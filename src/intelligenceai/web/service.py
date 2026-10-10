"""Transactional application service. Actor comes exclusively from the server session."""

import hashlib
import secrets
from collections.abc import Callable

from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from intelligenceai.security import clean, digest
from intelligenceai.web.contracts import ApprovalInput, MemberInput, TaskInput, preview
from intelligenceai.web.store import (
    approvals,
    artifacts,
    attempts,
    audit,
    execution_grants,
    jobs,
    members,
    now,
    paid_requests,
    projects,
    receipts,
    sessions,
    tasks,
    uid,
    users,
    vendor_invocations,
)


class Problem(Exception):
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code


class Service:
    def __init__(self, db):
        self.db = db

    def authorize(self, conn, actor: str, project_id: str, roles=None, *, lock=False):
        query = select(projects).where(projects.c.id == project_id)
        if lock:
            query = query.with_for_update()
        project = conn.execute(query).mappings().first()
        role = conn.execute(
            select(members.c.role)
            .join(users, users.c.id == members.c.user_id)
            .where(
                members.c.project_id == project_id,
                members.c.user_id == actor,
                users.c.active.is_(True),
            )
        ).scalar()
        if project is None or role is None or role == "revoked":
            raise Problem(404, "project_not_found")
        if roles and role not in roles:
            raise Problem(403, "role_required")
        return dict(project), role

    def project_list(self, actor):
        with self.db.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    select(projects, members.c.role)
                    .join(members)
                    .where(members.c.user_id == actor, members.c.role != "revoked")
                    .order_by(projects.c.name)
                    .limit(100)
                ).mappings()
            ]

    def project(self, actor, project_id):
        with self.db.connect() as conn:
            project, role = self.authorize(conn, actor, project_id)
            project["role"] = role
            project["members"] = [
                dict(row)
                for row in conn.execute(
                    select(members.c.user_id, members.c.role, users.c.name)
                    .join(users)
                    .where(members.c.project_id == project_id)
                    .order_by(users.c.name)
                    .limit(100)
                ).mappings()
            ]
            return project

    def task_list(self, actor, project_id):
        with self.db.connect() as conn:
            self.authorize(conn, actor, project_id)
            return [
                self.view(row)
                for row in conn.execute(
                    select(tasks)
                    .where(tasks.c.project_id == project_id)
                    .order_by(tasks.c.created_at.desc(), tasks.c.id)
                    .limit(100)
                ).mappings()
            ]

    @staticmethod
    def view(row):
        result = dict(row)
        result["execution_enabled"] = False
        result["model_calls"] = 0
        result["source"] = "private-ledger"
        return result

    def task(self, actor, project_id, task_id):
        with self.db.connect() as conn:
            self.authorize(conn, actor, project_id)
            row = self.task_row(conn, project_id, task_id)
            result = self.view(row)
            result["artifacts"] = [
                dict(a)
                for a in conn.execute(
                    select(artifacts.c.id, artifacts.c.name, artifacts.c.kind, artifacts.c.digest)
                    .where(artifacts.c.task_id == task_id)
                    .limit(50)
                ).mappings()
            ]
            approved = conn.execute(
                select(approvals.c.binding).where(approvals.c.task_id == task_id)
            ).scalar()
            result["approval"] = approved
            result["runs"] = list(
                reversed(
                    [
                        dict(r) | {"receipt": self.receipt_view(r["receipt"])}
                        for r in conn.execute(
                            select(
                                attempts.c.core_task_id,
                                attempts.c.generation,
                                attempts.c.phase,
                                attempts.c.receipt,
                            )
                            .where(attempts.c.task_id == task_id)
                            .order_by(attempts.c.generation.desc())
                            .limit(10)
                        ).mappings()
                    ]
                )
            )
            result["vendor_runs"] = [
                dict(value)
                for value in conn.execute(
                    select(
                        vendor_invocations.c.id,
                        vendor_invocations.c.generation,
                        vendor_invocations.c.state,
                        vendor_invocations.c.result,
                    )
                    .where(vendor_invocations.c.task_id == task_id)
                    .order_by(vendor_invocations.c.generation.desc())
                    .limit(10)
                ).mappings()
            ]
            return result

    @staticmethod
    def receipt_view(value):
        if value and value.get("never_started") is True:
            return {"kind": "never_started", "never_started": True}
        if (
            value
            and value.get("scope") == "FIXTURE_STATIC_ONLY"
            and isinstance(value.get("steps"), list)
        ):
            return value | {"kind": "completed"}
        return None

    @staticmethod
    def task_row(conn, project_id, task_id):
        row = (
            conn.execute(
                select(tasks).where(tasks.c.project_id == project_id, tasks.c.id == task_id)
            )
            .mappings()
            .first()
        )
        if row is None:
            raise Problem(404, "task_not_found")
        return row

    @staticmethod
    def record(conn, project_id, actor, event, detail, task_id=None):
        conn.execute(
            insert(audit).values(
                id=uid(),
                project_id=project_id,
                actor_id=actor,
                task_id=task_id,
                event=event,
                detail=clean(detail),
                created_at=now(),
            )
        )

    @staticmethod
    def validate_key(key):
        if not key or len(key) > 128 or not all(c.isalnum() or c in "-_" for c in key):
            raise Problem(400, "idempotency_key_required")

    def approval_receipt(self, actor, project_id, task_id, key):
        """Read an actor's historical receipt without creating or replaying a mutation."""
        self.validate_key(key)
        with self.db.connect() as conn:
            self.authorize(conn, actor, project_id, {"owner", "approver"})
            self.task_row(conn, project_id, task_id)
            result = conn.execute(
                select(receipts.c.result).where(
                    receipts.c.project_id == project_id,
                    receipts.c.actor_id == actor,
                    receipts.c.key == key,
                )
            ).scalar()
            if not result or result.get("id") != task_id or not result.get("review_approved"):
                return {"found": False}
            return {"found": True, "result": result}

    def mutate(self, actor, project_id, key, payload, roles, operation: Callable):
        self.validate_key(key)
        fingerprint = digest(payload)
        with self.db.begin() as conn:
            project, _ = self.authorize(conn, actor, project_id, roles, lock=True)
            receipt = (
                conn.execute(
                    select(receipts).where(
                        receipts.c.project_id == project_id,
                        receipts.c.actor_id == actor,
                        receipts.c.key == key,
                    )
                )
                .mappings()
                .first()
            )
            if receipt:
                if receipt["payload_digest"] != fingerprint:
                    raise Problem(409, "idempotency_conflict")
                return receipt["result"]
            result = operation(conn, project)
            conn.execute(
                insert(receipts).values(
                    project_id=project_id,
                    actor_id=actor,
                    key=key,
                    payload_digest=fingerprint,
                    result=result,
                )
            )
            return result

    def submit(self, actor, project_id, key, data: TaskInput):
        def operation(conn, _):
            task_id = uid()
            conn.execute(
                insert(tasks).values(
                    id=task_id,
                    project_id=project_id,
                    actor_id=actor,
                    title=clean(data.title),
                    request=clean(data.request),
                    plan=preview(data),
                    state="BLOCKED",
                    generation=1,
                    created_at=now(),
                )
            )
            conn.execute(insert(jobs).values(id=uid(), task_id=task_id, generation=1, state="HELD"))
            self.record(conn, project_id, actor, "task.submitted", {"state": "BLOCKED"}, task_id)
            return {"id": task_id, "state": "BLOCKED", "execution_enabled": False}

        return self.mutate(
            actor, project_id, key, {"submit": data.model_dump()}, {"owner", "operator"}, operation
        )

    def cancel(self, actor, project_id, task_id, key):
        def operation(conn, _):
            task = self.task_row(conn, project_id, task_id)
            job = (
                conn.execute(select(jobs).where(jobs.c.task_id == task_id).with_for_update())
                .mappings()
                .one()
            )
            if task["state"] == "CANCELLED":
                return {"id": task_id, "state": "CANCELLED"}
            vendor = (
                conn.execute(
                    select(vendor_invocations)
                    .where(
                        vendor_invocations.c.task_id == task_id,
                        vendor_invocations.c.generation == task["generation"],
                    )
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            completed = (
                conn.execute(
                    select(attempts).where(
                        attempts.c.task_id == task_id,
                        attempts.c.generation == task["generation"],
                        attempts.c.phase == "RECEIVED",
                    )
                )
                .mappings()
                .first()
            )
            confirmed_complete = bool(
                job["state"] == "FINISHED"
                and job["lease_token"] is None
                and job["generation"] == task["generation"]
                and completed
                and completed["receipt"]
                and completed["receipt"].get("kind", "completed") == "completed"
                and completed["receipt"].get("scope") == "FIXTURE_STATIC_ONLY"
            )
            confirmed = (
                job["state"] in {"HELD", "QUEUED"} and job["lease_token"] is None
            ) or confirmed_complete
            if vendor:
                confirmed = bool(
                    vendor["state"] == "RESERVED"
                    and job["lease_token"] is None
                    or vendor["state"] in {"COMPLETED", "TERMINATED"}
                    and vendor["result"]
                    and vendor["result"].get("termination_confirmed") is True
                    and job["lease_token"] is None
                )
                if vendor["state"] == "RESERVED" and confirmed:
                    conn.execute(
                        update(vendor_invocations)
                        .where(vendor_invocations.c.id == vendor["id"])
                        .values(
                            state="TERMINATED",
                            result={
                                "kind": "never_started",
                                "termination_confirmed": True,
                                "scope": "FAKE_VENDOR_TEST_ONLY",
                                "live_model": "NOTRUN",
                            },
                        )
                    )
            from intelligenceai.web.store import paid_reviews

            paid = (
                conn.execute(
                    select(paid_reviews)
                    .where(
                        paid_reviews.c.task_id == task_id,
                        paid_reviews.c.generation == task["generation"],
                    )
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if paid:
                confirmed = bool(
                    paid["state"] == "RESERVED"
                    and job["lease_token"] is None
                    or paid["termination_confirmed"]
                    and paid["state"] in {"SETTLED", "IMPORTED", "TERMINATED"}
                    and job["lease_token"] is None
                )
                if paid["state"] == "RESERVED" and confirmed:
                    from intelligenceai.web.paid_store import PaidLedger

                    PaidLedger(self.db).release_unsent(conn, paid)
                conn.execute(
                    update(paid_reviews).where(paid_reviews.c.id == paid["id"]).values(revoked=True)
                )
            if job["state"] == "FINISHED" and not confirmed_complete and not paid:
                raise Problem(409, "termination_receipt_required")
            state = "CANCELLED" if confirmed else "CANCEL_REQUESTED"
            conn.execute(
                update(jobs)
                .where(jobs.c.id == job["id"])
                .values(cancel_requested=True, state="CANCELLED" if confirmed else job["state"])
            )
            conn.execute(update(tasks).where(tasks.c.id == task_id).values(state=state))
            conn.execute(
                update(paid_requests)
                .where(
                    paid_requests.c.task_id == task_id,
                    paid_requests.c.state.in_(["QUOTED", "APPROVED", "REQUESTED", "DISPATCHED"]),
                )
                .values(state="REVOKED")
            )
            conn.execute(delete(approvals).where(approvals.c.task_id == task_id))
            self.record(
                conn,
                project_id,
                actor,
                "task.cancel",
                {"state": state, "completed_receipt": confirmed_complete},
                task_id,
            )
            return {"id": task_id, "state": state}

        return self.mutate(
            actor, project_id, key, {"cancel": task_id}, {"owner", "operator"}, operation
        )

    def recover(self, actor, project_id, task_id, key):
        def operation(conn, _):
            task = self.task_row(conn, project_id, task_id)
            job = (
                conn.execute(select(jobs).where(jobs.c.task_id == task_id).with_for_update())
                .mappings()
                .one()
            )
            if job["lease_token"] is not None or job["state"] not in {
                "HELD",
                "CANCELLED",
                "FINISHED",
            }:
                raise Problem(409, "termination_receipt_required")
            if task["state"] not in {"BLOCKED", "FAILED", "CANCELLED"}:
                raise Problem(409, "recovery_not_available")
            generation = task["generation"] + 1
            conn.execute(
                update(tasks)
                .where(tasks.c.id == task_id)
                .values(
                    generation=generation,
                    state="BLOCKED",
                    candidate_digest=None,
                    evidence_digest=None,
                    evidence_verified=False,
                )
            )
            conn.execute(
                update(jobs)
                .where(jobs.c.id == job["id"])
                .values(generation=generation, state="HELD", cancel_requested=False)
            )
            conn.execute(delete(approvals).where(approvals.c.task_id == task_id))
            conn.execute(delete(artifacts).where(artifacts.c.task_id == task_id))
            conn.execute(
                update(paid_requests)
                .where(
                    paid_requests.c.task_id == task_id,
                    paid_requests.c.state.in_(["QUOTED", "APPROVED", "REQUESTED", "DISPATCHED"]),
                )
                .values(state="REVOKED")
            )
            self.record(
                conn, project_id, actor, "task.recovered", {"generation": generation}, task_id
            )
            return {"id": task_id, "state": "BLOCKED", "generation": generation}

        return self.mutate(
            actor, project_id, key, {"recover": task_id}, {"owner", "operator"}, operation
        )

    def run_fixture(self, actor, project_id, task_id, key):
        """Explicit bounded admission; a private-review approval cannot enable execution."""

        def operation(conn, project):
            task = self.task_row(conn, project_id, task_id)
            job = (
                conn.execute(select(jobs).where(jobs.c.task_id == task_id).with_for_update())
                .mappings()
                .one()
            )
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
                raise Problem(409, "fixture_execution_grant_required")
            if job["state"] != "HELD" or job["lease_token"] or task["state"] != "BLOCKED":
                raise Problem(409, "fixture_run_not_available")
            conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(state="QUEUED"))
            conn.execute(update(tasks).where(tasks.c.id == task_id).values(state="QUEUED"))
            self.record(
                conn,
                project_id,
                actor,
                "fixture.queued",
                {"scope": "FIXTURE_STATIC_ONLY", "model_calls": 0},
                task_id,
            )
            return {"id": task_id, "state": "QUEUED", "execution_enabled": False}

        return self.mutate(
            actor, project_id, key, {"run_fixture": task_id}, {"owner", "operator"}, operation
        )

    @staticmethod
    def check_binding(task, project, binding, *, states=frozenset({"READY_FOR_APPROVAL"})):
        expected = {
            "candidate_digest": task["candidate_digest"],
            "policy_digest": project["policy_digest"],
            "evidence_digest": task["evidence_digest"],
            "destination_id": task["destination_id"],
            "generation": task["generation"],
        }
        if not task["evidence_verified"] or task["state"] not in states:
            raise Problem(409, "verified_evidence_required")
        if any(binding.get(k) != v for k, v in expected.items()):
            raise Problem(409, "approval_binding_changed")
        if not now() < binding["expires_at"] <= now() + 900:
            raise Problem(409, "approval_expired_or_ttl_invalid")

    def approve(self, actor, project_id, task_id, key, data: ApprovalInput):
        def operation(conn, project):
            task = self.task_row(conn, project_id, task_id)
            binding = data.model_dump()
            self.check_binding(task, project, binding)
            self.check_snapshot(conn, task)
            conn.execute(delete(approvals).where(approvals.c.task_id == task_id))
            conn.execute(
                insert(approvals).values(
                    task_id=task_id, actor_id=actor, binding=binding, created_at=now()
                )
            )
            self.record(conn, project_id, actor, "review.approved", binding, task_id)
            return {"id": task_id, "review_approved": True, "execution_enabled": False}

        return self.mutate(
            actor,
            project_id,
            key,
            {"approve": task_id, "binding": data.model_dump()},
            {"owner", "approver"},
            operation,
        )

    @staticmethod
    def check_snapshot(conn, task):
        """The frozen fixture receipt and private artifact bytes must still agree."""
        snapshot = conn.execute(
            select(attempts.c.receipt).where(
                attempts.c.task_id == task["id"],
                attempts.c.generation == task["generation"],
                attempts.c.phase == "RECEIVED",
            )
        ).scalar()
        if snapshot is None:
            if conn.execute(
                select(attempts.c.core_task_id).where(
                    attempts.c.task_id == task["id"], attempts.c.generation == task["generation"]
                )
            ).first():
                raise Problem(409, "verified_evidence_required")
            # Legacy/operator-imported static reviews have no runner mapping.
            return
        values = list(
            conn.execute(
                select(artifacts).where(
                    artifacts.c.task_id == task["id"], artifacts.c.kind == "candidate"
                )
            ).mappings()
        )
        if (
            digest(snapshot["candidate"]) != task["candidate_digest"]
            or digest(snapshot["evidence"]) != task["evidence_digest"]
            or len(values) != len(snapshot["contents"])
        ):
            raise Problem(409, "approval_binding_changed")
        for item in values:
            content = snapshot["contents"].get(item["name"])
            if (
                content is None
                or item["content"] != content
                or item["digest"] != hashlib.sha256(content.encode("utf-8")).hexdigest()
            ):
                raise Problem(409, "approval_binding_changed")

    def approved_fixture_authority(self, conn, project, task, actor, session_hash):
        """Current DB authority for the fixed synthetic executable, never a paid call."""
        self.authorize(conn, actor, project["id"], {"owner", "operator"})
        session = (
            conn.execute(
                select(sessions).where(sessions.c.token_hash == session_hash).with_for_update()
            )
            .mappings()
            .first()
        )
        if (
            not session
            or session["revoked"]
            or session["expires_at"] <= now()
            or session["data"].get("user_id") != actor
        ):
            raise Problem(409, "execution_session_required")
        approved = (
            conn.execute(
                select(approvals).where(approvals.c.task_id == task["id"]).with_for_update()
            )
            .mappings()
            .first()
        )
        if not approved:
            raise Problem(409, "current_review_approval_required")
        self.authorize(conn, approved["actor_id"], project["id"], {"owner", "approver"})
        self.check_binding(
            task,
            project,
            approved["binding"],
            states=frozenset(
                {
                    "READY_FOR_APPROVAL",
                    "VENDOR_QUEUED",
                    "VENDOR_RUNNING",
                }
            ),
        )
        snapshot = conn.execute(
            select(attempts.c.receipt).where(
                attempts.c.task_id == task["id"],
                attempts.c.generation == task["generation"],
                attempts.c.phase == "RECEIVED",
            )
        ).scalar()
        if not snapshot or snapshot.get("scope") != "FIXTURE_STATIC_ONLY":
            raise Problem(409, "owned_fixture_receipt_required")
        self.check_snapshot(conn, task)
        grant = (
            conn.execute(
                select(execution_grants).where(execution_grants.c.project_id == project["id"])
            )
            .mappings()
            .first()
        )
        if (
            not grant
            or grant["mode"] != "fixed-fixture"
            or grant["expires_at"] <= now()
            or grant["policy_digest"] != project["policy_digest"]
        ):
            raise Problem(409, "fixture_execution_grant_required")
        return approved, session, grant

    def run_approved_fixture(self, actor, project_id, task_id, key, *, session_hash):
        def operation(conn, project):
            task = self.task_row(conn, project_id, task_id)
            job = (
                conn.execute(select(jobs).where(jobs.c.task_id == task_id).with_for_update())
                .mappings()
                .one()
            )
            approved, session, grant = self.approved_fixture_authority(
                conn, project, task, actor, session_hash
            )
            if conn.execute(
                select(vendor_invocations.c.id).where(
                    vendor_invocations.c.task_id == task_id,
                    vendor_invocations.c.generation == task["generation"],
                )
            ).first():
                raise Problem(409, "invocation_already_reserved")
            if job["state"] != "FINISHED" or job["lease_token"] or job["cancel_requested"]:
                raise Problem(409, "approved_fixture_not_available")
            invocation_id = uid()
            binding = approved["binding"]
            conn.execute(
                insert(vendor_invocations).values(
                    id=invocation_id,
                    project_id=project_id,
                    task_id=task_id,
                    generation=task["generation"],
                    actor_id=actor,
                    session_hash=session_hash,
                    approved_by=approved["actor_id"],
                    binding=binding,
                    binding_digest=digest(binding),
                    deadline=min(
                        now() + 300,
                        binding["expires_at"],
                        session["expires_at"],
                        grant["expires_at"],
                    ),
                    state="RESERVED",
                    created_at=now(),
                )
            )
            conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(state="VENDOR_QUEUED"))
            conn.execute(update(tasks).where(tasks.c.id == task_id).values(state="VENDOR_QUEUED"))
            self.record(
                conn,
                project_id,
                actor,
                "fixture.vendor_reserved",
                {
                    "invocation_id": invocation_id,
                    "scope": "FAKE_VENDOR_TEST_ONLY",
                    "live_model": "NOTRUN",
                },
                task_id,
            )
            return {
                "id": task_id,
                "invocation_id": invocation_id,
                "state": "VENDOR_QUEUED",
                "execution_enabled": False,
                "scope": "FAKE_VENDOR_TEST_ONLY",
            }

        return self.mutate(
            actor,
            project_id,
            key,
            {"run_approved_fixture": task_id},
            {"owner", "operator"},
            operation,
        )

    def reject(self, actor, project_id, task_id, key):
        def operation(conn, _):
            task = self.task_row(conn, project_id, task_id)
            if task["state"] not in {"READY_FOR_APPROVAL", "BLOCKED"}:
                raise Problem(409, "review_not_available")
            conn.execute(delete(approvals).where(approvals.c.task_id == task_id))
            conn.execute(update(tasks).where(tasks.c.id == task_id).values(state="BLOCKED"))
            self.record(conn, project_id, actor, "review.rejected", {}, task_id)
            return {"id": task_id, "state": "BLOCKED"}

        return self.mutate(
            actor, project_id, key, {"reject": task_id}, {"owner", "approver"}, operation
        )

    def member(self, actor, project_id, key, data: MemberInput):
        def operation(conn, _):
            if data.user_id == actor:
                raise Problem(409, "self_role_change_forbidden")
            row = conn.execute(
                select(members).where(
                    members.c.project_id == project_id, members.c.user_id == data.user_id
                )
            ).first()
            # New identities and cross-tenant enrollment are operator provisioning, not web input.
            if row is None:
                raise Problem(404, "member_not_found")
            conn.execute(
                update(members)
                .where(members.c.project_id == project_id, members.c.user_id == data.user_id)
                .values(role=data.role)
            )
            self.record(conn, project_id, actor, "member.role_changed", data.model_dump())
            return {"user_id": data.user_id, "role": data.role}

        return self.mutate(
            actor, project_id, key, {"member": data.model_dump()}, {"owner"}, operation
        )

    def events(self, actor, project_id, *, task_id=None, limit=100):
        with self.db.connect() as conn:
            self.authorize(conn, actor, project_id)
            query = select(audit).where(audit.c.project_id == project_id)
            if task_id:
                self.task_row(conn, project_id, task_id)
                query = query.where(audit.c.task_id == task_id)
            return [
                dict(row)
                for row in conn.execute(
                    query.order_by(audit.c.created_at.desc(), audit.c.id).limit(limit)
                ).mappings()
            ]

    def artifact(self, actor, project_id, task_id, artifact_id):
        with self.db.connect() as conn:
            self.authorize(conn, actor, project_id)
            self.task_row(conn, project_id, task_id)
            row = (
                conn.execute(
                    select(artifacts).where(
                        artifacts.c.task_id == task_id, artifacts.c.id == artifact_id
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise Problem(404, "artifact_not_found")
            return dict(row)

    def dispatch(self, actor, project_id, task_id):
        """Trusted runner contract: recheck the grant immediately before any effect.

        No production runner is implemented. Even valid approvals cannot dispatch.
        """
        with self.db.begin() as conn:
            project, _ = self.authorize(conn, actor, project_id, {"owner", "approver"}, lock=True)
            task = self.task_row(conn, project_id, task_id)
            grant = (
                conn.execute(select(approvals).where(approvals.c.task_id == task_id))
                .mappings()
                .first()
            )
            if grant is None:
                raise Problem(409, "approval_required")
            self.authorize(conn, grant["actor_id"], project_id, {"owner", "approver"})
            self.check_binding(task, project, grant["binding"])
            self.check_snapshot(conn, task)
            raise Problem(503, "runner_and_external_effects_disabled")


def bootstrap(db, issuer, subject, name, project_name):
    """Operator-only provisioning; no HTTP route, no auto-enrollment on login."""
    try:
        with db.begin() as conn:
            user_id, project_id = uid(), uid()
            conn.execute(
                insert(users).values(id=user_id, issuer=issuer, subject=subject, name=clean(name))
            )
            conn.execute(
                insert(projects).values(
                    id=project_id,
                    tenant_id=uid(),
                    name=clean(project_name),
                    policy_digest=digest({"version": 1, "dispatch": "disabled"}),
                )
            )
            conn.execute(
                insert(members).values(project_id=project_id, user_id=user_id, role="owner")
            )
            return user_id, project_id
    except IntegrityError:
        raise Problem(409, "identity_already_provisioned") from None


def session_data(user_id=None):
    return {"user_id": user_id, "csrf": secrets.token_urlsafe(32)}
