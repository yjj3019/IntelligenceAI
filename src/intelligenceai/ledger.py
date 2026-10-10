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

    def state(self, task_id: str, state: str):
        current = self.task(task_id)["state"]
        if (
            current in {State.CANCELLED, State.NEEDS_RECONCILIATION, State.BLOCKED, State.FAILED}
            and current != state
        ):
            raise SafetyError("terminal or uncertain task transition refused")
        self.db.execute("UPDATE tasks SET state=? WHERE id=?", (state, task_id))
        self.event(task_id, {"state": state})

    def set_result(self, task_id: str, value: dict):
        self.db.execute("UPDATE tasks SET result=? WHERE id=?", (canonical(clean(value)), task_id))

    def reserve(self, task_id: str, step: Step, attempt: int, workspace: str) -> dict:
        authorize_step(step)
        key = digest([task_id, step.step_id, attempt])
        with self.transaction():
            task = self.task(task_id)
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

    def repair(self, task_id: str, signature: str):
        with self.transaction():
            task = self.task(task_id)
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
                self.state(task_id, State.REPAIRING)
            else:
                self.state(task_id, State.BLOCKED)
            return allowed

    def invocations(self, task_id: str) -> list[dict]:
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT id,status,generation,data,receipt FROM invocations WHERE task_id=?",
                (task_id,),
            )
        ]
