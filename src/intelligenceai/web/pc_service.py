"""Owner-approved outbound PC queue. Device reports are never OS attestation.

The atomic start transaction is the authorization boundary. Revocation after it
is best effort. A consumed attempt is never automatically replayed.
"""

import hashlib
import secrets

from sqlalchemy import insert, select, update

from intelligenceai.security import clean, digest
from intelligenceai.web.auth import token_hash
from intelligenceai.web.cli_runtime import SUPPORTED_VERSIONS
from intelligenceai.web.cli_service import LocalCLI
from intelligenceai.web.service import Problem, Service
from intelligenceai.web.store import (
    artifacts,
    jobs,
    members,
    now,
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
from intelligenceai.web.store import (
    pc_attempts as attempts,
)
from intelligenceai.web.store import (
    pc_runners as runners,
)


class PCs:
    def __init__(self, db, *, testing=False):
        self.db, self.testing = db, testing
        self.service, self.cli = Service(db), LocalCLI(db)

    @staticmethod
    def view(row):
        return {
            key: row[key]
            for key in (
                "id",
                "provider",
                "state",
                "expires_at",
                "manifest",
                "manifest_digest",
                "profile_id",
            )
        }

    def list(self, actor, project):
        with self.db.connect() as conn:
            self.service.authorize(conn, actor, project, {"owner"})
            return [
                self.view(row)
                for row in conn.execute(
                    select(runners).where(
                        runners.c.actor_id == actor, runners.c.project_id == project
                    )
                ).mappings()
            ]

    def pair(self, actor, project, key, data):
        # Receipt/audit persist the ID only; plaintext pairing code is returned once.
        code = secrets.token_urlsafe(32)
        issued = False

        def operation(conn, _):
            nonlocal issued
            issued = True
            row = dict(
                id=uid(),
                actor_id=actor,
                project_id=project,
                provider=data.provider,
                pair_hash=token_hash(code),
                state="PAIRING",
                expires_at=now() + 300,
                manifest=None,
                manifest_digest=None,
                profile_id=None,
            )
            conn.execute(insert(runners).values(**row))
            self.service.record(
                conn, project, actor, "pc.pairing_created", {"runner_id": row["id"]}
            )
            return self.view(row)

        result = self.service.mutate(
            actor, project, key, {"pc_pair": data.provider}, {"owner"}, operation
        )
        return result | {"pairing_code": code if issued else None}

    def exchange(self, code, data):
        with self.db.begin() as conn:
            initial = conn.execute(select(runners).where(runners.c.pair_hash == token_hash(code)))
            row = initial.mappings().first()
            if not row:
                raise Problem(401, "pc_pairing_unavailable")
            self.service.authorize(conn, row["actor_id"], row["project_id"], {"owner"}, lock=True)
            row = (
                conn.execute(select(runners).where(runners.c.id == row["id"]).with_for_update())
                .mappings()
                .one()
            )
            if row["state"] != "PAIRING" or row["expires_at"] <= now():
                raise Problem(409, "pc_pairing_unavailable")
            manifest = data.manifest.model_dump()
            if (
                manifest["provider"] != row["provider"]
                or (manifest["scope"] == "FAKE_CLI_TEST_ONLY" and not self.testing)
                or (
                    manifest["scope"] != "FAKE_CLI_TEST_ONLY"
                    and SUPPORTED_VERSIONS.get(row["provider"]) != manifest["version"]
                )
            ):
                raise Problem(409, "pc_manifest_unsupported")
            if secrets.compare_digest(code, data.token):
                raise Problem(422, "pc_distinct_token_required")
            conn.execute(
                update(runners)
                .where(runners.c.id == row["id"])
                .values(
                    pair_hash=None,
                    token_hash=token_hash(data.token),
                    state="PENDING",
                    manifest=manifest,
                    manifest_digest=digest(manifest),
                )
            )
            self.service.record(
                conn,
                row["project_id"],
                row["actor_id"],
                "pc.proposed",
                {"runner_id": row["id"], "manifest_digest": digest(manifest)},
            )
            return {"runner_id": row["id"], "state": "PENDING", "manifest_digest": digest(manifest)}

    def change(self, actor, project, runner_id, key, data, action):
        def operation(conn, _):
            row = (
                conn.execute(
                    select(runners)
                    .where(
                        runners.c.id == runner_id,
                        runners.c.actor_id == actor,
                        runners.c.project_id == project,
                    )
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if not row:
                raise Problem(404, "pc_not_found")
            if action == "confirm":
                if (
                    row["state"] != "PENDING"
                    or row["expires_at"] <= now()
                    or row["manifest_digest"] != data.manifest_digest
                ):
                    raise Problem(409, "pc_pairing_unavailable")
                profile = uid()
                metadata = row["manifest"] | {
                    "transport": "OUTBOUND_PC",
                    "runner_id": row["id"],
                    "registration_digest": row["manifest_digest"],
                    "can_execute": True,
                    "installation": "DEVICE_REPORTED",
                    "availability": "UNVERIFIED",
                }
                conn.execute(
                    insert(profiles).values(
                        id=profile,
                        project_id=project,
                        actor_id=actor,
                        provider=row["provider"],
                        runtime_digest=row["manifest"]["runtime_digest"],
                        metadata=metadata,
                    )
                )
                conn.execute(
                    update(runners)
                    .where(runners.c.id == runner_id)
                    .values(state="ACTIVE", expires_at=now() + 30 * 86400, profile_id=profile)
                )
            else:
                conn.execute(
                    update(runners)
                    .where(runners.c.id == runner_id)
                    .values(state="REVOKED", pair_hash=None)
                )
                if row["profile_id"]:
                    conn.execute(
                        update(profiles)
                        .where(profiles.c.id == row["profile_id"])
                        .values(active=False)
                    )
                for attempt in conn.execute(
                    select(attempts).where(
                        attempts.c.runner_id == runner_id,
                        attempts.c.state.in_(["CLAIMED", "STARTED"]),
                    )
                ).mappings():
                    self.unknown(conn, attempt)
            self.service.record(conn, project, actor, "pc." + action, {"runner_id": runner_id})
            return {"id": runner_id, "state": "ACTIVE" if action == "confirm" else "REVOKED"}

        return self.service.mutate(
            actor,
            project,
            key,
            {"pc_" + action: runner_id, **data.model_dump()},
            {"owner"},
            operation,
        )

    def authenticate(self, conn, token):
        row = conn.execute(select(runners).where(runners.c.token_hash == token_hash(token)))
        initial = row.mappings().first()
        if not initial:
            raise Problem(401, "pc_authorization_required")
        # Same actor fence as the direct DB worker: at most one uncertain/running call.
        user = (
            conn.execute(
                select(users)
                .where(users.c.id == initial["actor_id"])
                .with_for_update(key_share=True)
            )
            .mappings()
            .one()
        )
        self.service.authorize(conn, user["id"], initial["project_id"], {"owner"}, lock=True)
        role = conn.execute(
            select(members.c.role)
            .where(members.c.project_id == initial["project_id"], members.c.user_id == user["id"])
            .with_for_update()
        ).scalar()
        row = (
            conn.execute(select(runners).where(runners.c.id == initial["id"]).with_for_update())
            .mappings()
            .one()
        )
        if (
            not user["active"]
            or role != "owner"
            or row["state"] != "ACTIVE"
            or row["expires_at"] <= now()
        ):
            raise Problem(403, "pc_inactive")
        return row

    def unknown(self, conn, attempt):
        row = conn.execute(select(requests).where(requests.c.id == attempt["request_id"]))
        row = row.mappings().one()
        conn.execute(update(attempts).where(attempts.c.id == attempt["id"]).values(state="UNKNOWN"))
        conn.execute(
            update(requests)
            .where(requests.c.id == row["id"])
            .values(
                state="UNKNOWN",
                result={
                    "scope": "PC_REPORTED",
                    "live_model": "UNKNOWN",
                    "model_calls": None,
                    "cli_invocations": None,
                    "local_termination_confirmed": False,
                    "remote_cancellation": "UNKNOWN",
                },
            )
        )
        conn.execute(
            update(tasks)
            .where(tasks.c.id == row["task_id"], tasks.c.generation == row["generation"])
            .values(state="BLOCKED")
        )
        # Retain job lease: neither replay nor recovery is justified by timeout.

    def claim(self, token):
        with self.db.begin() as conn:
            runner = self.authenticate(conn, token)
            for expired in conn.execute(
                select(attempts).where(
                    attempts.c.runner_id == runner["id"],
                    attempts.c.state.in_(["CLAIMED", "STARTED"]),
                    attempts.c.expires_at <= now(),
                )
            ).mappings():
                self.unknown(conn, expired)
            if conn.execute(
                select(requests.c.id).where(
                    requests.c.actor_id == runner["actor_id"],
                    requests.c.state.in_(["STARTING", "RUNNING", "UNKNOWN"]),
                )
            ).first():
                return {"attempt": None}
            row = (
                conn.execute(
                    select(requests)
                    .where(
                        requests.c.profile_id == runner["profile_id"], requests.c.state == "QUEUED"
                    )
                    .order_by(requests.c.created_at)
                    .limit(1)
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if not row:
                return {"attempt": None}
            try:
                task, job, _ = self.cli.current(conn, row, {"LOCAL_CLI_QUEUED"})
            except Problem:
                # Consume obsolete consent without executing or silently re-queuing it.
                conn.execute(
                    update(requests).where(requests.c.id == row["id"]).values(state="NEVER_STARTED")
                )
                conn.execute(
                    update(tasks)
                    .where(tasks.c.id == row["task_id"], tasks.c.generation == row["generation"])
                    .values(state="BLOCKED")
                )
                conn.execute(
                    update(jobs)
                    .where(
                        jobs.c.task_id == row["task_id"],
                        jobs.c.generation == row["generation"],
                        jobs.c.lease_token.is_(None),
                    )
                    .values(state="FINISHED")
                )
                return {"attempt": None}
            if job["lease_token"] is not None:
                raise Problem(409, "pc_prior_run_unresolved")
            attempt = dict(
                id=uid(),
                runner_id=runner["id"],
                request_id=row["id"],
                binding_digest=row["binding_digest"],
                lease=secrets.token_hex(32),
                expires_at=now() + 15,
                deadline=min(now() + 60, row["binding"]["expires_at"]),
                state="CLAIMED",
            )
            conn.execute(insert(attempts).values(**attempt))
            conn.execute(
                update(requests)
                .where(requests.c.id == row["id"])
                .values(state="STARTING", lease_token=attempt["lease"])
            )
            conn.execute(
                update(jobs)
                .where(jobs.c.id == job["id"])
                .values(lease_token=attempt["lease"], lease_expires_at=attempt["expires_at"])
            )
            self.service.record(
                conn,
                runner["project_id"],
                runner["actor_id"],
                "pc.claimed",
                {"attempt_id": attempt["id"]},
                row["task_id"],
            )
            return {
                "attempt": {
                    "attempt_id": attempt["id"],
                    "task_id": task["id"],
                    "generation": row["generation"],
                    "binding_digest": row["binding_digest"],
                    "lease": attempt["lease"],
                    "expires_at": attempt["expires_at"],
                    "deadline": attempt["deadline"],
                    "provider": runner["provider"],
                    "runtime_digest": runner["manifest"]["runtime_digest"],
                    "payload_sha256": row["binding"]["payload"]["payload_sha256"],
                    "prompt": self.cli.prompt(conn, task)[0],
                }
            }

    def bound(self, conn, runner, data):
        attempt = (
            conn.execute(
                select(attempts)
                .where(attempts.c.id == data.attempt_id, attempts.c.runner_id == runner["id"])
                .with_for_update()
            )
            .mappings()
            .first()
        )
        if not attempt:
            raise Problem(404, "pc_attempt_not_found")
        row = (
            conn.execute(
                select(requests).where(requests.c.id == attempt["request_id"]).with_for_update()
            )
            .mappings()
            .one()
        )
        if (
            row["profile_id"] != runner["profile_id"]
            or row["task_id"] != data.task_id
            or row["generation"] != data.generation
            or data.binding_digest != attempt["binding_digest"]
            or row["binding_digest"] != data.binding_digest
            or not secrets.compare_digest(data.lease, attempt["lease"])
        ):
            raise Problem(409, "pc_attempt_changed")
        return attempt, row

    def start(self, token, data):
        with self.db.begin() as conn:
            runner = self.authenticate(conn, token)
            attempt, row = self.bound(conn, runner, data)
            if attempt["state"] != "CLAIMED" or attempt["expires_at"] <= now():
                raise Problem(409, "pc_start_consumed_or_expired")
            _, job, _ = self.cli.current(conn, row, {"LOCAL_CLI_QUEUED"})
            if job["lease_token"] != data.lease:
                raise Problem(409, "pc_lease_changed")
            conn.execute(
                update(attempts)
                .where(attempts.c.id == data.attempt_id)
                .values(state="STARTED", expires_at=min(now() + 15, attempt["deadline"]))
            )
            conn.execute(update(requests).where(requests.c.id == row["id"]).values(state="RUNNING"))
            conn.execute(update(tasks).where(tasks.c.id == row["task_id"]).values(state="RUNNING"))
            self.service.record(
                conn,
                runner["project_id"],
                runner["actor_id"],
                "pc.start_authorized",
                {"attempt_id": data.attempt_id},
                row["task_id"],
            )
            return {"authorized": True, "deadline": attempt["deadline"], "heartbeat_seconds": 2}

    def heartbeat(self, token, data):
        with self.db.begin() as conn:
            runner = self.authenticate(conn, token)
            attempt, row = self.bound(conn, runner, data)
            valid = attempt["state"] == "STARTED" and attempt["expires_at"] > now()
            cancelling = conn.execute(
                select(jobs.c.cancel_requested).where(
                    jobs.c.task_id == row["task_id"], jobs.c.lease_token == data.lease
                )
            ).scalar()
            if valid and cancelling:
                # Keep the unexpired consumed attempt available for a cancellation report.
                return {"continue": False}
            try:
                _, job, _ = self.cli.current(conn, row, {"RUNNING"})
                valid = valid and job["lease_token"] == data.lease
            except Problem:
                valid = False
            if not valid or attempt["deadline"] <= now():
                if attempt["state"] in {"CLAIMED", "STARTED"}:
                    self.unknown(conn, attempt)
                return {"continue": False}
            expiry = min(now() + 15, attempt["deadline"])
            conn.execute(
                update(attempts).where(attempts.c.id == data.attempt_id).values(expires_at=expiry)
            )
            conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(lease_expires_at=expiry))
            return {"continue": True}

    def result(self, token, data):
        with self.db.begin() as conn:
            runner = self.authenticate(conn, token)
            attempt, row = self.bound(conn, runner, data)
            # Hash original content before redaction; only an identical upload may repeat.
            fingerprint = digest(data.model_dump())
            if attempt["result_digest"]:
                if attempt["result_digest"] != fingerprint:
                    raise Problem(409, "pc_result_conflict")
                return attempt["result"]
            if attempt["state"] != "STARTED" or attempt["expires_at"] <= now():
                raise Problem(409, "pc_result_stale")
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
            if task["generation"] != data.generation or job["lease_token"] != data.lease:
                raise Problem(409, "pc_result_stale")
            cancelled = job["cancel_requested"]
            if data.outcome == "COMPLETED" and (
                data.availability != "AVAILABLE"
                or not data.text.strip()
                or not data.cleanup_reported
            ):
                raise Problem(422, "pc_result_inconsistent")
            if not cancelled:
                self.cli.current(conn, row, {"RUNNING"})
            else:
                # A completed immutable journal can race a browser cancellation.
                # Accept its exact bound cleanup, discard text and preserve upload identity.
                if not data.cleanup_reported or data.outcome == "UNKNOWN":
                    raise Problem(409, "pc_cancel_receipt_required")
            closed = data.cleanup_reported and data.outcome != "UNKNOWN"
            completed = closed and not cancelled and data.outcome == "COMPLETED"
            # Opaque device capabilities have no vendor prefix for the common scanner.
            text = clean(data.text.replace(token, "[REDACTED]")) if completed else None
            if text:
                conn.execute(
                    insert(artifacts).values(
                        id=uid(),
                        task_id=task["id"],
                        name="device-review.txt",
                        kind="cli-result",
                        content=text,
                        digest=hashlib.sha256(text.encode()).hexdigest(),
                    )
                )
            result = {
                "scope": "PC_REPORTED",
                "source": "USER_DEVICE_REPORT",
                "live_model": "NOTRUN"
                if runner["manifest"]["scope"] == "FAKE_CLI_TEST_ONLY"
                else "UNVERIFIED",
                "availability": data.availability,
                "model_calls": None,
                "cli_invocations": None,
                "local_termination_confirmed": False,
                "device_cleanup_reported": data.cleanup_reported,
                "remote_cancellation": "DEVICE_REPORTED" if cancelled and closed else "UNKNOWN",
                "usage": {
                    "source": "USER_DEVICE_REPORT",
                    "unit": "tokens",
                    "completeness": "INPUT_OUTPUT_ONLY",
                    "measured_at": None,
                    "values": {
                        "input_tokens": data.input_tokens,
                        "output_tokens": data.output_tokens,
                    },
                },
                "outcome": "CANCELLED" if cancelled and closed else data.outcome,
                "payload": row["binding"]["payload"],
            }
            state = "COMPLETED" if completed else "FAILED" if closed else "UNKNOWN"
            conn.execute(
                update(attempts)
                .where(attempts.c.id == data.attempt_id)
                .values(
                    state="FINISHED" if closed else "UNKNOWN",
                    result_digest=fingerprint,
                    result=result,
                )
            )
            conn.execute(
                update(requests)
                .where(requests.c.id == row["id"])
                .values(state=state, result=result)
            )
            conn.execute(
                update(jobs)
                .where(jobs.c.id == job["id"])
                .values(
                    state="FINISHED" if closed else "RUNNING",
                    lease_token=None if closed else data.lease,
                    lease_expires_at=None if closed else attempt["expires_at"],
                )
            )
            conn.execute(
                update(tasks)
                .where(tasks.c.id == task["id"])
                .values(
                    state="CANCELLED"
                    if cancelled and closed
                    else "CLI_REVIEW_RECEIVED"
                    if completed
                    else "BLOCKED"
                )
            )
            self.service.record(
                conn,
                runner["project_id"],
                runner["actor_id"],
                "pc.result_reported",
                {"attempt_id": data.attempt_id, "outcome": data.outcome},
                task["id"],
            )
            return result
