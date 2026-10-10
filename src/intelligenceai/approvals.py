import time
import uuid
from collections import Counter

from .contracts import Action, Approval, Candidate, Evidence, Finding, Plan, StepResult
from .ledger import Ledger
from .security import SafetyError, canonical, digest, require_no_secrets


def subject(task: dict, action: Action, result: dict) -> str:
    require_no_secrets(action.model_dump())
    return digest(
        {
            "repo": task["data"]["repo_identity"],
            "base": task["data"]["base_sha"],
            "generation": task["generation"],
            "plan_version": task["data"]["plan_version"],
            "plan": task["data"]["plan"],
            "policy": task["data"]["policy_version"],
            "action": action.model_dump(),
            "candidate": result["candidate"],
            "evidence": result["evidence"],
            "findings": result["findings"],
            "scope": result["allowed_paths"],
        }
    )


def ready(task: dict, result: dict, ledger: Ledger):
    from .dag import checks_for, validate_executable_plan, write_scope

    plan = Plan.model_validate(task["data"]["plan"])
    validate_executable_plan(plan)
    candidate = Candidate.model_validate(result["candidate"])
    evidence = [Evidence.model_validate(e) for e in result["evidence"]]
    if any(not e.live for e in evidence if e.command_profile.endswith("gitleaks-v1")):
        raise SafetyError("fixture scanner evidence cannot authorize external actions")
    expected = Counter(
        (profile, None, None, "gitleaks-8.30.1")
        for profile in ("outbound-gitleaks-v1", "candidate-gitleaks-v1")
    )
    for step in plan.steps:
        if step.mode == "write":
            profile = (
                "fixture-assertion-v1" if step.profile == "answer-v1" else "fixture-json-config-v1"
            )
            expected[
                (
                    profile,
                    step.step_id,
                    digest(["fixture-profile", step.profile]),
                    "intelligenceai-fixture-v1",
                )
            ] += 1
        for check in checks_for(step):
            profile = (
                check.kind
                if check.kind in {"test_command", "build_command"}
                else "static-" + check.kind + "-v1"
            )
            tool = (
                "disabled-os-contract"
                if check.kind in {"test_command", "build_command"}
                else "intelligenceai-static-v1"
            )
            expected[(profile, step.step_id, digest(check.model_dump()), tool)] += 1
    actual = Counter(
        (e.command_profile, e.step_id, e.check_digest, e.tool_version) for e in evidence
    )
    if (
        actual != expected
        or any(
            e.status != "PASS" or e.exit_code != 0 or e.candidate_id != candidate.candidate_id
            for e in evidence
        )
        or result["allowed_paths"] != write_scope(plan)
    ):
        raise SafetyError("required evidence missing, failed, unverified, or stale")
    latest = ledger.db.execute(
        "SELECT max(round) FROM step_runs WHERE task_id=?", (task["id"],)
    ).fetchone()[0]
    receipts = [r["result"] for r in ledger.steps(task["id"], latest)] if latest is not None else []
    if receipts != result["steps"] or {r["step_id"] for r in receipts} != {
        s.step_id for s in plan.steps
    }:
        raise SafetyError("complete matching authoritative step receipts required")
    for receipt in receipts:
        row = StepResult.model_validate(receipt)
        if row.status != "SUCCEEDED" or row.generation != task["generation"]:
            raise SafetyError("unfinished or stale step receipt")
        if row.evidence and row.candidate_id != candidate.candidate_id:
            raise SafetyError("checker receipt bound to an earlier candidate")
    checker_profiles = {"test_command", "build_command"}
    actual_checks = Counter(
        canonical(e.model_dump())
        for e in evidence
        if e.command_profile.startswith("static-") or e.command_profile in checker_profiles
    )
    recorded_checks = Counter(canonical(e) for r in receipts for e in r["evidence"])
    if actual_checks != recorded_checks:
        raise SafetyError("checker evidence differs from authoritative step receipts")
    findings = [Finding.model_validate(f) for f in result["findings"]]
    if any(
        f.candidate_id != candidate.candidate_id or (f.blocking and f.resolution != "resolved")
        for f in findings
    ):
        raise SafetyError("blocking findings unresolved")


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
        require_ready(task, result, ledger)
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
    require_ready(task, result, ledger)
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


def require_ready(task: dict, result: dict, ledger: Ledger):
    try:
        ready(task, result, ledger)
    except Exception as exc:
        ledger.invalidate_candidate(task["id"])
        if isinstance(exc, SafetyError):
            raise
        raise SafetyError("required approval proof invalid; previous approval revoked") from exc
