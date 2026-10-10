import copy
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import StubScanner
from test_dag import sample_plan
from test_mcp_stdio import static_plan

from intelligenceai import fixture, workspace
from intelligenceai.approvals import ready
from intelligenceai.contracts import Action, Check, Plan
from intelligenceai.controller import Controller, fixture_plan
from intelligenceai.ownership import TaskLease
from intelligenceai.security import SafetyError
from intelligenceai.service import ControllerService

ACTION = Action(kind="push", destination="example.invalid/repo", argv=["push", "fixture"])


def seed(repo, kind):
    path = repo / ("module.py" if kind == "python" else "manifest.json")
    path.write_text("def preserved(): pass\n" if kind == "python" else '{"name":"owned"}\n')
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "owned gate sample"],
        check=True,
        capture_output=True,
    )


@pytest.mark.parametrize("kind", ["python", "json", "static-only"])
def test_plan_specific_submit_run_approve_dry_run(repo, tmp_path, kind):
    ctl = Controller(tmp_path / "state", scanner=StubScanner(live=True))
    try:
        if kind == "static-only":
            plan = static_plan()
        else:
            seed(repo, kind)
            base = sample_plan(kind)
            # The writer's declared required check must also run and bind to its receipt.
            writer = base.steps[0].model_copy(update={"checks": base.steps[1].checks})
            plan = Plan(steps=[writer, *base.steps[1:]])
        tid = ctl.submit(repo, "owned approval sample", plan)
        assert ctl.run(tid)["state"] == "READY_FOR_APPROVAL"
        baseline = ctl.ledger.task(tid)["result"]
        for mutation in ("missing", "unknown", "candidate", "check", "duplicate", "receipt"):
            result = copy.deepcopy(baseline)
            if mutation == "missing":
                result["evidence"].pop()
            elif mutation == "unknown":
                result["evidence"][-1]["command_profile"] = "unregistered-check"
            elif mutation == "candidate":
                result["evidence"][-1]["candidate_id"] = "other-candidate"
            elif mutation == "check":
                result["evidence"][-1]["check_digest"] = "b" * 64
            elif mutation == "duplicate":
                result["evidence"].append(result["evidence"][-1])
            else:
                result["steps"].pop()
            with pytest.raises(SafetyError):
                ready(ctl.ledger.task(tid), result, ctl.ledger)
        ctl.approve(tid, ACTION, "local-operator")
        assert ctl.status(tid)["state"] == "COMPLETED"
        assert ctl.dry_run(tid, ACTION)["external_action_count"] == 0
        # An evidence validation failure permanently revokes the prior approval.
        changed = copy.deepcopy(baseline)
        changed["evidence"].pop()
        ctl.ledger.set_result(tid, changed)
        with pytest.raises(SafetyError):
            ctl.dry_run(tid, ACTION)
        ctl.ledger.set_result(tid, baseline)
        with pytest.raises(SafetyError):
            ctl.dry_run(tid, ACTION)
        assert ctl.status(tid)["state"] == "BLOCKED"
    finally:
        ctl.close()


@pytest.mark.parametrize("kind", ["test_command", "build_command"])
def test_writer_declared_unverified_command_never_skipped(repo, tmp_path, kind):
    ctl = Controller(tmp_path / "state", scanner=StubScanner(live=True))
    try:
        writer = (
            fixture_plan()
            .steps[0]
            .model_copy(update={"checks": [Check(kind=kind, path="answer.py")]})
        )
        tid = ctl.submit(repo, "required writer check", Plan(steps=[writer]))
        status = ctl.run(tid)
        assert status["state"] == "UNVERIFIED"
        row = status["result"]["steps"][0]
        assert row["status"] == "UNVERIFIED" and row["evidence"][0]["command_profile"] == kind
        with pytest.raises(SafetyError):
            ctl.approve(tid, ACTION, "operator")
    finally:
        ctl.close()


def test_cancel_during_admission_duplicate_never_resurrects_writer(repo, tmp_path, monkeypatch):
    service = ControllerService(tmp_path / "state", {"sample": repo})
    entered, release = threading.Event(), threading.Event()
    original = workspace.prepare
    effects = []

    def held(*args):
        entered.set()
        assert release.wait(30)
        return original(*args)

    monkeypatch.setattr(workspace, "prepare", held)
    monkeypatch.setattr(fixture, "implement", lambda *a, **k: effects.append(True))
    args = {
        "repository": "sample",
        "request": "owned admission",
        "idempotency_key": "admission-race",
    }
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(service.call, "submit", args)
            assert entered.wait(30)
            duplicate = service.call("submit", args)
            assert duplicate["duplicate"] and duplicate["admission"] == "CLAIMED"
            tid = duplicate["task_id"]
            assert service.call("cancel", {"task_id": tid})["generation"] == 2
            release.set()
            with pytest.raises(SafetyError):
                pending.result(timeout=60)
        status = service.call("status", {"task_id": tid})
        assert status["state"] == "CANCELLED" and status["generation"] == 2
        assert not effects and not status["invocations"]
        assert service.call("submit", args)["task_id"] == tid
    finally:
        release.set()
        service.close()


def test_two_hosts_grants_and_active_controller_owner(repo, tmp_path):
    root = tmp_path / "state"
    other = tmp_path / "other-repository"
    other.mkdir()
    ctl = Controller(root, scanner=StubScanner())
    tid = ctl.submit(repo, "active owned task")
    ctl.ledger.state(tid, "RUNNING", expected_generation=1)
    record = ctl.ledger.reserve(tid, fixture_plan().steps[0], 0, ctl.metadata(tid)["workspace"])
    ctl.ledger.start(record["id"])
    before = ctl.ledger.task(tid)
    try:
        with TaskLease(root, tid) as first:
            assert first.acquired
            with TaskLease(root, tid) as second:
                assert not second.acquired
            for grants in ({"other": other}, {"same": repo}):
                host = ControllerService(root, grants)
                host.close()
                assert ctl.ledger.task(tid) == before
            with pytest.raises(SafetyError, match="another controller"):
                ctl.run(tid)
        # A crash residue can be reconciled only by a host granted this repository.
        host = ControllerService(root, {"other": other})
        host.close()
        assert ctl.ledger.task(tid) == before
        host = ControllerService(root, {"same": repo})
        host.close()
        assert ctl.ledger.task(tid)["state"] == "NEEDS_RECONCILIATION"
    finally:
        ctl.close()
