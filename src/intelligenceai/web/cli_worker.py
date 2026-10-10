"""Separate local worker consumes durable consent once. No browser argv or credentials."""

import argparse
import hashlib
import time
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import insert, select, update

from intelligenceai.security import clean
from intelligenceai.web.cli_results import parse
from intelligenceai.web.cli_runtime import NativeRuntime
from intelligenceai.web.cli_service import LocalCLI
from intelligenceai.web.config import Settings
from intelligenceai.web.service import Problem
from intelligenceai.web.store import (
    artifacts,
    engine,
    jobs,
    now,
    projects,
    tasks,
    uid,
    users,
)
from intelligenceai.web.store import (
    local_cli_profiles as profiles,
)
from intelligenceai.web.store import (
    local_cli_requests as requests,
)


class Worker:
    def __init__(self, db, profile_id, runtime, root):
        self.db, self.cli = db, LocalCLI(db)
        self.profile_id, self.runtime = profile_id, runtime
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def locked(self, conn, identifier):
        existing = (
            conn.execute(select(requests).where(requests.c.id == identifier)).mappings().one()
        )
        self.cli.service.authorize(
            conn, existing["actor_id"], existing["project_id"], {"owner"}, lock=True
        )
        row = (
            conn.execute(select(requests).where(requests.c.id == identifier).with_for_update())
            .mappings()
            .one()
        )
        return row

    def verify(self, conn, row, lease=None):
        task, job, profile = self.cli.current(conn, row, {"LOCAL_CLI_QUEUED", "LOCAL_CLI_RUNNING"})
        if (
            profile["id"] != self.profile_id
            or profile["runtime_digest"] != self.runtime.runtime_digest
        ):
            raise Problem(409, "cli_runtime_changed")
        if profile["metadata"].get("scope") != self.runtime.scope:
            raise Problem(409, "cli_runtime_changed")
        if lease is not None and (
            row["lease_token"] != lease
            or job["lease_token"] != lease
            or job["lease_expires_at"] <= now()
        ):
            raise Problem(409, "cli_fence_lost")
        return task, job

    @contextmanager
    def launch_authority(self, row, lease):
        with self.db.begin() as conn:
            current = self.locked(conn, row["id"])
            self.verify(conn, current, lease)
            conn.execute(update(requests).where(requests.c.id == row["id"]).values(state="RUNNING"))

            def recheck():
                current = self.locked(conn, row["id"])
                self.verify(conn, current, lease)

            yield recheck

    def refresh_quota(self):
        # Read identity without locks; native status can take 15 seconds.
        with self.db.connect() as conn:
            identity = (
                conn.execute(select(profiles).where(profiles.c.id == self.profile_id))
                .mappings()
                .one()
            )
            self.cli.service.authorize(
                conn, identity["actor_id"], identity["project_id"], {"owner"}
            )
            if not identity["active"] or identity["runtime_digest"] != self.runtime.runtime_digest:
                raise Problem(409, "cli_runtime_changed")
        snapshot = self.runtime.quota(self.root)
        with self.db.begin() as conn:
            # All paths acquire project authority before the profile row.
            self.cli.service.authorize(
                conn, identity["actor_id"], identity["project_id"], {"owner"}, lock=True
            )
            row = (
                conn.execute(
                    select(profiles).where(profiles.c.id == self.profile_id).with_for_update()
                )
                .mappings()
                .one()
            )
            if (
                not row["active"]
                or any(
                    row[key] != identity[key]
                    for key in ("actor_id", "project_id", "provider", "runtime_digest")
                )
                or row["runtime_digest"] != self.runtime.runtime_digest
            ):
                raise Problem(409, "cli_runtime_changed")
            conn.execute(
                update(profiles)
                .where(profiles.c.id == self.profile_id)
                .values(metadata=clean(dict(row["metadata"]) | {"quota": snapshot}))
            )

    def once(self):
        # One DB slot per owner. A crashed consumed attempt blocks all automatic replay.
        with self.db.begin() as conn:
            profile = (
                conn.execute(select(profiles).where(profiles.c.id == self.profile_id))
                .mappings()
                .one()
            )
            conn.execute(
                select(users.c.id)
                .where(users.c.id == profile["actor_id"])
                .with_for_update(key_share=True)
            ).one()
            conn.execute(
                select(projects.c.id)
                .where(projects.c.id == profile["project_id"])
                .with_for_update()
            ).one()
            if conn.execute(
                select(requests.c.id).where(
                    requests.c.actor_id == profile["actor_id"],
                    requests.c.state.in_(["STARTING", "RUNNING", "UNKNOWN"]),
                )
            ).first():
                return False
            row = (
                conn.execute(
                    select(requests)
                    .where(
                        requests.c.profile_id == self.profile_id,
                        requests.c.state == "QUEUED",
                    )
                    .order_by(requests.c.created_at)
                    .limit(1)
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if not row:
                return False
            try:
                task, job = self.verify(conn, row)
            except Problem:
                # QUEUED has never released stdin. Do not strand later valid requests.
                result = {
                    "availability": "NEVER_STARTED",
                    "scope": self.runtime.scope,
                    "live_model": "NOTRUN",
                    "model_calls": 0,
                    "cli_invocations": 0,
                    "local_termination_confirmed": True,
                    "remote_cancellation": "NOT_STARTED",
                }
                conn.execute(
                    update(requests)
                    .where(requests.c.id == row["id"])
                    .values(state="NEVER_STARTED", result=result)
                )
                job = (
                    conn.execute(
                        select(jobs).where(jobs.c.task_id == row["task_id"]).with_for_update()
                    )
                    .mappings()
                    .one()
                )
                if job["generation"] == row["generation"] and job["lease_token"] is None:
                    conn.execute(
                        update(jobs).where(jobs.c.id == job["id"]).values(state="FINISHED")
                    )
                    conn.execute(
                        update(tasks).where(tasks.c.id == row["task_id"]).values(state="BLOCKED")
                    )
                self.cli.service.record(
                    conn,
                    row["project_id"],
                    row["actor_id"],
                    "cli.never_started",
                    {"request_id": row["id"], **result},
                    row["task_id"],
                )
                return True
            prompt, metrics = self.cli.prompt(conn, task)
            lease = uid()
            conn.execute(
                update(requests)
                .where(requests.c.id == row["id"])
                .values(state="STARTING", lease_token=lease)
            )
            conn.execute(
                update(jobs)
                .where(jobs.c.id == job["id"])
                .values(state="LOCAL_CLI_RUNNING", lease_token=lease, lease_expires_at=now() + 65)
            )
            conn.execute(
                update(tasks).where(tasks.c.id == task["id"]).values(state="LOCAL_CLI_RUNNING")
            )
            row = dict(row) | {"state": "STARTING", "lease_token": lease}
        workspace = self.root / row["id"]
        workspace.mkdir(exist_ok=False)
        process = None
        stopped, failure = False, None
        started = time.monotonic()

        def gate():
            return self.launch_authority(row, lease)

        try:
            process = self.runtime.start(workspace, prompt, gate)
            while process.process.poll() is None:
                if time.monotonic() - started >= 60:
                    failure = "TIMEOUT"
                    break
                if process.overflow.is_set():
                    failure = "OUTPUT_TRUNCATED"
                    break
                with self.db.begin() as conn:
                    self.verify(conn, self.locked(conn, row["id"]), lease)
                time.sleep(0.05)
        except Exception:
            failure = "AUTHORITY_OR_EXECUTION_CHANGED"
        finally:
            if process is not None:
                stopped = process.close()
        result = {
            "availability": failure or "EXECUTION_ERROR",
            "scope": self.runtime.scope,
            "local_termination_confirmed": stopped,
            "remote_cancellation": "UNKNOWN",
            "native_internal_requests": "UNKNOWN",
            "model_calls": None,
            "cli_invocations": None,
            "exit_code": process.process.returncode if process is not None and stopped else None,
            "payload": metrics,
            "live_model": "NOTRUN" if self.runtime.scope == "FAKE_CLI_TEST_ONLY" else "UNKNOWN",
        }
        if process is not None and stopped and not failure:
            stdout, stderr = process.output()
            result |= parse(
                self.runtime.provider,
                stdout,
                stderr,
                process.process.returncode,
                now(),
                truncated=process.overflow.is_set(),
            )
            if result["availability"] == "AVAILABLE":
                result["cli_invocations"] = 1
                result["live_model"] = (
                    "NOTRUN"
                    if self.runtime.scope == "FAKE_CLI_TEST_ONLY"
                    else "NATIVE_RESULT_RECEIVED"
                )
        text = result.pop("text", None)
        with self.db.begin() as conn:
            # Fence cleanup does not depend on continued membership; result import does.
            conn.execute(
                select(projects.c.id).where(projects.c.id == row["project_id"]).with_for_update()
            ).one()
            current = (
                conn.execute(select(requests).where(requests.c.id == row["id"]).with_for_update())
                .mappings()
                .one()
            )
            job = (
                conn.execute(select(jobs).where(jobs.c.task_id == row["task_id"]).with_for_update())
                .mappings()
                .one()
            )
            if current["lease_token"] != lease or job["lease_token"] != lease:
                return True
            valid = False
            try:
                self.verify(conn, current, lease)
                valid = True
            except Problem:
                result["availability"] = "AUTHORITY_CHANGED"
            complete = stopped and valid and result["availability"] == "AVAILABLE"
            state = "COMPLETED" if complete else "UNKNOWN"
            # Unknown includes remote status after timeout/revocation; no retry/recovery shortcut.
            conn.execute(
                update(requests)
                .where(requests.c.id == row["id"])
                .values(state=state, result=clean(result))
            )
            conn.execute(
                update(jobs)
                .where(jobs.c.id == job["id"])
                .values(
                    state="FINISHED" if complete else "LOCAL_CLI_UNRESOLVED",
                    lease_token=None if stopped else lease,
                )
            )
            conn.execute(
                update(tasks)
                .where(tasks.c.id == row["task_id"])
                .values(state="CLI_COMPLETED" if complete else "BLOCKED")
            )
            if complete:
                content = clean(text)
                conn.execute(
                    insert(artifacts).values(
                        id=uid(),
                        task_id=row["task_id"],
                        name="Private CLI review",
                        kind="cli-result",
                        content=content,
                        digest=hashlib.sha256(content.encode()).hexdigest(),
                    )
                )
            self.cli.service.record(
                conn,
                row["project_id"],
                row["actor_id"],
                "cli.finished",
                {"request_id": row["id"], **result},
                row["task_id"],
            )
        return True


def main():
    parser = argparse.ArgumentParser(
        description="Owner-bound local CLI worker; native credentials stay local"
    )
    parser.add_argument("command", choices=("register", "quota", "once", "serve"))
    parser.add_argument("--provider", choices=("claude", "codex", "grok"), required=True)
    parser.add_argument(
        "--executable",
        required=True,
        help="operator-local installed executable; never browser input",
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--root", required=True, help="dedicated local worker directory")
    parser.add_argument("--project")
    parser.add_argument("--actor")
    parser.add_argument("--profile")
    args = parser.parse_args()
    runtime = NativeRuntime(args.provider, args.executable, args.version)
    db = engine(Settings.from_env().database_url)
    worker = Worker(db, args.profile, runtime, args.root)
    try:
        if args.command == "register":
            with db.begin() as conn:
                worker.cli.service.authorize(conn, args.actor, args.project, {"owner"}, lock=True)
                identifier = uid()
                conn.execute(
                    insert(profiles).values(
                        id=identifier,
                        project_id=args.project,
                        actor_id=args.actor,
                        provider=args.provider,
                        runtime_digest=runtime.runtime_digest,
                        metadata=clean(runtime.probe(worker.root)),
                    )
                )
            print("Local CLI profile:", identifier, "execution restrictions unverified")
        elif args.command == "quota":
            worker.refresh_quota()
            print("Official usage snapshot refreshed; no model turn started")
        elif args.command == "serve":
            while True:
                worker.once()
                time.sleep(2)
        else:
            print("Request consumed" if worker.once() else "No authorized queued request")
    except KeyboardInterrupt:
        raise SystemExit(
            "Local worker stopped; unresolved requests require receipt review"
        ) from None
    except Exception:
        raise SystemExit(
            "Local CLI operation unavailable; review installation, authority and saved status"
        ) from None
    finally:
        db.dispose()


if __name__ == "__main__":
    main()
