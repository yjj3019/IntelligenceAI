import time
import uuid

from .contracts import Action, Approval, Candidate
from .ledger import Ledger
from .security import SafetyError, canonical, digest, require_no_secrets

REQUIRED = {"outbound-gitleaks-v1", "candidate-gitleaks-v1", "fixture-assertion-v1"}


def subject(task: dict, action: Action, result: dict) -> str:
    require_no_secrets(action.model_dump())
    return digest(
        {
            "repo": task["data"]["repo_identity"],
            "base": task["data"]["base_sha"],
            "generation": task["generation"],
            "plan_version": task["data"]["plan_version"],
            "policy": task["data"]["policy_version"],
            "action": action.model_dump(),
            "candidate": result["candidate"],
            "evidence": result["evidence"],
            "findings": result["findings"],
            "scope": result["allowed_paths"],
        }
    )


def ready(result: dict):
    candidate = Candidate.model_validate(result["candidate"])
    evidence = result["evidence"]
    if (
        len(evidence) != len(REQUIRED)
        or {e["command_profile"] for e in evidence} != REQUIRED
        or any(
            e["status"] != "PASS"
            or e["exit_code"] != 0
            or e["candidate_id"] != candidate.candidate_id
            for e in evidence
        )
    ):
        raise SafetyError("required evidence missing, failed, unverified, or stale")
    if any(f["blocking"] and f["resolution"] != "resolved" for f in result["findings"]):
        raise SafetyError("blocking findings unresolved")
    # A scanner stub cannot authorize external actions.
    if any(
        not e["live"] or e["tool_version"] != "gitleaks-8.30.1"
        for e in evidence
        if e["command_profile"].endswith("gitleaks-v1")
    ):
        raise SafetyError("fixture scanner evidence cannot authorize external actions")


def decide(
    ledger: Ledger,
    task_id: str,
    action: Action,
    candidate: Candidate,
    principal: str,
    decision: str,
    ttl_seconds: int = 900,
) -> Approval:
    task = ledger.task(task_id)
    if not task["result"] or task["state"] not in {"COMPLETED", "READY_FOR_APPROVAL"}:
        raise SafetyError("task is not ready for approval")
    result = task["result"]
    if candidate.model_dump() != result["candidate"]:
        raise SafetyError("candidate changed; previous evidence invalidated")
    if decision == "approve":
        ready(result)
    if not 1 <= ttl_seconds <= 3600:
        raise SafetyError("approval expiry out of bounds")
    approval = Approval(
        approval_id=str(uuid.uuid4()),
        principal=principal,
        action_digest=subject(task, action, result),
        candidate_id=candidate.candidate_id,
        policy_version=task["data"]["policy_version"],
        scope=result["allowed_paths"],
        decision=decision,
        expires_at=time.time() + ttl_seconds,
    )
    ledger.db.execute(
        "INSERT OR REPLACE INTO approvals VALUES(?,?)", (task_id, canonical(approval.model_dump()))
    )
    ledger.event(task_id, {"decision": decision, "approval_id": approval.approval_id})
    return approval


def dry_run(ledger: Ledger, task_id: str, action: Action, candidate: Candidate) -> dict:
    import json

    task = ledger.task(task_id)
    if task["state"] not in {"COMPLETED", "READY_FOR_APPROVAL"}:
        raise SafetyError("task cannot enter external gate")
    result = task["result"]
    ready(result)
    row = ledger.db.execute("SELECT data FROM approvals WHERE task_id=?", (task_id,)).fetchone()
    if row is None:
        raise SafetyError("approval required")
    approval = Approval.model_validate(json.loads(row[0]))
    if (
        approval.decision != "approve"
        or approval.expires_at <= time.time()
        or approval.candidate_id != candidate.candidate_id
        or candidate.model_dump() != result["candidate"]
        or approval.action_digest != subject(task, action, result)
    ):
        raise SafetyError("approval rejected, expired, or invalidated by drift")
    return {
        "dry_run": True,
        "external_actions_enabled": False,
        "external_action_count": 0,
        "action_digest": approval.action_digest,
        "candidate_id": candidate.candidate_id,
    }
