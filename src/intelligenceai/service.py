"""Local service facade over the same Controller used by the CLI.

Repository grants, state root and transports are operator configuration, never tool inputs.
"""

import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import Field

from .contracts import Contract, Plan, State
from .controller import Controller, fixture_plan
from .ledger import Ledger
from .registry import registry
from .security import SafetyError, digest, redact


class NoArguments(Contract):
    pass


class PreviewArguments(Contract):
    plan: Plan | None = None


class SubmitArguments(Contract):
    repository: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    request: str = Field(min_length=1, max_length=16384)
    plan: Plan | None = None
    idempotency_key: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")


class TaskArguments(Contract):
    task_id: str = Field(pattern=r"^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$")


TOOLS = {
    "capabilities": NoArguments,
    "preview": PreviewArguments,
    "submit": SubmitArguments,
    "status": TaskArguments,
    "results": TaskArguments,
    "cancel": TaskArguments,
}


class ControllerService:
    def __init__(self, root: Path, repositories: dict[str, Path]):
        self.root = root.resolve()
        self.repositories = {}
        for name, path in repositories.items():
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name):
                raise SafetyError("invalid repository grant name")
            resolved = path.resolve(strict=True)
            if not resolved.is_dir() or self.root.is_relative_to(resolved):
                raise SafetyError("state must be outside operator-granted repositories")
            self.repositories[name] = resolved
        if not self.repositories:
            raise SafetyError("at least one operator repository grant required")
        self.allowed_identities = {digest(str(p)) for p in self.repositories.values()}
        self.lock = threading.Lock()
        self.active: set[str] = set()
        self.closed = False
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="iai-local")
        ledger = Ledger(self.root / "ledger.sqlite")
        try:
            ledger.db.execute(
                "CREATE TABLE IF NOT EXISTS service_requests "
                "(key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, "
                "task_id TEXT NOT NULL, state TEXT NOT NULL)"
            )
            # Do not re-dispatch old admissions or active invocations when a stdio host reconnects.
            for row in ledger.db.execute(
                "SELECT id FROM tasks WHERE "
                "state IN ('RUNNING','VERIFYING','REVIEWING','REPAIRING')"
            ).fetchall():
                ledger.reconcile(row[0])
        finally:
            ledger.close()

    def call(self, tool: str, arguments: dict) -> dict | list:
        model = TOOLS.get(tool)
        if model is None:
            raise SafetyError("unexposed tool; no approval or external action capability")
        args = model.model_validate(arguments)
        if tool == "capabilities":
            return {
                "executors": registry(),
                "repositories": sorted(self.repositories),
                "live_dispatch_enabled": False,
                "external_actions_enabled": False,
            }
        if tool == "preview":
            return {
                "plan": (args.plan or fixture_plan()).model_dump(),
                "executors": registry(),
                "live_dispatch_enabled": False,
                "note": "No account probe or worker launch",
            }
        if tool == "submit":
            return self._submit(args)
        controller = Controller(self.root)
        try:
            task = controller.ledger.task(args.task_id)
            if task["data"]["repo_identity"] not in self.allowed_identities:
                raise SafetyError("task outside operator repository grants")
            if tool == "cancel":
                controller.reject(args.task_id)
            return controller.status(args.task_id)
        finally:
            controller.close()

    def _submit(self, args: SubmitArguments):
        from .dag import validate_executable_plan

        repo = self.repositories.get(args.repository)
        if repo is None:
            raise SafetyError("repository grant missing")
        plan = Plan.model_validate((args.plan or fixture_plan()).model_dump())
        validate_executable_plan(plan)
        fingerprint = digest([str(repo), redact(args.request), plan.model_dump()])
        with self.lock:
            if self.closed:
                raise SafetyError("local service closing")
            ledger = Ledger(self.root / "ledger.sqlite")
            try:
                with ledger.transaction():
                    prior = ledger.db.execute(
                        "SELECT * FROM service_requests WHERE key=?", (args.idempotency_key,)
                    ).fetchone()
                    if prior:
                        if prior["fingerprint"] != fingerprint:
                            raise SafetyError("conflicting duplicate admission")
                        return {
                            "task_id": prior["task_id"],
                            "admission": prior["state"],
                            "duplicate": True,
                        }
                    if len(self.active) >= 2:
                        raise SafetyError("local task concurrency limit reached")
                    tid = str(uuid.uuid4())
                    ledger.db.execute(
                        "INSERT INTO service_requests VALUES(?,?,?,?)",
                        (args.idempotency_key, fingerprint, tid, "CLAIMED"),
                    )
                self.active.add(tid)
            finally:
                ledger.close()
        controller = Controller(self.root)
        try:
            controller.submit(repo, args.request, plan, _task_id=tid)
            with controller.ledger.transaction():
                controller.ledger.db.execute(
                    "UPDATE service_requests SET state='SUBMITTED' WHERE key=?",
                    (args.idempotency_key,),
                )
            with self.lock:
                if self.closed:
                    controller.reject(tid)
                    raise SafetyError("service closed before queue admission")
                self.pool.submit(self._run, tid)
            return {"task_id": tid, "admission": "SUBMITTED", "duplicate": False}
        except BaseException:
            # The durable claim remains. A duplicate can inspect it, but never replay it.
            with self.lock:
                self.active.discard(tid)
            try:
                row = controller.ledger.task(tid)
                controller.ledger.state(
                    tid, State.NEEDS_RECONCILIATION, expected_generation=row["generation"]
                )
            except SafetyError:
                pass
            raise
        finally:
            controller.close()

    def _run(self, tid):
        controller = Controller(self.root)
        try:
            controller.run(tid)
        except Exception:
            controller.ledger.invalidate_candidate(tid)
        finally:
            controller.close()
            with self.lock:
                self.active.discard(tid)

    def close(self):
        with self.lock:
            self.closed = True
            active = list(self.active)
        ledger = Ledger(self.root / "ledger.sqlite")
        try:
            for tid in active:
                if ledger.db.execute("SELECT 1 FROM tasks WHERE id=?", (tid,)).fetchone():
                    ledger.cancel(tid)
        finally:
            ledger.close()
        self.pool.shutdown(wait=True, cancel_futures=True)
