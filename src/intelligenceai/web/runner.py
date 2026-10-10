"""Durable supervisor for fixed offline fixtures. Live providers/effects stay disabled."""

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import stat
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import and_, insert, or_, select, update

from intelligenceai import checkers
from intelligenceai.security import canonical, clean, digest, require_no_secrets
from intelligenceai.web.core_bridge import fixed_plan
from intelligenceai.web.service import Problem, Service
from intelligenceai.web.store import (
    artifacts,
    attempts,
    engine,
    execution_grants,
    jobs,
    now,
    projects,
    tasks,
    uid,
)


@dataclass(frozen=True)
class Claim:
    project_id: str
    task_id: str
    generation: int
    token: str
    core_task_id: str


def child_environment(root):
    """Allowlist platform necessities; never inherit database/model/OIDC credentials."""
    env = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC")
        if key in os.environ
    }
    private = root / "environment"
    private.mkdir(exist_ok=True)
    env.update(
        HOME=str(private),
        USERPROFILE=str(private),
        TMP=str(private),
        TEMP=str(private),
        TMPDIR=str(private),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        LANGCHAIN_TRACING_V2="false",
        LANGSMITH_TRACING="false",
        PYTHONUTF8="1",
    )
    return env


class Runner:
    def __init__(self, db, root: Path, *, lease_seconds=120, crash_at=None):
        self.db, self.root = db, root.resolve()
        if os.name == "nt" and len(str(self.root)) > 120:
            raise ValueError("Use a shorter dedicated runner state path on Windows")
        self.root.mkdir(parents=True, exist_ok=True)
        self.service = Service(db)
        self.lease_seconds, self.crash_at = lease_seconds, crash_at

    def crash(self, boundary):
        if self.crash_at == boundary:
            raise RuntimeError("injected supervisor crash: " + boundary)

    def locked(self, conn, claim, *, require_current_role=True):
        # Every worker and web mutation takes project -> task -> job, in that order.
        project = (
            conn.execute(
                select(projects).where(projects.c.id == claim.project_id).with_for_update()
            )
            .mappings()
            .one()
        )
        task = (
            conn.execute(
                select(tasks)
                .where(tasks.c.project_id == claim.project_id, tasks.c.id == claim.task_id)
                .with_for_update()
            )
            .mappings()
            .one()
        )
        job = (
            conn.execute(select(jobs).where(jobs.c.task_id == claim.task_id).with_for_update())
            .mappings()
            .one()
        )
        mapping = (
            conn.execute(
                select(attempts).where(
                    attempts.c.core_task_id == claim.core_task_id,
                    attempts.c.task_id == claim.task_id,
                    attempts.c.project_id == claim.project_id,
                    attempts.c.generation == claim.generation,
                )
            )
            .mappings()
            .one()
        )
        if (
            task["generation"] != claim.generation
            or job["generation"] != claim.generation
            or job["lease_token"] != claim.token
            or (job["lease_expires_at"] or 0) <= now()
        ):
            raise Problem(409, "runner_fence_lost")
        if require_current_role:
            self.service.authorize(conn, task["actor_id"], claim.project_id, {"owner", "operator"})
            grant = (
                conn.execute(
                    select(execution_grants).where(
                        execution_grants.c.project_id == claim.project_id
                    )
                )
                .mappings()
                .first()
            )
            if (
                not grant
                or grant["mode"] != "fixed-fixture"
                or grant["expires_at"] <= now()
                or (
                    grant["policy_digest"] != project["policy_digest"]
                    or mapping["policy_digest"] != project["policy_digest"]
                    or mapping["plan_digest"] != digest(task["plan"])
                )
            ):
                raise Problem(409, "fixture_execution_grant_required")
        return task, job, mapping

    def queued_candidates(self):
        cursor = None
        while True:
            query = (
                select(tasks.c.project_id, tasks.c.id, tasks.c.created_at)
                .join(jobs, jobs.c.task_id == tasks.c.id)
                .where(jobs.c.state == "QUEUED")
            )
            if cursor:
                query = query.where(
                    or_(
                        tasks.c.created_at > cursor[0],
                        and_(tasks.c.created_at == cursor[0], tasks.c.id > cursor[1]),
                    )
                )
            with self.db.connect() as conn:
                rows = list(conn.execute(query.order_by(tasks.c.created_at, tasks.c.id).limit(100)))
            if not rows:
                return
            yield from rows
            cursor = (rows[-1].created_at, rows[-1].id)

    def claim(self):
        for project_id, task_id, _ in self.queued_candidates():
            with self.db.begin() as conn:
                project = (
                    conn.execute(
                        select(projects)
                        .where(projects.c.id == project_id)
                        .with_for_update(skip_locked=True)
                    )
                    .mappings()
                    .first()
                )
                if not project:
                    continue
                task = (
                    conn.execute(select(tasks).where(tasks.c.id == task_id).with_for_update())
                    .mappings()
                    .one()
                )
                job = (
                    conn.execute(select(jobs).where(jobs.c.task_id == task_id).with_for_update())
                    .mappings()
                    .one()
                )
                if job["state"] != "QUEUED" or job["cancel_requested"]:
                    continue
                try:
                    self.service.authorize(
                        conn, task["actor_id"], project_id, {"owner", "operator"}
                    )
                except Problem:
                    conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(state="HELD"))
                    conn.execute(update(tasks).where(tasks.c.id == task_id).values(state="BLOCKED"))
                    continue
                grant = (
                    conn.execute(
                        select(execution_grants).where(execution_grants.c.project_id == project_id)
                    )
                    .mappings()
                    .first()
                )
                if (
                    not grant
                    or grant["mode"] != "fixed-fixture"
                    or grant["expires_at"] <= now()
                    or (grant["policy_digest"] != project["policy_digest"])
                ):
                    conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(state="HELD"))
                    conn.execute(update(tasks).where(tasks.c.id == task_id).values(state="BLOCKED"))
                    self.service.record(
                        conn,
                        project_id,
                        task["actor_id"],
                        "fixture.admission_blocked",
                        {"reason": "execution_capability_invalid"},
                        task_id,
                    )
                    continue
                token, core_id = secrets.token_hex(32), uid()
                conn.execute(
                    insert(attempts).values(
                        core_task_id=core_id,
                        project_id=project_id,
                        task_id=task_id,
                        generation=task["generation"],
                        phase="CLAIMED",
                        profile=task["plan"]["profile"],
                        policy_digest=project["policy_digest"],
                        plan_digest=digest(task["plan"]),
                    )
                )
                conn.execute(
                    update(jobs)
                    .where(jobs.c.id == job["id"])
                    .values(
                        state="CLAIMED",
                        lease_token=token,
                        lease_expires_at=now() + self.lease_seconds,
                    )
                )
                conn.execute(update(tasks).where(tasks.c.id == task_id).values(state="QUEUED"))
                return Claim(project_id, task_id, task["generation"], token, core_id)
        return None

    def heartbeat(self, claim):
        with self.db.begin() as conn:
            _, job, _ = self.locked(conn, claim, require_current_role=False)
            conn.execute(
                update(jobs)
                .where(jobs.c.id == job["id"])
                .values(lease_expires_at=now() + self.lease_seconds)
            )

    def descriptor(self, claim, *, current_role=True):
        with self.db.begin() as conn:
            task, _, mapping = self.locked(conn, claim, require_current_role=current_role)
            return {
                "project_id": claim.project_id,
                "task_id": claim.task_id,
                "generation": claim.generation,
                "core_task_id": claim.core_task_id,
                "profile": mapping["profile"],
                "request": task["request"],
                "policy_digest": mapping["policy_digest"],
                "plan_digest": mapping["plan_digest"],
            }

    def child(self, phase, claim, descriptor):
        stop = threading.Event()
        proc = None

        def pulse():
            while not stop.wait(max(1, self.lease_seconds // 3)):
                try:
                    self.heartbeat(claim)
                except Exception:
                    return

        thread = threading.Thread(target=pulse, daemon=True)
        try:
            # Process creation is serialized with cancellation and membership revocation.
            # The durable STARTING intent remains authoritative if this transaction fails.
            with self.db.begin() as conn:
                _, job, mapping = self.locked(conn, claim)
                expected = "CLAIMED" if phase == "prepare" else "STARTING"
                if phase not in {"prepare", "execute"} or mapping["phase"] != expected:
                    raise Problem(409, "start_intent_uncertain")
                if job["cancel_requested"]:
                    raise Problem(409, "cancellation_pending")
                proc = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "intelligenceai.web.core_bridge",
                        phase,
                        str(self.root),
                        claim.core_task_id,
                    ],
                    stdin=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    env=child_environment(self.root),
                    cwd=self.root,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if phase == "execute":
                    conn.execute(
                        update(attempts)
                        .where(attempts.c.core_task_id == claim.core_task_id)
                        .values(phase="EXECUTING")
                    )
            thread.start()
            proc.communicate(canonical(descriptor), timeout=90)
            if proc.returncode:
                raise Problem(409, "core_receipt_unavailable")
        finally:
            stop.set()
            if thread.ident is not None:
                thread.join(timeout=2)
            if proc is not None and proc.poll() is None:
                proc.kill()  # Only the directly created owned child; no unrelated processes.
                proc.communicate(timeout=5)

    def phase(self, claim, phase):
        with self.db.begin() as conn:
            task, job, mapping = self.locked(conn, claim)
            expected = "CLAIMED" if phase == "RESERVED" else "RESERVED"
            if mapping["phase"] != expected:
                raise Problem(409, "start_intent_uncertain")
            if job["cancel_requested"]:
                # No invocation started at these boundaries; the prepare child has exited.
                conn.execute(
                    update(tasks).where(tasks.c.id == claim.task_id).values(state="CANCELLED")
                )
                conn.execute(
                    update(jobs)
                    .where(jobs.c.id == job["id"])
                    .values(state="CANCELLED", lease_token=None, lease_expires_at=None)
                )
                conn.execute(
                    update(attempts)
                    .where(attempts.c.core_task_id == claim.core_task_id)
                    .values(
                        phase="TERMINATED", receipt={"kind": "never_started", "never_started": True}
                    )
                )
                return False
            conn.execute(
                update(attempts)
                .where(attempts.c.core_task_id == claim.core_task_id)
                .values(phase=phase)
            )
            if phase == "STARTING":
                conn.execute(update(tasks).where(tasks.c.id == task["id"]).values(state="RUNNING"))
                conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(state="STARTING"))
            return True

    def verified_receipt(self, claim, descriptor):
        path = self.root / claim.core_task_id / "completed.json"
        if path.is_symlink() or path.stat().st_size > 1024 * 1024:
            raise Problem(409, "core_receipt_unavailable")
        report = json.loads(path.read_text(encoding="utf-8"))
        if report["mapping"] != descriptor or report["result"]["task_id"] != claim.core_task_id:
            raise Problem(409, "core_mapping_changed")
        plan = fixed_plan(descriptor["profile"])
        writer = plan.steps[1]
        expected = {
            writer.allowed_paths[0]: "ANSWER = 42\n"
            if descriptor["profile"] == "python-review"
            else '{"enabled":true,"version":42}\n'
        }
        if report["contents"] != expected:
            raise Problem(409, "candidate_bytes_changed")
        candidate = report["candidate"]
        workspace = self.root / claim.core_task_id / "core" / "workspaces" / claim.core_task_id
        payloads = {}
        for name in expected:
            target = workspace / name
            if any(
                p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
                for p in [target, *target.parents]
                if p.is_relative_to(self.root)
            ):
                raise Problem(409, "candidate_bytes_changed")
            info = target.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 4096:
                raise Problem(409, "candidate_bytes_changed")
            payloads[name] = target.read_bytes()
            if payloads[name] != expected[name].encode("utf-8"):
                raise Problem(409, "candidate_bytes_changed")
        # Read authoritative core accounting without running a controller or invoking Git.
        ledger_path = self.root / claim.core_task_id / "core" / "ledger.sqlite"
        with sqlite3.connect(ledger_path.as_uri() + "?mode=ro", uri=True) as core:
            core.row_factory = sqlite3.Row
            task = core.execute("SELECT * FROM tasks WHERE id=?", (claim.core_task_id,)).fetchone()
            invocations = list(
                core.execute("SELECT * FROM invocations WHERE task_id=?", (claim.core_task_id,))
            )
            data = json.loads(task["data"])
            if (
                data["plan"] != plan.model_dump()
                or len(invocations) != 1
                or invocations[0]["status"] != "SUCCEEDED"
                or not invocations[0]["receipt"]
                or task["generation"] != 1
                or task["state"] != "UNVERIFIED"
            ):
                raise Problem(409, "core_receipt_unavailable")
            if json.loads(task["result"])["candidate"] != candidate:
                raise Problem(409, "candidate_bytes_changed")
        baseline = workspace / "baseline.json"
        if baseline.read_bytes() != b'{"fixture":true}\n':
            raise Problem(409, "candidate_bytes_changed")
        current = {
            name: (hashlib.sha256(value).hexdigest(), (workspace / name).stat().st_mode & 0o111)
            for name, value in {**payloads, "baseline.json": baseline.read_bytes()}.items()
        }
        tree = digest(current)
        expected_id = digest(
            {
                "base": data["base_sha"],
                "head": data["base_sha"],
                "tree": tree,
                "changed": sorted(expected),
            }
        )
        if candidate["candidate_id"] != expected_id or candidate["tree_digest"] != tree:
            raise Problem(409, "candidate_bytes_changed")
        for name, value in payloads.items():
            if candidate["artifact_digests"].get(name) != hashlib.sha256(value).hexdigest():
                raise Problem(409, "candidate_bytes_changed")
            require_no_secrets(value.decode("utf-8"))
        evidence = [
            checkers.inspect(c, payloads, candidate["candidate_id"])[0].model_dump()
            for c in plan.steps[2].checks
        ]
        if any(e["status"] != "PASS" for e in evidence):
            raise Problem(409, "candidate_bytes_changed")
        return clean(
            {
                "kind": "completed",
                "candidate": candidate,
                "contents": expected,
                "evidence": evidence,
                "steps": report["result"]["steps"],
                "invocations": report["result"]["invocations"],
                "core_state": report["result"]["state"],
                "scope": "FIXTURE_STATIC_ONLY",
                "live_model": "NOTRUN",
                "os_sandbox": "UNVERIFIED",
                "model_calls": 0,
            }
        )

    def finish(self, claim, descriptor):
        snapshot = self.verified_receipt(claim, descriptor)
        with self.db.begin() as conn:
            task, job, mapping = self.locked(conn, claim, require_current_role=False)
            if mapping["phase"] not in {"STARTING", "EXECUTING", "NEEDS_RECONCILIATION"}:
                raise Problem(409, "core_mapping_changed")
            try:
                self.locked(conn, claim)
                authorized = True
            except Problem:
                authorized = False
            state = (
                "CANCELLED"
                if job["cancel_requested"]
                else ("READY_FOR_APPROVAL" if authorized else "BLOCKED")
            )
            conn.execute(
                update(attempts)
                .where(attempts.c.core_task_id == claim.core_task_id)
                .values(phase="RECEIVED", receipt=snapshot)
            )
            conn.execute(
                update(jobs)
                .where(jobs.c.id == job["id"])
                .values(
                    state="CANCELLED" if job["cancel_requested"] else "FINISHED",
                    lease_token=None,
                    lease_expires_at=None,
                )
            )
            conn.execute(
                update(tasks)
                .where(tasks.c.id == task["id"])
                .values(
                    state=state,
                    candidate_digest=digest(snapshot["candidate"]),
                    evidence_digest=digest(snapshot["evidence"]),
                    evidence_verified=authorized and state == "READY_FOR_APPROVAL",
                )
            )
            for name, content in snapshot["contents"].items():
                conn.execute(
                    insert(artifacts).values(
                        id=uid(),
                        task_id=task["id"],
                        name=name,
                        kind="candidate",
                        content=clean(content),
                        digest=hashlib.sha256(content.encode()).hexdigest(),
                    )
                )
            self.service.record(
                conn,
                claim.project_id,
                task["actor_id"],
                "runner.receipt",
                {
                    "generation": claim.generation,
                    "core_task_id": claim.core_task_id,
                    "state": state,
                    "scope": "FIXTURE_STATIC_ONLY",
                },
                claim.task_id,
            )
        return state

    def uncertain(self, claim):
        with self.db.begin() as conn:
            try:
                task, _, _ = self.locked(conn, claim, require_current_role=False)
            except Problem:
                return
            conn.execute(
                update(tasks).where(tasks.c.id == task["id"]).values(state="NEEDS_RECONCILIATION")
            )
            conn.execute(
                update(attempts)
                .where(attempts.c.core_task_id == claim.core_task_id)
                .values(phase="NEEDS_RECONCILIATION")
            )

    def run_once(self):
        claim = self.claim()
        if claim is None:
            return None
        self.crash("claimed")
        return self.run_claim(claim)

    def run_claim(self, claim, *, prepared=False):
        descriptor = self.descriptor(claim)
        try:
            if not prepared:
                self.child("prepare", claim, descriptor)
                if not self.phase(claim, "RESERVED"):
                    return "CANCELLED"
            self.crash("reserved")
            if not self.phase(claim, "STARTING"):
                return "CANCELLED"
            self.crash("starting")
            self.child("execute", claim, descriptor)
            self.crash("receipt")
            return self.finish(claim, descriptor)
        except (Problem, OSError, ValueError, subprocess.TimeoutExpired):
            self.uncertain(claim)
            raise Problem(409, "core_receipt_unavailable") from None

    def reconcile(self, core_id):
        """Expired ownership may import a durable completion, never replay STARTING."""
        with self.db.connect() as conn:
            row = (
                conn.execute(select(attempts).where(attempts.c.core_task_id == core_id))
                .mappings()
                .one()
            )
        with self.db.begin() as conn:
            conn.execute(
                select(projects).where(projects.c.id == row["project_id"]).with_for_update()
            ).one()
            task = (
                conn.execute(select(tasks).where(tasks.c.id == row["task_id"]).with_for_update())
                .mappings()
                .one()
            )
            job = (
                conn.execute(select(jobs).where(jobs.c.task_id == task["id"]).with_for_update())
                .mappings()
                .one()
            )
            row = (
                conn.execute(select(attempts).where(attempts.c.core_task_id == core_id))
                .mappings()
                .one()
            )
            if task["generation"] != row["generation"] or job["generation"] != row["generation"]:
                raise Problem(409, "runner_fence_lost")
            if row["phase"] == "RECEIVED":
                return task["state"]
            if (job["lease_expires_at"] or 0) > now():
                raise Problem(409, "runner_still_owned")
            completed = (self.root / core_id / "completed.json").is_file()
            prepared = (
                row["phase"] == "RESERVED" and (self.root / core_id / "prepared.json").is_file()
            )
            if not completed and not prepared:
                conn.execute(
                    update(tasks)
                    .where(tasks.c.id == task["id"])
                    .values(state="NEEDS_RECONCILIATION")
                )
                conn.execute(
                    update(attempts)
                    .where(attempts.c.core_task_id == core_id)
                    .values(phase="NEEDS_RECONCILIATION")
                )
                return "NEEDS_RECONCILIATION"
            token = secrets.token_hex(32)
            conn.execute(
                update(jobs)
                .where(jobs.c.id == job["id"])
                .values(lease_token=token, lease_expires_at=now() + self.lease_seconds)
            )
            claim = Claim(row["project_id"], task["id"], task["generation"], token, core_id)
        if prepared:
            return self.run_claim(claim, prepared=True)
        return self.finish(claim, self.descriptor(claim, current_role=False))


def main():
    parser = argparse.ArgumentParser(description="Fixed-fixture supervisor; no live providers")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--reconcile")
    args = parser.parse_args()
    if not args.once and not args.reconcile:
        parser.error("choose --once or --reconcile CORE_UUID")
    try:
        db = engine(os.environ["IAI_RUNNER_DATABASE_URL"])
        runner = Runner(db, Path(os.environ["IAI_RUNNER_STATE_DIR"]))
        print(runner.reconcile(args.reconcile) if args.reconcile else runner.run_once())
    except Exception:
        raise SystemExit("Runner operation unavailable; inspect authorized private audit") from None


if __name__ == "__main__":
    main()
