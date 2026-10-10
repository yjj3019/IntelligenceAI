import json
import time
from pathlib import Path

import pytest

from intelligenceai.contracts import Action
from intelligenceai.security import SafetyError, canonical

ACTION = Action(kind="push", destination="example.invalid/repo", argv=["push", "fixture"])


def approved(ctl, repo):
    task = ctl.submit(repo, "fixture")
    ctl.run(task)
    ctl.approve(task, ACTION, "operator")
    return task


@pytest.mark.parametrize(
    "mutation",
    [
        "bytes",
        "untracked",
        "base",
        "policy",
        "evidence",
        "scope",
        "expiry",
        "destination",
        "argv",
        "reject",
    ],
)
def test_exact_approval_drift(approval_controller, repo, mutation):
    ctl = approval_controller
    task = approved(ctl, repo)
    target = Path(ctl.metadata(task)["workspace"])
    act = ACTION
    if mutation == "bytes":
        (target / "answer.py").write_text("ANSWER = 43\n")
    elif mutation == "untracked":
        (target / "extra.txt").write_text("new")
    elif mutation in {"base", "policy"}:
        data = ctl.metadata(task)
        data["base_sha" if mutation == "base" else "policy_version"] = "changed"
        ctl.ledger.db.execute("UPDATE tasks SET data=? WHERE id=?", (canonical(data), task))
    elif mutation in {"evidence", "scope"}:
        result = ctl.ledger.task(task)["result"]
        if mutation == "evidence":
            result["evidence"][0]["redacted_log"] = "changed proof"
        else:
            result["allowed_paths"] = ["extra.txt"]
        ctl.ledger.set_result(task, result)
    elif mutation in {"expiry", "reject"}:
        row = json.loads(
            ctl.ledger.db.execute("SELECT data FROM approvals WHERE task_id=?", (task,)).fetchone()[
                0
            ]
        )
        if mutation == "expiry":
            row["expires_at"] = time.time() - 1
        else:
            row["decision"] = "reject"
        ctl.ledger.db.execute("UPDATE approvals SET data=? WHERE task_id=?", (canonical(row), task))
    elif mutation == "destination":
        act = ACTION.model_copy(update={"destination": "different.invalid"})
    elif mutation == "argv":
        act = ACTION.model_copy(update={"argv": ["merge", "other"]})
    with pytest.raises(SafetyError):
        ctl.dry_run(task, act)
    assert ctl.status(task)["result"]["external_action_count"] == 0


def test_failure_invalidates_approval_even_if_bytes_restored(approval_controller, repo):
    ctl = approval_controller
    task = approved(ctl, repo)
    path = Path(ctl.metadata(task)["workspace"]) / "answer.py"
    original = path.read_bytes()
    path.write_text("ANSWER = 0\n")
    with pytest.raises(SafetyError):
        ctl.dry_run(task, ACTION)
    path.write_bytes(original)
    with pytest.raises(SafetyError):
        ctl.dry_run(task, ACTION)
