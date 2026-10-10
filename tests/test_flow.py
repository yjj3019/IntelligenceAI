import json
from pathlib import Path

import pytest
from conftest import StubScanner

from intelligenceai.cli import main
from intelligenceai.contracts import Action
from intelligenceai.controller import Controller
from intelligenceai.security import SafetyError


def action(destination="example.invalid/repo"):
    return Action(kind="push", destination=destination, argv=["push", destination])


def test_vertical_flow_preserves_checkout(controller, repo):
    (repo / "user.txt").write_text("user edit\n")
    (repo / "personal.txt").write_text("untracked\n")
    task = controller.submit(repo, "fixture")
    result = controller.run(task)
    assert result["state"] == "READY_FOR_APPROVAL"
    assert result["result"]["candidate"]["changed_paths"] == ["answer.py"]
    assert (repo / "user.txt").read_text() == "user edit\n"
    assert (repo / "personal.txt").read_text() == "untracked\n"
    assert not (repo / "answer.py").exists()
    assert result["result"]["external_action_count"] == 0


def test_reproduced_fixture_repaired(controller, repo):
    task = controller.submit(repo, "fixture", scenario="repair")
    result = controller.run(task)
    assert result["state"] == "READY_FOR_APPROVAL"
    assert result["repairs"] == 1
    assert len(result["invocations"]) == 2
    assert not result["result"]["findings"]


def test_repair_exhaustion_is_blocked(controller, repo):
    task = controller.submit(repo, "fixture", scenario="exhaust")
    result = controller.run(task)
    assert result["state"] == "BLOCKED"
    assert result["repairs"] == 2
    assert len(result["invocations"]) == 3


@pytest.mark.parametrize("status,state", [("UNVERIFIED", "UNVERIFIED"), ("FAIL", "FAILED")])
def test_required_scan_blocks(repo, tmp_path, status, state):
    ctl = Controller(tmp_path / "state", scanner=StubScanner(status))
    try:
        task = ctl.submit(repo, "fixture")
        assert ctl.run(task)["state"] == state
        with pytest.raises(SafetyError):
            ctl.approve(task, action(), "operator")
    finally:
        ctl.close()


def test_fixture_scanner_cannot_approve(controller, repo):
    task = controller.submit(repo, "fixture")
    controller.run(task)
    with pytest.raises(SafetyError, match="fixture scanner"):
        controller.approve(task, action(), "operator")


def test_persistent_interrupt_resume(approval_controller, repo, tmp_path):
    ctl = approval_controller
    task = ctl.submit(repo, "fixture")
    ctl.run(task)
    assert ctl.graph.get_state(ctl.config(task)).interrupts
    # Simulate a new process/connection, with actual SqliteSaver.
    fresh = Controller(tmp_path / "state", scanner=StubScanner(live=True))
    try:
        fresh.approve(task, action(), "operator")
        assert fresh.status(task)["state"] == "COMPLETED"
        assert len(fresh.status(task)["invocations"]) == 1
        assert fresh.dry_run(task, action())["external_action_count"] == 0
    finally:
        fresh.close()


def test_reject_and_cancel_no_launch(controller, repo):
    task = controller.submit(repo, "fixture")
    controller.reject(task)
    assert controller.run(task)["state"] == "CANCELLED"
    assert not controller.status(task)["invocations"]


def test_cli_offline_e2e(repo, tmp_path, capsys, monkeypatch):
    import shutil

    original = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda name: None if name == "gitleaks" else original(name)
    )
    root = str(tmp_path / "cli-state")
    assert (
        main(["--state-dir", root, "submit", "--repo", str(repo), "--request", "fixture", "--run"])
        == 0
    )
    submitted = json.loads(capsys.readouterr().out)
    assert submitted["state"] == "UNVERIFIED"  # No native Windows/live scanner certificate.
    assert main(["--state-dir", root, "results", submitted["task_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["external_action_count"] == 0
    assert (
        main(
            [
                "--state-dir",
                root,
                "approve",
                submitted["task_id"],
                "--action",
                "push",
                "--destination",
                "example.invalid/repo",
            ]
        )
        == 2
    )


def test_scope_violation_is_blocked(controller, repo):
    task = controller.submit(repo, "fixture")
    target = Path(controller.metadata(task)["workspace"])
    (target / "unauthorized.txt").write_text("outside scope")
    assert controller.run(task)["state"] == "BLOCKED"
