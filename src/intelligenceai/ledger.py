import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .contracts import Invocation, State, Step, Task
from .registry import authorize_step
from .security import SafetyError, canonical, clean, digest


class Ledger:
    """Authoritative effects ledger. Graph checkpoint state cannot launch a worker."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, state TEXT NOT NULL, generation INTEGER NOT NULL,
                data TEXT NOT NULL, result TEXT, repairs INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS invocations (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL, status TEXT NOT NULL,
                generation INTEGER NOT NULL, mode TEXT NOT NULL, data TEXT NOT NULL,
                receipt TEXT, UNIQUE(task_id, id));
            CREATE TABLE IF NOT EXISTS writers (
                workspace TEXT PRIMARY KEY, invocation_id TEXT UNIQUE NOT NULL);
            CREATE TABLE IF NOT EXISTS approvals (
                task_id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                timestamp REAL NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS failures (
                task_id TEXT NOT NULL, signature TEXT NOT NULL, count INTEGER NOT NULL,
                PRIMARY KEY(task_id, signature));
            CREATE TABLE IF NOT EXISTS repair_decisions (
                task_id TEXT NOT NULL, operation_id TEXT NOT NULL,
                signature TEXT NOT NULL, generation INTEGER NOT NULL, allowed INTEGER NOT NULL,
                PRIMARY KEY(task_id, operation_id));
            CREATE TABLE IF NOT EXISTS step_runs (
                task_id TEXT NOT NULL, step_id TEXT NOT NULL, round INTEGER NOT NULL,
                generation INTEGER NOT NULL, status TEXT NOT NULL, result TEXT,
                PRIMARY KEY(task_id, step_id, round));
        """)

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def event(self, task_id: str, event: dict):
        self.db.execute(
            "INSERT INTO events(task_id,timestamp,data) VALUES(?,?,?)",
            (task_id, time.time(), canonical(clean(event))),
        )

    def create(self, task: Task):
        self.db.execute(
            "INSERT INTO tasks(id,state,generation,data) VALUES(?,?,?,?)",
            (task.task_id, task.state, task.generation, canonical(clean(task.model_dump()))),
        )
        self.event(task.task_id, {"state": task.state})

    def task(self, task_id: str) -> dict:
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise SafetyError("unknown task")
        value = dict(row)
        value["data"] = json.loads(value["data"])
        value["result"] = json.loads(value["result"]) if value["result"] else None
        return value

    def _state_locked(self, task_id: str, state: str, expected_generation: int):
        task = self.task(task_id)
        current = task["state"]
        if task["generation"] != expected_generation:
            raise SafetyError("stale generation state transition refused")
        if (
            current in {State.CANCELLED, State.NEEDS_RECONCILIATION, State.BLOCKED, State.FAILED}
            and current != state
        ):
            raise SafetyError("terminal or uncertain task transition refused")
        self.db.execute("UPDATE tasks SET state=? WHERE id=?", (state, task_id))
        self.event(task_id, {"state": state})

    def state(self, task_id: str, state: str, *, expected_generation: int):
        with self.transaction():
            self._state_locked(task_id, state, expected_generation)

    def set_result(self, task_id: str, value: dict, *, expected_generation: int | None = None):
        with self.transaction():
            task = self.task(task_id)
            if expected_generation is not None and task["generation"] != expected_generation:
                raise SafetyError("stale generation verification refused")
            if task["state"] in {State.CANCELLED, State.NEEDS_RECONCILIATION}:
                raise SafetyError("verification refused for cancelled or uncertain task")
            self.db.execute(
                "UPDATE tasks SET result=? WHERE id=?", (canonical(clean(value)), task_id)
            )

    def reserve(
        self,
        task_id: str,
        step: Step,
        attempt: int,
        workspace: str,
        *,
        expected_generation: int | None = None,
    ) -> dict:
        authorize_step(step)
        key = digest([task_id, step.step_id, attempt])
        with self.transaction():
            task = self.task(task_id)
            if expected_generation is not None and task["generation"] != expected_generation:
                raise SafetyError("stale generation reservation refused")
            if step.executor != "fixture":
                raise SafetyError("only verified fixture executor can reserve effects")
            old = self.db.execute("SELECT * FROM invocations WHERE id=?", (key,)).fetchone()
            if old:
                return dict(old)
            if task["state"] in {
                State.CANCELLED,
                State.NEEDS_RECONCILIATION,
                State.FAILED,
                State.BLOCKED,
            }:
                raise SafetyError("task cannot launch while terminal or uncertain")
            count = self.db.execute(
                "SELECT count(*) FROM invocations WHERE task_id=?", (task_id,)
            ).fetchone()[0]
            active = self.db.execute(
                "SELECT count(*) FROM invocations WHERE status IN ('STARTING','RUNNING')"
            ).fetchone()[0]
            if count >= task["data"]["budgets"]["max_model_calls"] or active >= 3:
                raise SafetyError("model call budget exhausted")
            invocation = Invocation(
                invocation_id=key,
                task_id=task_id,
                step_id=step.step_id,
                attempt=attempt,
                owner_generation=task["generation"],
                executor=step.executor,
                provider=step.provider,
                model=step.model,
                effort=step.effort,
                mode=step.mode,
            )
            if step.mode == "write":
                try:
                    self.db.execute("INSERT INTO writers VALUES(?,?)", (workspace, key))
                except sqlite3.IntegrityError as exc:
                    raise SafetyError("workspace writer still owned") from exc
            self.db.execute(
                "INSERT INTO invocations VALUES(?,?,?,?,?,?,NULL)",
                (
                    key,
                    task_id,
                    "RESERVED",
                    task["generation"],
                    step.mode,
                    canonical(invocation.model_dump()),
                ),
            )
            self.event(task_id, {"invocation": key, "status": "RESERVED"})
        return dict(self.db.execute("SELECT * FROM invocations WHERE id=?", (key,)).fetchone())

    def start(self, invocation_id: str) -> bool:
        with self.transaction():
            row = self.db.execute(
                "SELECT * FROM invocations WHERE id=?", (invocation_id,)
            ).fetchone()
            task = self.task(row["task_id"])
            if task["generation"] != row["generation"] or task["state"] in {
                State.CANCELLED,
                State.NEEDS_RECONCILIATION,
                State.BLOCKED,
                State.FAILED,
            }:
                raise SafetyError("stale or blocked launch")
            active = self.db.execute(
                "SELECT count(*) FROM invocations WHERE status IN ('STARTING','RUNNING')"
            ).fetchone()[0]
            if row["status"] == "RESERVED" and active >= 3:
                raise SafetyError("concurrent model call limit exhausted")
            changed = self.db.execute(
                "UPDATE invocations SET status='STARTING' WHERE id=? AND status='RESERVED'",
                (invocation_id,),
            ).rowcount
            return bool(changed)

    def receive(self, invocation_id: str, generation: int, receipt: dict) -> bool:
        with self.transaction():
            row = self.db.execute(
                "SELECT * FROM invocations WHERE id=?", (invocation_id,)
            ).fetchone()
            if row is None:
                raise SafetyError("unknown invocation")
            task = self.task(row["task_id"])
            if generation != row["generation"] or generation != task["generation"]:
                raise SafetyError("stale generation result refused")
            encoded = canonical(clean(receipt))
            if row["status"] == "SUCCEEDED":
                if row["receipt"] != encoded:
                    raise SafetyError("conflicting duplicate receipt")
                return False
            if row["status"] != "STARTING":
                raise SafetyError("receipt does not match a start intent")
            self.db.execute(
                "UPDATE invocations SET status='SUCCEEDED',receipt=? WHERE id=?",
                (encoded, invocation_id),
            )
            self.db.execute("DELETE FROM writers WHERE invocation_id=?", (invocation_id,))
            self.event(row["task_id"], {"invocation": invocation_id, "status": "SUCCEEDED"})
            return True

    def reconcile(self, task_id: str) -> bool:
        with self.transaction():
            uncertain = self.db.execute(
                "SELECT count(*) FROM invocations WHERE task_id=? AND "
                "status IN ('STARTING','RUNNING')",
                (task_id,),
            ).fetchone()[0]
            if uncertain:
                # Keep writer ownership. Unknown termination cannot unlock a workspace.
                self.db.execute(
                    "UPDATE tasks SET generation=generation+1,state=? WHERE id=?",
                    (State.NEEDS_RECONCILIATION, task_id),
                )
                self.event(task_id, {"state": State.NEEDS_RECONCILIATION})
                return False
            return self.task(task_id)["state"] not in {
                State.NEEDS_RECONCILIATION,
                State.CANCELLED,
                State.BLOCKED,
                State.FAILED,
            }

    def cancel(self, task_id: str):
        with self.transaction():
            if self.task(task_id)["state"] in {State.CANCELLED, State.NEEDS_RECONCILIATION}:
                self.db.execute("DELETE FROM approvals WHERE task_id=?", (task_id,))
                return
            unknown = self.db.execute(
                "SELECT count(*) FROM invocations WHERE task_id=? AND "
                "status IN ('STARTING','RUNNING')",
                (task_id,),
            ).fetchone()[0]
            target = State.NEEDS_RECONCILIATION if unknown else State.CANCELLED
            self.db.execute(
                "UPDATE tasks SET generation=generation+1,state=? WHERE id=?", (target, task_id)
            )
            self.db.execute("DELETE FROM approvals WHERE task_id=?", (task_id,))
            if not unknown:
                self.db.execute(
                    "DELETE FROM writers WHERE invocation_id IN "
                    "(SELECT id FROM invocations WHERE task_id=?)",
                    (task_id,),
                )
                self.db.execute(
                    "UPDATE invocations SET status='CANCELLED' WHERE task_id=? "
                    "AND status='RESERVED'",
                    (task_id,),
                )
            self.event(task_id, {"state": target, "termination_verified": not bool(unknown)})

    def repair(self, task_id: str, signature: str, *, operation_id: str, expected_generation: int):
        with self.transaction():
            task = self.task(task_id)
            if task["generation"] != expected_generation:
                raise SafetyError("stale generation repair refused")
            decision = self.db.execute(
                "SELECT * FROM repair_decisions WHERE task_id=? AND operation_id=?",
                (task_id, operation_id),
            ).fetchone()
            if decision:
                if (
                    decision["signature"] != signature
                    or decision["generation"] != expected_generation
                ):
                    raise SafetyError("repair operation identity conflicts with previous decision")
                return bool(decision["allowed"])
            if task["state"] in {
                State.CANCELLED,
                State.NEEDS_RECONCILIATION,
                State.BLOCKED,
                State.FAILED,
            }:
                raise SafetyError("repair refused for terminal or uncertain task")
            row = self.db.execute(
                "SELECT count FROM failures WHERE task_id=? AND signature=?", (task_id, signature)
            ).fetchone()
            count = (row[0] if row else 0) + 1
            self.db.execute(
                "INSERT OR REPLACE INTO failures VALUES(?,?,?)", (task_id, signature, count)
            )
            allowed = (
                task["repairs"] < task["data"]["budgets"]["max_repairs"]
                and count < task["data"]["budgets"]["same_failure_limit"]
            )
            if allowed:
                self.db.execute("UPDATE tasks SET repairs=repairs+1 WHERE id=?", (task_id,))
                self.db.execute("DELETE FROM approvals WHERE task_id=?", (task_id,))
                self._state_locked(task_id, State.REPAIRING, expected_generation)
            else:
                self._state_locked(task_id, State.BLOCKED, expected_generation)
            self.db.execute(
                "INSERT INTO repair_decisions VALUES(?,?,?,?,?)",
                (task_id, operation_id, signature, expected_generation, int(allowed)),
            )
            return allowed

    @contextmanager
    def write_guard(self, invocation_id: str, generation: int, workspace: str):
        # Hold the ledger transaction through the trusted fixture write. Cancel cannot
        # commit between the authority check and that write. This is not OS containment.
        with self.transaction():
            row = self.db.execute(
                "SELECT * FROM invocations WHERE id=?", (invocation_id,)
            ).fetchone()
            lease = self.db.execute(
                "SELECT invocation_id FROM writers WHERE workspace=?", (workspace,)
            ).fetchone()
            if (
                row is None
                or row["mode"] != "write"
                or row["status"] != "STARTING"
                or row["generation"] != generation
                or lease is None
                or lease[0] != invocation_id
            ):
                raise SafetyError("active matching writer lease required at write boundary")
            task = self.task(row["task_id"])
            if task["generation"] != generation or task["state"] != State.RUNNING:
                raise SafetyError("stale or cancelled fixture write refused")
            yield

    def invalidate_candidate(self, task_id: str):
        with self.transaction():
            row = self.db.execute(
                "SELECT state,generation FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
            self.db.execute("DELETE FROM approvals WHERE task_id=?", (task_id,))
            if row and row["state"] not in {
                State.CANCELLED,
                State.NEEDS_RECONCILIATION,
                State.BLOCKED,
                State.FAILED,
            }:
                self._state_locked(task_id, State.BLOCKED, row["generation"])
            self.event(
                task_id, {"candidate_validation": "failed; approval permanently invalidated"}
            )

    def invocations(self, task_id: str) -> list[dict]:
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT id,status,generation,data,receipt FROM invocations WHERE task_id=?",
                (task_id,),
            )
        ]

    def step_start(self, task_id: str, step_id: str, round_number: int, generation: int):
        with self.transaction():
            task = self.task(task_id)
            if task["generation"] != generation or task["state"] != State.RUNNING:
                raise SafetyError("stale or inactive DAG step")
            self.db.execute(
                "INSERT OR IGNORE INTO step_runs VALUES(?,?,?,?,?,NULL)",
                (task_id, step_id, round_number, generation, "STARTING"),
            )

    def step_finish(self, task_id: str, result):
        from .contracts import StepResult

        result = StepResult.model_validate(result.model_dump())
        with self.transaction():
            task = self.task(task_id)
            if task["generation"] != result.generation or task["state"] != State.RUNNING:
                raise SafetyError("stale or cancelled DAG step result")
            old = self.db.execute(
                "SELECT result FROM step_runs WHERE task_id=? AND step_id=? AND round=?",
                (task_id, result.step_id, result.round_number),
            ).fetchone()
            encoded = canonical(clean(result.model_dump()))
            if old and old[0] and old[0] != encoded:
                raise SafetyError("conflicting immutable DAG step receipt")
            self.db.execute(
                "INSERT OR REPLACE INTO step_runs VALUES(?,?,?,?,?,?)",
                (
                    task_id,
                    result.step_id,
                    result.round_number,
                    result.generation,
                    result.status,
                    encoded,
                ),
            )

    def steps(self, task_id: str, round_number: int | None = None) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM step_runs WHERE task_id=? ORDER BY round,step_id", (task_id,)
        )
        return [
            dict(r) | {"result": json.loads(r["result"]) if r["result"] else None}
            for r in rows
            if round_number is None or r["round"] == round_number
        ]
