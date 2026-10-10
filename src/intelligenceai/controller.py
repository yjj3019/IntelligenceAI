import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import TypedDict

# Local-only defaults, set before importing graph components. No cloud tracing is configured.
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from . import dag, fixture, workspace
from .approvals import decide, dry_run
from .contracts import Action, Candidate, Evidence, Finding, Plan, State, Step, Task
from .ledger import Ledger
from .registry import authorize_step
from .scanner import GitleaksScanner
from .security import SafetyError, canonical, clean, digest, redact


class GraphState(TypedDict, total=False):
    task_id: str
    owner_generation: int
    round_number: int
    done: bool


def fixture_plan() -> Plan:
    return Plan(
        steps=[
            Step(
                step_id="implement",
                role="implement",
                mode="write",
                allowed_paths=[fixture.FIXTURE_FILE],
            )
        ]
    )


class Controller:
    def __init__(self, root: Path, scanner=None, crash_at: str | None = None):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(self.root / "ledger.sqlite")
        self.scanner = scanner or GitleaksScanner()
        self.crash_at = crash_at  # Test-only injection, unavailable through CLI or plans.
        connection = sqlite3.connect(self.root / "checkpoints.sqlite", check_same_thread=False)
        self.checkpoint_connection = connection
        self.checkpointer = SqliteSaver(connection)
        builder = StateGraph(GraphState)
        builder.add_node("execute", self._execute)
        builder.add_node("verify", self._verify)
        builder.add_node("route", self._route)
        builder.add_node("approval_wait", self._approval_wait)
        builder.add_edge(START, "execute")
        builder.add_edge("execute", "verify")
        builder.add_edge("verify", "route")
        builder.add_conditional_edges(
            "route",
            lambda s: "end" if s["done"] else "repair",
            {"end": "approval_wait", "repair": "execute"},
        )
        builder.add_edge("approval_wait", END)
        self.graph = builder.compile(checkpointer=self.checkpointer)

    def close(self):
        self.ledger.close()
        self.checkpoint_connection.close()

    def config(self, task_id: str) -> dict:
        return {"configurable": {"thread_id": task_id}, "recursion_limit": 20}

    def metadata(self, task_id: str) -> dict:
        row = self.ledger.task(task_id)
        return row["data"]

    def submit(
        self,
        repo: Path,
        request: str,
        plan: Plan | None = None,
        scenario: str = "success",
        *,
        _task_id: str | None = None,
    ) -> str:
        if scenario not in {"success", "repair", "exhaust"}:
            raise SafetyError("unknown fixture scenario")
        plan = Plan.model_validate((plan or fixture_plan()).model_dump())
        dag.validate_executable_plan(plan)
        repo, base = workspace.identity(repo)
        if self.root.is_relative_to(repo):
            raise SafetyError("controller state must be outside the user's repository")
        task_id = str(uuid.UUID(_task_id)) if _task_id else str(uuid.uuid4())
        task = Task(
            task_id=task_id,
            redacted_request=redact(request),
            repo_identity=digest(str(repo)),
            base_sha=base,
            budgets=plan.budgets,
        )
        self.ledger.create(task)
        target = workspace.prepare(repo, self.root, task_id, base)
        initial = workspace.baseline(target)
        data = task.model_dump() | {
            "plan": plan.model_dump(),
            "workspace": str(target),
            "initial": initial,
            "scenario": scenario,
        }
        self.ledger.db.execute(
            "UPDATE tasks SET data=?,state=? WHERE id=?",
            (canonical(clean(data)), State.READY, task_id),
        )
        return task_id

    def _crash(self, boundary: str):
        if self.crash_at == boundary:
            raise RuntimeError("injected crash at " + boundary)

    def _execute(self, state: GraphState) -> dict:
        return dag.execute(self, state)

    def _fixture_step(self, state: GraphState, step: Step) -> dict:
        tid, round_number = state["task_id"], state.get("round_number", 0)
        data = self.metadata(tid)
        authorize_step(step)
        generation = self._generation(state)
        self.ledger.state(tid, State.RUNNING, expected_generation=generation)
        record = self.ledger.reserve(
            tid, step, round_number, data["workspace"], expected_generation=generation
        )
        self._crash("reserved")
        if record["status"] == "SUCCEEDED":
            return {"round_number": round_number}
        if record["status"] != "RESERVED":
            self.ledger.state(tid, State.NEEDS_RECONCILIATION, expected_generation=generation)
            raise SafetyError("start intent uncertain; automatic replay refused")
        if not self.ledger.start(record["id"]):
            raise SafetyError("another owner already started invocation")
        self._crash("started")
        receipt = fixture.implement(
            Path(data["workspace"]),
            round_number,
            data["scenario"],
            ledger=self.ledger,
            invocation_id=record["id"],
            generation=generation,
            profile=step.profile,
        )
        self._crash("effect")
        self.ledger.receive(record["id"], record["generation"], receipt)
        self._crash("receipt")
        return {"round_number": round_number}

    def candidate(self, task_id: str) -> Candidate:
        data = self.metadata(task_id)
        plan = Plan.model_validate(data["plan"])
        return workspace.freeze(
            Path(data["workspace"]), data["base_sha"], data["initial"], dag.write_scope(plan)
        )

    def _verify(self, state: GraphState) -> dict:
        tid = state["task_id"]
        generation = self._generation(state)
        self.ledger.state(tid, State.VERIFYING, expected_generation=generation)
        data = self.metadata(tid)
        target = Path(data["workspace"])
        candidate = self.candidate(tid)
        outbound = [canonical({"request": data["redacted_request"], "plan": data["plan"]}).encode()]
        payloads = workspace.export(target, candidate)
        evidence = [
            self.scanner.scan(outbound, candidate.candidate_id, "outbound-gitleaks-v1"),
            self.scanner.scan(payloads, candidate.candidate_id, "candidate-gitleaks-v1"),
        ]
        self.ledger.state(tid, State.REVIEWING, expected_generation=generation)
        plan = Plan.model_validate(data["plan"])
        findings = []
        for step in plan.steps:
            if step.mode == "write":
                evidence.append(fixture.verify(target, candidate.candidate_id, step.profile))
                findings.extend(fixture.review(target, candidate.candidate_id, step.profile))
        step_rows = self.ledger.steps(tid, state.get("round_number", 0))
        for row in step_rows:
            result = row["result"]
            if not result:
                raise SafetyError("DAG has unfinished step receipts")
            if result["candidate_id"] == candidate.candidate_id:
                evidence.extend(Evidence.model_validate(e) for e in result["evidence"])
                findings.extend(Finding.model_validate(f) for f in result["findings"])
            elif result["evidence"]:
                evidence.append(
                    Evidence(
                        candidate_id=candidate.candidate_id,
                        command_profile="stale-step-evidence",
                        tool_version="controller-v1",
                        environment="local",
                        exit_code=None,
                        status="UNVERIFIED",
                        redacted_log="Earlier DAG result is bound to a previous candidate",
                        timestamp=time.time(),
                    )
                )
        # Check the candidate again after every inspection; changed bytes invalidate all evidence.
        if self.candidate(tid) != candidate:
            raise SafetyError("candidate changed during verification")
        result = {
            "candidate": candidate.model_dump(),
            "evidence": [e.model_dump() for e in evidence],
            "findings": [f.model_dump() for f in findings],
            "allowed_paths": dag.write_scope(plan),
            "scope": "offline-dag",
            "steps": [r["result"] for r in step_rows],
            "live_adapters": "UNVERIFIED",
            "external_action_count": 0,
        }
        self.ledger.set_result(tid, result, expected_generation=generation)
        self._crash("verified")
        return {}

    def _route(self, state: GraphState) -> dict:
        tid = state["task_id"]
        task = self.ledger.task(tid)
        result = task["result"]
        generation = self._generation(state)
        blockers = [f for f in result["findings"] if f["blocking"] and f["reproduced"]]
        if blockers:
            if not any(s.mode == "write" for s in Plan.model_validate(task["data"]["plan"]).steps):
                self.ledger.state(tid, State.BLOCKED, expected_generation=generation)
                return {"done": True}
            signature = digest([f["finding_id"] for f in blockers])
            operation_id = digest(
                [
                    "repair",
                    tid,
                    generation,
                    state.get("round_number", 0),
                    result["candidate"]["candidate_id"],
                    signature,
                    task["data"]["policy_version"],
                ]
            )
            allowed = self.ledger.repair(
                tid, signature, operation_id=operation_id, expected_generation=generation
            )
            self._crash("repair_committed")
            if allowed:
                return {"round_number": state.get("round_number", 0) + 1, "done": False}
            return {"done": True}
        status = (
            State.FAILED
            if any(e["status"] == "FAIL" for e in result["evidence"])
            else State.UNVERIFIED
            if any(e["status"] == "UNVERIFIED" for e in result["evidence"])
            else State.READY_FOR_APPROVAL
        )
        self.ledger.state(tid, status, expected_generation=generation)
        return {"done": True}

    def _approval_wait(self, state: GraphState) -> dict:
        tid = state["task_id"]
        if self.ledger.task(tid)["state"] == State.READY_FOR_APPROVAL:
            # No external effects before/after this interrupt. Ledger is still authoritative.
            decision = interrupt({"task_id": tid, "candidate_id": self.candidate(tid).candidate_id})
            if decision != "local-complete":
                raise SafetyError("unrecognized authenticated controller resume")
            self.ledger.state(tid, State.COMPLETED, expected_generation=self._generation(state))
        return {}

    def run(self, task_id: str) -> dict:
        task = self.ledger.task(task_id)
        if task["state"] in {
            State.COMPLETED,
            State.UNVERIFIED,
            State.FAILED,
            State.BLOCKED,
            State.CANCELLED,
            State.NEEDS_RECONCILIATION,
        }:
            return self.status(task_id)
        if not self.ledger.reconcile(task_id):
            return self.status(task_id)
        checkpoint = self.graph.get_state(self.config(task_id))
        try:
            if checkpoint.values:
                if "owner_generation" not in checkpoint.values:
                    raise SafetyError("legacy checkpoint requires explicit reconciliation")
                self.graph.invoke(None, self.config(task_id))
            else:
                self.graph.invoke(
                    {"task_id": task_id, "round_number": 0, "owner_generation": task["generation"]},
                    self.config(task_id),
                )
        except (SafetyError, ValueError, OSError):
            current = self.ledger.task(task_id)
            if current["generation"] == task["generation"] and current["state"] not in {
                State.NEEDS_RECONCILIATION,
                State.CANCELLED,
                State.BLOCKED,
                State.FAILED,
            }:
                self.ledger.state(task_id, State.BLOCKED, expected_generation=task["generation"])
            self.ledger.event(task_id, {"error": "execution or candidate validation failed"})
        return self.status(task_id)

    def approve(self, task_id: str, action: Action, principal: str, ttl: int = 900):
        candidate = self._gate_candidate(task_id)
        approval = decide(self.ledger, task_id, action, candidate, principal, "approve", ttl)
        if self.graph.get_state(self.config(task_id)).interrupts:
            self.graph.invoke(Command(resume="local-complete"), self.config(task_id))
        return approval.model_dump()

    def reject(self, task_id: str):
        self.ledger.cancel(task_id)
        self.ledger.event(task_id, {"decision": "reject"})

    def dry_run(self, task_id: str, action: Action) -> dict:
        return dry_run(self.ledger, task_id, action, self._gate_candidate(task_id))

    def _gate_candidate(self, task_id: str) -> Candidate:
        try:
            candidate = self.candidate(task_id)
            result = self.ledger.task(task_id)["result"]
            if not result or result["candidate"] != candidate.model_dump():
                raise SafetyError("candidate drift invalidated evidence and approval")
            return candidate
        except Exception as exc:
            self.ledger.invalidate_candidate(task_id)
            raise SafetyError(
                "candidate validation failed; approval permanently invalidated"
            ) from exc

    def _generation(self, state: GraphState) -> int:
        generation = state.get("owner_generation")
        if generation is None or self.ledger.task(state["task_id"])["generation"] != generation:
            raise SafetyError("missing or stale graph owner generation")
        return generation

    def status(self, task_id: str) -> dict:
        task = self.ledger.task(task_id)
        return clean(
            {
                "task_id": task_id,
                "state": task["state"],
                "generation": task["generation"],
                "repairs": task["repairs"],
                "request": task["data"]["redacted_request"],
                "result": task["result"],
                "invocations": [
                    {"id": r["id"], "status": r["status"], "generation": r["generation"]}
                    for r in self.ledger.invocations(task_id)
                ],
                "steps": self.ledger.steps(task_id),
            }
        )
