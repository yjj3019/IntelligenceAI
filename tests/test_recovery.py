from pathlib import Path

import pytest
from conftest import StubScanner

from intelligenceai.controller import Controller, fixture_plan
from intelligenceai.security import SafetyError


@pytest.mark.parametrize(
    "boundary,expected",
    [
        ("reserved", "READY_FOR_APPROVAL"),
        ("started", "NEEDS_RECONCILIATION"),
        ("effect", "NEEDS_RECONCILIATION"),
        ("receipt", "READY_FOR_APPROVAL"),
        ("verified", "READY_FOR_APPROVAL"),
    ],
)
def test_crash_boundaries(repo, tmp_path, boundary, expected):
    root = tmp_path / "state"
    ctl = Controller(root, scanner=StubScanner(), crash_at=boundary)
    task = ctl.submit(repo, "crash")
    with pytest.raises(RuntimeError, match="injected"):
        ctl.run(task)
    target = Path(ctl.metadata(task)["workspace"])
    before = (target / "answer.py").read_bytes() if (target / "answer.py").exists() else None
    ctl.close()
    fresh = Controller(root, scanner=StubScanner())
    try:
        result = fresh.run(task)
        assert result["state"] == expected
        assert len(result["invocations"]) == 1
        if expected == "NEEDS_RECONCILIATION":
            assert (
                (target / "answer.py").read_bytes() if (target / "answer.py").exists() else None
            ) == before
            assert fresh.ledger.db.execute("SELECT count(*) FROM writers").fetchone()[0] == 1
            assert fresh.run(task)["state"] == expected
    finally:
        fresh.close()


def test_duplicate_receipt_idempotent_and_conflict_refused(controller, repo):
    task = controller.submit(repo, "fixture")
    record = controller.ledger.reserve(
        task, fixture_plan().steps[0], 0, controller.metadata(task)["workspace"]
    )
    assert controller.ledger.start(record["id"])
    assert controller.ledger.receive(record["id"], 1, {"status": "ok"})
    assert not controller.ledger.receive(record["id"], 1, {"status": "ok"})
    with pytest.raises(SafetyError, match="conflicting"):
        controller.ledger.receive(record["id"], 1, {"status": "different"})


def test_cancel_unknown_keeps_writer_and_refuses_stale(controller, repo):
    task = controller.submit(repo, "fixture")
    record = controller.ledger.reserve(
        task, fixture_plan().steps[0], 0, controller.metadata(task)["workspace"]
    )
    controller.ledger.start(record["id"])
    controller.ledger.cancel(task)
    assert controller.status(task)["state"] == "NEEDS_RECONCILIATION"
    with pytest.raises(SafetyError, match="stale"):
        controller.ledger.receive(record["id"], 1, {"status": "ok"})
    with pytest.raises(SafetyError):
        controller.ledger.reserve(
            task, fixture_plan().steps[0], 1, controller.metadata(task)["workspace"]
        )
    assert controller.ledger.db.execute("SELECT count(*) FROM writers").fetchone()[0] == 1


def test_single_writer_across_tasks(controller, repo):
    first = controller.submit(repo, "first")
    second = controller.submit(repo, "second")
    workspace = controller.metadata(first)["workspace"]
    controller.ledger.reserve(first, fixture_plan().steps[0], 0, workspace)
    with pytest.raises(SafetyError, match="writer"):
        controller.ledger.reserve(second, fixture_plan().steps[0], 0, workspace)
