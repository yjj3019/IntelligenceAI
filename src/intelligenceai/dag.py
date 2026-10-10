"""Offline DAG execution: serialized writers and concurrent immutable static inspection."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import checkers, fixture
from .contracts import Check, Plan, StepResult
from .security import SafetyError, digest


def write_scope(plan: Plan) -> list[str]:
    return sorted({p for step in plan.steps if step.mode == "write" for p in step.allowed_paths})


def validate_executable_plan(plan: Plan):
    from .registry import authorize_step

    for step in plan.steps:
        authorize_step(step)
        if step.executor == "fixture" and step.allowed_paths != [
            fixture.profile_path(step.profile)
        ]:
            raise SafetyError("fixture supports only its registered profile path")


def capture(target: Path, candidate) -> dict[str, bytes]:
    payloads = {}
    for name, expected in candidate.artifact_digests.items():
        value = (target / name).read_bytes()
        if hashlib.sha256(value).hexdigest() != expected:
            raise SafetyError("candidate drift before parallel inspection")
        payloads[name] = value
    return payloads


def inspect_step(step, payloads, candidate):
    checks = step.checks
    if step.executor == "fixture" and not checks:
        name = fixture.profile_path(step.profile)
        checks = [
            Check(kind="python_ast", path=name, expected_literals={"ANSWER": 42})
            if step.profile == "answer-v1"
            else Check(
                kind="json_shape",
                path=name,
                required_keys=["enabled", "version"],
                expected_literals={"enabled": True, "version": 42},
            )
        ]
    results = [checkers.inspect(check, payloads, candidate.candidate_id) for check in checks]
    evidence = [e.model_dump() for e, _ in results]
    findings = [f.model_dump() for _, fs in results for f in fs]
    status = (
        "FAILED"
        if any(e["status"] == "FAIL" for e in evidence)
        else "UNVERIFIED"
        if any(e["status"] == "UNVERIFIED" for e in evidence)
        else "SUCCEEDED"
    )
    return status, evidence, findings


def execute(controller, state):
    tid, round_number = state["task_id"], state.get("round_number", 0)
    generation = controller._generation(state)
    data = controller.metadata(tid)
    plan = Plan.model_validate(data["plan"])
    validate_executable_plan(plan)
    controller.ledger.state(tid, "RUNNING", expected_generation=generation)
    target = Path(data["workspace"])
    while True:
        completed = {
            r["step_id"]: r["result"]
            for r in controller.ledger.steps(tid, round_number)
            if r["result"]
        }
        pending = [s for s in plan.steps if s.step_id not in completed]
        if not pending:
            break
        blocked = [
            s
            for s in pending
            if any(
                d in completed and completed[d]["status"] in {"FAILED", "BLOCKED", "UNVERIFIED"}
                for d in s.dependencies
            )
        ]
        candidate = controller.candidate(tid)

        def finish(step, status, evidence, findings):
            refs = {d: completed[d]["result_id"] for d in step.result_refs if d in completed}
            result = StepResult(
                step_id=step.step_id,
                round_number=round_number,
                generation=generation,
                status=status,
                candidate_id=candidate.candidate_id,
                result_id=digest(
                    [
                        step.step_id,
                        round_number,
                        generation,
                        candidate.candidate_id,
                        status,
                        refs,
                        evidence,
                        findings,
                    ]
                ),
                references=refs,
                evidence=evidence,
                findings=findings,
            )
            controller.ledger.step_finish(tid, result)
            controller._crash("step_committed")

        if blocked:
            for step in blocked:
                finish(step, "BLOCKED", [], [])
            continue
        ready = [s for s in pending if set(s.dependencies) <= completed.keys()]
        if not ready:
            raise SafetyError("DAG cannot make validated progress")
        writers = [s for s in ready if s.mode == "write"]
        if writers:
            step = writers[0]
            controller.ledger.step_start(tid, step.step_id, round_number, generation)
            controller._fixture_step(state, step)
            candidate = controller.candidate(tid)
            finish(step, "SUCCEEDED", [], [])
            continue
        payloads = capture(target, candidate)
        for step in ready:
            controller.ledger.step_start(tid, step.step_id, round_number, generation)
        # These functions only parse the same immutable bytes. No ledger or filesystem writes.
        with ThreadPoolExecutor(max_workers=min(3, len(ready))) as pool:
            outputs = list(pool.map(lambda step: inspect_step(step, payloads, candidate), ready))
        if controller.candidate(tid) != candidate:
            raise SafetyError("candidate changed during parallel review")
        for step, (status, evidence, findings) in zip(ready, outputs, strict=True):
            finish(step, status, evidence, findings)
    return {"round_number": round_number}
