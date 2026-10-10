"""Durable approval-to-process fixture path; cannot dispatch a live provider."""

import argparse
import hashlib
import json
import os
import secrets
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import and_, insert, or_, select, update

from intelligenceai.security import SafetyError, canonical, clean, digest, require_no_secrets
from intelligenceai.web import fixture_vendor
from intelligenceai.web.core_bridge import atomic_json
from intelligenceai.web.runner import child_environment
from intelligenceai.web.service import Problem, Service
from intelligenceai.web.store import (
    artifacts,
    engine,
    jobs,
    now,
    projects,
    tasks,
    uid,
    vendor_invocations,
)


@dataclass(frozen=True)
class VendorClaim:
    invocation_id: str
    project_id: str
    task_id: str
    generation: int
    token: str


class ApprovedFixtureRunner:
    def __init__(self, db, root: Path, *, lease_seconds=120, crash_at=None):
        self.db, self.root = db, root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.service = Service(db)
        self.lease_seconds, self.crash_at = lease_seconds, crash_at
        self.vendor_source = Path(fixture_vendor.__file__).resolve()
        self.vendor_digest = self.file_digest(self.vendor_source)
        self.python_digest = self.file_digest(Path(sys.executable))

    @staticmethod
    def file_digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def crash(self, boundary):
        if self.crash_at == boundary:
            raise RuntimeError("injected fixture vendor crash: " + boundary)

    def locked(self, conn, claim, *, authority=True, fenced=True):
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
                .where(tasks.c.id == claim.task_id, tasks.c.project_id == claim.project_id)
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
        row = (
            conn.execute(
                select(vendor_invocations)
                .where(
                    vendor_invocations.c.id == claim.invocation_id,
                    vendor_invocations.c.task_id == claim.task_id,
                    vendor_invocations.c.project_id == claim.project_id,
                )
                .with_for_update()
            )
            .mappings()
            .one()
        )
        if (
            task["generation"] != claim.generation
            or job["generation"] != claim.generation
            or row["generation"] != claim.generation
            or fenced
            and (
                row["lease_token"] != claim.token
                or job["lease_token"] != claim.token
                or (row["lease_expires_at"] or 0) <= now()
                or (job["lease_expires_at"] or 0) <= now()
            )
        ):
            raise Problem(409, "vendor_fence_lost")
        if authority:
            approved, _, _ = self.service.approved_fixture_authority(
                conn, project, task, row["actor_id"], row["session_hash"]
            )
            if (
                approved["actor_id"] != row["approved_by"]
                or digest(approved["binding"]) != row["binding_digest"]
                or digest(row["binding"]) != row["binding_digest"]
                or row["deadline"] <= now()
                or job["cancel_requested"]
            ):
                raise Problem(409, "vendor_authority_changed")
        return project, task, job, row

    def candidates(self):
        cursor = None
        while True:
            query = select(vendor_invocations).where(vendor_invocations.c.state == "RESERVED")
            if cursor:
                query = query.where(
                    or_(
                        vendor_invocations.c.created_at > cursor[0],
                        and_(
                            vendor_invocations.c.created_at == cursor[0],
                            vendor_invocations.c.id > cursor[1],
                        ),
                    )
                )
            with self.db.connect() as conn:
                values = list(
                    conn.execute(
                        query.order_by(
                            vendor_invocations.c.created_at, vendor_invocations.c.id
                        ).limit(100)
                    ).mappings()
                )
            if not values:
                return
            yield from values
            cursor = (values[-1]["created_at"], values[-1]["id"])

    def claim(self):
        for item in self.candidates():
            claim = VendorClaim(
                item["id"],
                item["project_id"],
                item["task_id"],
                item["generation"],
                secrets.token_hex(32),
            )
            with self.db.begin() as conn:
                _, _, job, row = self.locked(conn, claim, authority=False, fenced=False)
                if row["state"] != "RESERVED" or job["state"] != "VENDOR_QUEUED":
                    continue
                try:
                    self.locked(conn, claim, fenced=False)
                except Problem:
                    result = {
                        "kind": "never_started",
                        "termination_confirmed": True,
                        "scope": "FAKE_VENDOR_TEST_ONLY",
                        "live_model": "NOTRUN",
                    }
                    conn.execute(
                        update(vendor_invocations)
                        .where(vendor_invocations.c.id == claim.invocation_id)
                        .values(state="TERMINATED", result=result)
                    )
                    conn.execute(
                        update(jobs).where(jobs.c.id == job["id"]).values(state="FINISHED")
                    )
                    conn.execute(
                        update(tasks).where(tasks.c.id == claim.task_id).values(state="BLOCKED")
                    )
                    continue
                expires = now() + self.lease_seconds
                conn.execute(
                    update(vendor_invocations)
                    .where(vendor_invocations.c.id == claim.invocation_id)
                    .values(state="CLAIMED", lease_token=claim.token, lease_expires_at=expires)
                )
                conn.execute(
                    update(jobs)
                    .where(jobs.c.id == job["id"])
                    .values(
                        state="VENDOR_CLAIMED",
                        lease_token=claim.token,
                        lease_expires_at=expires,
                    )
                )
                return claim
        return None

    def descriptor(self, conn, claim, row):
        contents = {
            item["name"]: item["content"]
            for item in conn.execute(
                select(artifacts).where(
                    artifacts.c.task_id == claim.task_id, artifacts.c.kind == "candidate"
                )
            ).mappings()
        }
        value = {
            "invocation_id": claim.invocation_id,
            "scope": "FAKE_VENDOR_TEST_ONLY",
            "binding_digest": row["binding_digest"],
            "contents": contents,
        }
        require_no_secrets(value)
        if len(canonical(value).encode()) > 8192:
            raise Problem(409, "fixture_input_limit")
        return value

    def uncertain(self, claim):
        with self.db.begin() as conn:
            try:
                _, _, _, row = self.locked(conn, claim, authority=False)
            except Problem:
                return
            if row["state"] in {"COMPLETED", "TERMINATED"}:
                return
            conn.execute(
                update(vendor_invocations)
                .where(vendor_invocations.c.id == claim.invocation_id)
                .values(state="NEEDS_RECONCILIATION")
            )
            conn.execute(
                update(tasks)
                .where(tasks.c.id == claim.task_id)
                .values(state="NEEDS_RECONCILIATION")
            )

    def read_owned_json(self, path):
        if any(
            p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
            for p in [path, *path.parents]
            if p.is_relative_to(self.root)
        ):
            raise Problem(409, "fixture_result_unavailable")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 8192:
            raise Problem(409, "fixture_result_unavailable")
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def expected_output(claim, descriptor):
        return {
            "invocation_id": claim.invocation_id,
            "input_digest": digest(descriptor),
            "status": "SYNTHETIC_OUTPUT",
            "scope": "FAKE_VENDOR_TEST_ONLY",
            "message": "Fixed synthetic vendor response",
            "value": 42,
            "model_calls": 0,
            "live_model": "NOTRUN",
            "os_sandbox": "UNVERIFIED",
        }

    def completion(self, claim, descriptor, returncode, reason):
        result = {
            "kind": "terminated",
            "scope": "FAKE_VENDOR_TEST_ONLY",
            "live_model": "NOTRUN",
            "os_sandbox": "UNVERIFIED",
            "model_calls": 0,
            "termination_confirmed": True,
            "returncode": returncode,
            "reason": reason,
            "invocation_id": claim.invocation_id,
            "binding_digest": descriptor["binding_digest"],
            "input_digest": digest(descriptor),
            "vendor_digest": self.vendor_digest,
            "python_digest": self.python_digest,
        }
        if returncode == 0:
            value = self.read_owned_json(self.root / claim.invocation_id / "vendor-result.json")
            expected = self.expected_output(claim, descriptor)
            if value != expected:
                raise Problem(409, "fixture_result_changed")
            result.update(kind="completed", output=value)
        require_no_secrets(result)
        result = clean(result)
        atomic_json(self.root / claim.invocation_id / "supervisor-completed.json", result)
        return result

    def finish(self, claim, result):
        with self.db.begin() as conn:
            _, task, job, row = self.locked(conn, claim, authority=False)
            if row["state"] not in {"STARTING", "EXECUTING", "NEEDS_RECONCILIATION"}:
                raise Problem(409, "vendor_start_intent_consumed")
            if (
                result.get("invocation_id") != claim.invocation_id
                or result.get("binding_digest") != row["binding_digest"]
                or result.get("scope") != "FAKE_VENDOR_TEST_ONLY"
                or result.get("termination_confirmed") is not True
                or result.get("vendor_digest") != self.vendor_digest
                or result.get("python_digest") != self.python_digest
            ):
                raise Problem(409, "fixture_result_changed")
            descriptor = self.descriptor(conn, claim, row)
            required = {
                "kind",
                "scope",
                "live_model",
                "os_sandbox",
                "model_calls",
                "termination_confirmed",
                "returncode",
                "reason",
                "invocation_id",
                "binding_digest",
                "input_digest",
                "vendor_digest",
                "python_digest",
            }
            if (
                set(result)
                != required | ({"output"} if result.get("kind") == "completed" else set())
                or result["kind"] not in {"completed", "terminated"}
                or type(result["returncode"]) is not int
                or result["live_model"] != "NOTRUN"
                or result["os_sandbox"] != "UNVERIFIED"
                or result["model_calls"] != 0
                or type(result["model_calls"]) is not int
                or result["input_digest"] != digest(descriptor)
                or result["reason"] not in {"EXITED", "AUTHORITY_OR_CANCEL_CHANGED", "DEADLINE"}
                or result["kind"] == "completed"
                and (
                    result["returncode"] != 0
                    or result["output"] != self.expected_output(claim, descriptor)
                    or self.read_owned_json(self.root / claim.invocation_id / "vendor-result.json")
                    != result["output"]
                )
                or result["kind"] == "terminated"
                and result["returncode"] == 0
            ):
                raise Problem(409, "fixture_result_changed")
            try:
                self.locked(conn, claim)
                authorized = True
            except Problem:
                authorized = False
            state = (
                "CANCELLED"
                if job["cancel_requested"]
                else (
                    "BLOCKED"
                    if not authorized
                    else "FIXTURE_COMPLETED"
                    if result["kind"] == "completed"
                    else "FAILED"
                )
            )
            conn.execute(
                update(vendor_invocations)
                .where(vendor_invocations.c.id == claim.invocation_id)
                .values(
                    state="COMPLETED" if result["kind"] == "completed" else "TERMINATED",
                    result=clean(result),
                    lease_token=None,
                    lease_expires_at=None,
                )
            )
            conn.execute(
                update(jobs)
                .where(jobs.c.id == job["id"])
                .values(
                    state="CANCELLED" if state == "CANCELLED" else "FINISHED",
                    lease_token=None,
                    lease_expires_at=None,
                )
            )
            conn.execute(update(tasks).where(tasks.c.id == task["id"]).values(state=state))
            if result["kind"] == "completed":
                content = canonical(clean(result["output"]))
                conn.execute(
                    insert(artifacts).values(
                        id=uid(),
                        task_id=task["id"],
                        name="synthetic-vendor-result.json",
                        kind="vendor-result",
                        content=content,
                        digest=hashlib.sha256(content.encode()).hexdigest(),
                    )
                )
            self.service.record(
                conn,
                claim.project_id,
                row["actor_id"],
                "fixture.vendor_finished",
                {
                    "invocation_id": claim.invocation_id,
                    "state": state,
                    "scope": "FAKE_VENDOR_TEST_ONLY",
                },
                claim.task_id,
            )
            return state

    def never_started(self, claim):
        """The current owning call observed no Popen; crash recovery cannot use this proof."""
        with self.db.begin() as conn:
            try:
                _, _, job, row = self.locked(conn, claim, authority=False)
            except Problem:
                return False
            if row["state"] not in {"CLAIMED", "STARTING"}:
                return False
            state = "CANCELLED" if job["cancel_requested"] else "BLOCKED"
            conn.execute(
                update(vendor_invocations)
                .where(vendor_invocations.c.id == claim.invocation_id)
                .values(
                    state="TERMINATED",
                    lease_token=None,
                    lease_expires_at=None,
                    result={
                        "kind": "never_started",
                        "termination_confirmed": True,
                        "scope": "FAKE_VENDOR_TEST_ONLY",
                        "live_model": "NOTRUN",
                    },
                )
            )
            conn.execute(
                update(jobs)
                .where(jobs.c.id == job["id"])
                .values(
                    state="CANCELLED" if state == "CANCELLED" else "FINISHED",
                    lease_token=None,
                    lease_expires_at=None,
                )
            )
            conn.execute(update(tasks).where(tasks.c.id == claim.task_id).values(state=state))
            self.service.record(
                conn,
                claim.project_id,
                row["actor_id"],
                "fixture.vendor_never_started",
                {
                    "invocation_id": claim.invocation_id,
                    "state": state,
                    "scope": "FAKE_VENDOR_TEST_ONLY",
                },
                claim.task_id,
            )
            return True

    def run_claim(self, claim):
        proc = None
        descriptor = None
        try:
            # Commit one-time consumption before launching. Retrying this method cannot replay it.
            with self.db.begin() as conn:
                _, _, job, row = self.locked(conn, claim)
                if row["state"] != "CLAIMED":
                    raise Problem(409, "vendor_start_intent_consumed")
                descriptor = self.descriptor(conn, claim, row)
                conn.execute(
                    update(vendor_invocations)
                    .where(vendor_invocations.c.id == claim.invocation_id)
                    .values(state="STARTING")
                )
                conn.execute(
                    update(jobs).where(jobs.c.id == job["id"]).values(state="VENDOR_STARTING")
                )
                conn.execute(
                    update(tasks).where(tasks.c.id == claim.task_id).values(state="VENDOR_RUNNING")
                )
            self.crash("starting")
            (self.root / claim.invocation_id).mkdir(exist_ok=True)
            if (
                self.file_digest(self.vendor_source) != self.vendor_digest
                or self.file_digest(Path(sys.executable)) != self.python_digest
            ):
                raise Problem(409, "fixture_executable_changed")
            # Hashing precedes the final current-authority/deadline check. Project and
            # session locks serialize process creation with membership/logout mutations.
            with self.db.begin() as conn:
                _, _, _, row = self.locked(conn, claim)
                if row["state"] != "STARTING":
                    raise Problem(409, "vendor_start_intent_consumed")
                remaining = row["deadline"] - time.time()
                if not 0 < remaining <= 300:
                    raise Problem(409, "vendor_deadline_expired")
                limit = time.monotonic() + remaining
                proc = subprocess.Popen(
                    [sys.executable, "-m", "intelligenceai.web.fixture_vendor", str(self.root)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    cwd=self.root,
                    env=child_environment(self.root),
                )
                conn.execute(
                    update(vendor_invocations)
                    .where(vendor_invocations.c.id == claim.invocation_id)
                    .values(state="EXECUTING")
                )
            proc.stdin.write(canonical(descriptor))
            proc.stdin.close()
            reason = "EXITED"
            while proc.poll() is None:
                try:
                    with self.db.begin() as conn:
                        self.locked(conn, claim)
                except Problem:
                    reason = "AUTHORITY_OR_CANCEL_CHANGED"
                    proc.kill()
                    break
                if time.monotonic() >= limit:
                    reason = "DEADLINE"
                    proc.kill()
                    break
                time.sleep(0.05)
            returncode = proc.wait(timeout=3)
            result = self.completion(claim, descriptor, returncode, reason)
            self.crash("receipt")
            return self.finish(claim, result)
        except (Problem, SafetyError, OSError, ValueError, subprocess.TimeoutExpired):
            if proc is not None or not self.never_started(claim):
                self.uncertain(claim)
            raise Problem(409, "fixture_vendor_result_unavailable") from None
        finally:
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait(timeout=3)

    def run_once(self):
        claim = self.claim()
        if claim is None:
            return None
        self.crash("claimed")
        return self.run_claim(claim)

    def reconcile(self, invocation_id):
        with self.db.connect() as conn:
            row = (
                conn.execute(
                    select(vendor_invocations).where(vendor_invocations.c.id == invocation_id)
                )
                .mappings()
                .one()
            )
        claim = VendorClaim(
            invocation_id,
            row["project_id"],
            row["task_id"],
            row["generation"],
            row["lease_token"] or "",
        )
        with self.db.begin() as conn:
            _, task, job, row = self.locked(conn, claim, authority=False, fenced=False)
            if row["state"] in {"COMPLETED", "TERMINATED"}:
                return task["state"]
            if row["state"] == "RESERVED":
                return task["state"]
            if (row["lease_expires_at"] or 0) > now():
                raise Problem(409, "vendor_still_owned")
            path = self.root / invocation_id / "supervisor-completed.json"
            resumable = row["state"] == "CLAIMED"
            if not path.is_file() and not resumable:
                conn.execute(
                    update(vendor_invocations)
                    .where(vendor_invocations.c.id == invocation_id)
                    .values(state="NEEDS_RECONCILIATION")
                )
                conn.execute(
                    update(tasks)
                    .where(tasks.c.id == claim.task_id)
                    .values(state="NEEDS_RECONCILIATION")
                )
                return "NEEDS_RECONCILIATION"
            result = None if resumable else self.read_owned_json(path)
            token = secrets.token_hex(32)
            claim = VendorClaim(
                invocation_id, row["project_id"], row["task_id"], row["generation"], token
            )
            expires = now() + self.lease_seconds
            conn.execute(
                update(vendor_invocations)
                .where(vendor_invocations.c.id == invocation_id)
                .values(lease_token=token, lease_expires_at=expires)
            )
            conn.execute(
                update(jobs)
                .where(jobs.c.id == job["id"])
                .values(lease_token=token, lease_expires_at=expires)
            )
        return self.run_claim(claim) if resumable else self.finish(claim, result)


def main():
    parser = argparse.ArgumentParser(description="Approved fixed synthetic vendor; no live models")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--reconcile")
    args = parser.parse_args()
    if not args.once and not args.reconcile:
        parser.error("choose --once or --reconcile INVOCATION_UUID")
    try:
        db = engine(os.environ["IAI_RUNNER_DATABASE_URL"])
        runner = ApprovedFixtureRunner(db, Path(os.environ["IAI_RUNNER_STATE_DIR"]) / "vendor")
        print(runner.reconcile(args.reconcile) if args.reconcile else runner.run_once())
    except Exception:
        raise SystemExit(
            "Fixture operation unavailable; inspect authorized private audit"
        ) from None


if __name__ == "__main__":
    main()
