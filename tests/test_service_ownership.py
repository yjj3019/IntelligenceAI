import threading
from concurrent.futures import ThreadPoolExecutor

from conftest import StubScanner

from intelligenceai.controller import Controller
from intelligenceai.ledger import Ledger
from intelligenceai.ownership import TaskLease
from intelligenceai.service import ControllerService


def test_mcp_runner_lease_conflict_does_not_block_active_cli(repo, tmp_path, monkeypatch):
    root = tmp_path / "state"
    service = ControllerService(root, {"sample": repo})
    mcp_waiting, mcp_release, mcp_finished = (threading.Event() for _ in range(3))
    cli_owned, cli_release = threading.Event(), threading.Event()
    original_run, original_owned = Controller.run, Controller._run_owned
    original_service_run = service._run
    outcomes = []

    def held_run(self, tid):
        if threading.current_thread().name.startswith("iai-local"):
            mcp_waiting.set()
            assert mcp_release.wait(30)
        return original_run(self, tid)

    def held_owned(self, tid):
        if threading.current_thread().name.startswith("owned-cli"):
            cli_owned.set()
            assert cli_release.wait(30)
        return original_owned(self, tid)

    def service_run(tid):
        try:
            outcomes.append(original_service_run(tid))
        finally:
            mcp_finished.set()

    def cli_run(tid):
        ctl = Controller(root, scanner=StubScanner(live=True))
        try:
            return ctl.run(tid)
        finally:
            ctl.close()

    monkeypatch.setattr(Controller, "run", held_run)
    monkeypatch.setattr(Controller, "_run_owned", held_owned)
    monkeypatch.setattr(service, "_run", service_run)
    try:
        submitted = service.call(
            "submit",
            {"repository": "sample", "request": "owned race", "idempotency_key": "lease-race"},
        )
        tid = submitted["task_id"]
        assert mcp_waiting.wait(30)
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="owned-cli") as pool:
            pending = pool.submit(cli_run, tid)
            try:
                assert cli_owned.wait(30)
                observer = Controller(root)
                try:
                    before = observer.ledger.task(tid)
                    invocations = observer.ledger.invocations(tid)
                    mcp_release.set()
                    assert mcp_finished.wait(30)
                    assert outcomes == [{"task_id": tid, "execution": "OWNED_ELSEWHERE"}]
                    assert tid not in service.active
                    assert observer.ledger.task(tid) == before
                    assert observer.ledger.invocations(tid) == invocations
                finally:
                    observer.close()
            finally:
                cli_release.set()
            assert pending.result(timeout=120)["state"] == "READY_FOR_APPROVAL"
    finally:
        mcp_release.set()
        cli_release.set()
        service.close()


def test_unexpected_service_failure_invalidates_only_while_owned(repo, tmp_path, monkeypatch):
    root = tmp_path / "state"
    service = ControllerService(root, {"sample": repo})
    finished = threading.Event()
    checks, outcomes = [], []

    def failure(self, tid):
        raise RuntimeError("owned synthetic failure")

    original_invalidate = Ledger.invalidate_candidate

    def owned_invalidate(self, tid):
        with TaskLease(root, tid) as observer:
            checks.append(not observer.acquired)
        return original_invalidate(self, tid)

    original_service_run = service._run

    def service_run(tid):
        try:
            outcomes.append(original_service_run(tid))
        finally:
            finished.set()

    monkeypatch.setattr(Controller, "_run_owned", failure)
    monkeypatch.setattr(Ledger, "invalidate_candidate", owned_invalidate)
    monkeypatch.setattr(service, "_run", service_run)
    try:
        tid = service.call(
            "submit",
            {"repository": "sample", "request": "owned failure", "idempotency_key": "failure"},
        )["task_id"]
        assert finished.wait(30)
        assert checks == [True]
        assert outcomes == [{"task_id": tid, "execution": "FAILED_OR_UNVERIFIED"}]
        assert service.call("status", {"task_id": tid})["state"] == "BLOCKED"
    finally:
        service.close()
