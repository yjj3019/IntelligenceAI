import pytest

from intelligenceai.contracts import Budgets, Step, Task
from intelligenceai.ledger import Ledger
from intelligenceai.security import SafetyError


def test_concurrent_start_limit_even_when_all_reserved_first(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite")
    step = Step(step_id="review", role="review", mode="read_only", allowed_paths=["answer.py"])
    records = []
    try:
        for i in range(4):
            task = Task(
                task_id=str(i), redacted_request="fixture", repo_identity="fixture", base_sha="base"
            )
            ledger.create(task)
            records.append(ledger.reserve(str(i), step, 0, str(i)))
        for record in records[:3]:
            assert ledger.start(record["id"])
        with pytest.raises(SafetyError, match="concurrent"):
            ledger.start(records[3]["id"])
    finally:
        ledger.close()


def test_same_failure_limit_independent_of_repair_limit(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite")
    try:
        ledger.create(
            Task(
                task_id="task",
                redacted_request="fixture",
                repo_identity="fixture",
                base_sha="base",
                budgets=Budgets(max_repairs=2),
            )
        )
        assert ledger.repair("task", "same-error")
        assert ledger.repair("task", "same-error")
        assert not ledger.repair("task", "same-error")
        assert ledger.task("task")["state"] == "BLOCKED"
    finally:
        ledger.close()
