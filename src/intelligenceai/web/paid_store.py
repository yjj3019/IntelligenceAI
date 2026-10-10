"""Durable at-most-once provider HTTP admission and conservative budget settlement."""

import hashlib

from sqlalchemy import (
    insert,
    select,
    update,
)

from intelligenceai.security import SafetyError, canonical, clean, digest
from intelligenceai.web.claude_contracts import ClaudeProfile, PaidReviewIntent
from intelligenceai.web.service import Service
from intelligenceai.web.store import (
    artifacts,
    audit,
    jobs,
    now,
    paid_budgets,
    paid_reviews,
    projects,
    sessions,
    tasks,
    uid,
)


class PaidLedger:
    def __init__(self, db):
        self.db, self.service = db, Service(db)

    @staticmethod
    def event(conn, intent, name, detail):
        conn.execute(
            insert(audit).values(
                id=uid(),
                project_id=intent.approval.project_id,
                actor_id=intent.approval.actor_id,
                task_id=intent.approval.task_id,
                event=name,
                detail=clean({"invocation_id": intent.invocation_id, **detail}),
                created_at=now(),
            )
        )

    def locked(self, conn, intent, session_hash, approved_by, *, check_current=True):
        if approved_by != intent.approved_by:
            raise SafetyError("paid_approver_binding_changed")
        approval = intent.approval
        project, _ = self.service.authorize(
            conn, approval.actor_id, approval.project_id, {"owner", "operator"}, lock=True
        )
        self.service.authorize(conn, approved_by, approval.project_id, {"owner", "approver"})
        task = (
            conn.execute(
                select(tasks)
                .where(tasks.c.id == approval.task_id, tasks.c.project_id == approval.project_id)
                .with_for_update()
            )
            .mappings()
            .one()
        )
        job = (
            conn.execute(select(jobs).where(jobs.c.task_id == approval.task_id).with_for_update())
            .mappings()
            .one()
        )
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
            or (session["data"].get("user_id") != approval.actor_id)
        ):
            raise SafetyError("paid_session_revoked")
        if check_current and (
            task["generation"] != approval.generation
            or job["generation"] != approval.generation
            or job["cancel_requested"]
            or task["state"] not in {"READY_FOR_APPROVAL", "VENDOR_COMPLETED", "RUNNING"}
            or not task["evidence_verified"]
            or not now() < approval.expires_at
            or task["candidate_digest"] != approval.candidate_digest
            or task["evidence_digest"] != approval.evidence_digest
            or project["policy_digest"] != approval.policy_digest
        ):
            raise SafetyError("paid_authority_changed")
        self.service.check_snapshot(conn, task)
        return project, task, job

    def reserve(self, intent, profile, *, session_hash, approved_by, receipt_digest):
        intent = PaidReviewIntent.model_validate(intent.model_dump())
        profile = ClaudeProfile.model_validate(profile.model_dump())
        if intent.profile_digest != profile.binding:
            raise SafetyError("paid_profile_changed")
        if intent.approved_by != approved_by:
            raise SafetyError("paid_approver_binding_changed")
        if profile.policy_digest != intent.approval.policy_digest or (
            profile.reservation > intent.budget_microusd
        ):
            raise SafetyError("paid_budget_insufficient")
        with self.db.begin() as conn:
            self.locked(conn, intent, session_hash, approved_by)
            if conn.execute(
                select(paid_reviews.c.id).where(
                    paid_reviews.c.task_id == intent.approval.task_id,
                    paid_reviews.c.generation == intent.approval.generation,
                )
            ).first():
                raise SafetyError("paid_invocation_already_reserved")
            budget = (
                conn.execute(
                    select(paid_budgets)
                    .where(paid_budgets.c.project_id == intent.approval.project_id)
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if (
                not budget
                or budget["expires_at"] <= now()
                or (
                    budget["policy_digest"] != profile.policy_digest
                    or budget["held_microusd"] + budget["spent_microusd"] + profile.reservation
                    > budget["limit_microusd"]
                )
            ):
                raise SafetyError("paid_project_budget_unavailable")
            conn.execute(
                update(paid_budgets)
                .where(paid_budgets.c.project_id == intent.approval.project_id)
                .values(held_microusd=budget["held_microusd"] + profile.reservation)
            )
            conn.execute(
                insert(paid_reviews).values(
                    id=intent.invocation_id,
                    project_id=intent.approval.project_id,
                    task_id=intent.approval.task_id,
                    generation=intent.approval.generation,
                    actor_id=intent.approval.actor_id,
                    session_hash=session_hash,
                    approved_by=approved_by,
                    intent=intent.model_dump(mode="json"),
                    intent_digest=intent.binding,
                    receipt_digest=receipt_digest,
                    state="RESERVED",
                    hold_microusd=profile.reservation,
                    revoked=False,
                    created_at=now(),
                )
            )

            self.event(conn, intent, "paid_review_reserved", {"held_microusd": profile.reservation})

    def admit(self, intent, request_digest):
        """Commit STARTED before HTTP. Any ambiguous send holds funds; never auto-replay."""
        with self.db.begin() as conn:
            conn.execute(
                select(projects)
                .where(projects.c.id == intent.approval.project_id)
                .with_for_update()
            ).one()
            row = (
                conn.execute(
                    select(paid_reviews)
                    .where(paid_reviews.c.id == intent.invocation_id)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            self.locked(conn, intent, row["session_hash"], row["approved_by"])
            budget = (
                conn.execute(
                    select(paid_budgets)
                    .where(paid_budgets.c.project_id == intent.approval.project_id)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if budget["expires_at"] <= now() or (
                budget["policy_digest"] != intent.approval.policy_digest
                or budget["held_microusd"] + budget["spent_microusd"] > budget["limit_microusd"]
            ):
                raise SafetyError("paid_budget_authority_changed")
            if (
                row["revoked"]
                or row["state"] != "LAUNCHING"
                or (
                    row["intent_digest"] != intent.binding
                    or digest(row["intent"]) != intent.binding
                )
            ):
                raise SafetyError("paid_request_already_consumed_or_revoked")
            conn.execute(
                update(paid_reviews)
                .where(paid_reviews.c.id == row["id"])
                .values(state="STARTED", request_digest=request_digest)
            )

            self.event(conn, intent, "paid_http_admitted", {"request_digest": request_digest})

    def claim_launch(self, intent):
        with self.db.begin() as conn:
            conn.execute(
                select(projects)
                .where(projects.c.id == intent.approval.project_id)
                .with_for_update()
            ).one()
            row = (
                conn.execute(
                    select(paid_reviews)
                    .where(paid_reviews.c.id == intent.invocation_id)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            self.locked(conn, intent, row["session_hash"], row["approved_by"])
            if (
                row["revoked"]
                or row["state"] != "RESERVED"
                or row["intent_digest"] != intent.binding
                or digest(row["intent"]) != intent.binding
            ):
                raise SafetyError("paid_launch_already_consumed")
            conn.execute(
                update(paid_reviews).where(paid_reviews.c.id == row["id"]).values(state="LAUNCHING")
            )

            self.event(conn, intent, "paid_launch_claimed", {})
            job = (
                conn.execute(
                    select(jobs).where(jobs.c.task_id == intent.approval.task_id).with_for_update()
                )
                .mappings()
                .one()
            )
            if job["lease_token"] is not None:
                raise SafetyError("paid_task_lease_conflict")
            conn.execute(
                update(jobs)
                .where(jobs.c.id == job["id"])
                .values(
                    state="RUNNING",
                    lease_token=intent.invocation_id,
                    lease_expires_at=int(intent.approval.expires_at),
                )
            )
            conn.execute(
                update(tasks).where(tasks.c.id == intent.approval.task_id).values(state="RUNNING")
            )

    def uncertain(self, invocation_id):
        with self.db.begin() as conn:
            conn.execute(
                update(paid_reviews)
                .where(
                    paid_reviews.c.id == invocation_id,
                    paid_reviews.c.state.in_(["STARTED", "LAUNCHING"]),
                )
                .values(state="NEEDS_RECONCILIATION")
            )

    def settle(self, intent, profile, usage, result):
        if intent.profile_digest != profile.binding:
            raise SafetyError("paid_settlement_profile_changed")
        # No privilege check here: settling observed upstream usage after logout/cancel is required.
        # Importing a private result has a separate current-authority check below.
        if (
            set(usage) != {"input_tokens", "output_tokens"}
            or any(type(v) is not int or v < 0 for v in usage.values())
            or usage["input_tokens"] > profile.input_token_ceiling
            or (usage["output_tokens"] > profile.output_token_limit)
        ):
            raise SafetyError("paid_usage_outside_verified_ceiling")
        charge = (
            usage["input_tokens"] * profile.input_price_ceiling
            + usage["output_tokens"] * profile.output_price_ceiling
        )
        with self.db.begin() as conn:
            # All paths take project -> review -> budget, matching reservation and admission.
            conn.execute(
                select(projects)
                .where(projects.c.id == intent.approval.project_id)
                .with_for_update()
            ).one()
            row = (
                conn.execute(
                    select(paid_reviews)
                    .where(paid_reviews.c.id == intent.invocation_id)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            budget = (
                conn.execute(
                    select(paid_budgets)
                    .where(paid_budgets.c.project_id == row["project_id"])
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if (
                row["state"] != "STARTED"
                or row["intent_digest"] != intent.binding
                or (charge > row["hold_microusd"])
            ):
                raise SafetyError("paid_settlement_conflict")
            stored = clean(
                {
                    "usage": usage,
                    "cost_upper_bound_microusd": charge,
                    "response_digest": hashlib.sha256(result).hexdigest(),
                }
            )
            conn.execute(
                update(paid_reviews)
                .where(paid_reviews.c.id == row["id"])
                .values(state="SETTLED", result=stored)
            )
            conn.execute(
                update(paid_budgets)
                .where(paid_budgets.c.project_id == row["project_id"])
                .values(
                    held_microusd=budget["held_microusd"] - row["hold_microusd"],
                    spent_microusd=budget["spent_microusd"] + charge,
                )
            )

            self.event(conn, intent, "paid_usage_settled", stored)

    def import_review(self, intent, text, *, cleanup_verified):
        if not cleanup_verified:
            raise SafetyError("paid_descendant_cleanup_unverified")
        with self.db.begin() as conn:
            # Reauthorization at import is independent of durable financial settlement.
            conn.execute(
                select(projects)
                .where(projects.c.id == intent.approval.project_id)
                .with_for_update()
            ).one()
            row = (
                conn.execute(
                    select(paid_reviews)
                    .where(paid_reviews.c.id == intent.invocation_id)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            self.locked(conn, intent, row["session_hash"], row["approved_by"])
            if row["state"] != "SETTLED" or row["revoked"] or not row["termination_confirmed"]:
                raise SafetyError("paid_review_import_conflict")
            content = clean(text)
            if len(content.encode()) > 65536:
                raise SafetyError("paid_review_output_limit")
            conn.execute(
                insert(artifacts).values(
                    id=intent.invocation_id,
                    task_id=row["task_id"],
                    name="claude-review.txt",
                    kind="review",
                    content=content,
                    digest=hashlib.sha256(content.encode()).hexdigest(),
                )
            )
            conn.execute(
                update(paid_reviews).where(paid_reviews.c.id == row["id"]).values(state="IMPORTED")
            )

            self.event(conn, intent, "paid_review_imported", {"artifact_id": intent.invocation_id})

    def review_prompt(self, intent):
        with self.db.connect() as conn:
            files = list(
                conn.execute(
                    select(artifacts)
                    .where(
                        artifacts.c.task_id == intent.approval.task_id,
                        artifacts.c.kind == "candidate",
                    )
                    .order_by(artifacts.c.name)
                ).mappings()
            )
            if (
                not files
                or len(files) > 32
                or any(
                    hashlib.sha256(item["content"].encode()).hexdigest() != item["digest"]
                    for item in files
                )
            ):
                raise SafetyError("paid_candidate_bytes_changed")
            return canonical(
                {
                    "instruction": "Review this immutable candidate. Do not run tools.",
                    "candidate_digest": intent.approval.candidate_digest,
                    "files": [{"name": item["name"], "content": item["content"]} for item in files],
                }
            )

    def active(self, intent):
        try:
            with self.db.begin() as conn:
                row = (
                    conn.execute(
                        select(paid_reviews).where(paid_reviews.c.id == intent.invocation_id)
                    )
                    .mappings()
                    .one()
                )
                self.locked(conn, intent, row["session_hash"], row["approved_by"])
                return not row["revoked"]
        except Exception:
            return False

    def runtime_ended(self, intent, *, cleanup_verified):
        """Local cleanup alone cannot release a possibly active/uncertain remote call."""
        if not cleanup_verified:
            raise SafetyError("paid_descendant_cleanup_unverified")
        with self.db.begin() as conn:
            conn.execute(
                select(projects)
                .where(projects.c.id == intent.approval.project_id)
                .with_for_update()
            ).one()
            task = (
                conn.execute(
                    select(tasks).where(tasks.c.id == intent.approval.task_id).with_for_update()
                )
                .mappings()
                .one()
            )
            job = (
                conn.execute(select(jobs).where(jobs.c.task_id == task["id"]).with_for_update())
                .mappings()
                .one()
            )
            row = (
                conn.execute(
                    select(paid_reviews)
                    .where(paid_reviews.c.id == intent.invocation_id)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if (
                row["intent_digest"] != intent.binding
                or task["generation"] != (intent.approval.generation)
                or job["lease_token"] != intent.invocation_id
            ):
                raise SafetyError("paid_runtime_fence_lost")
            terminal = row["state"] in {"LAUNCHING", "SETTLED", "IMPORTED"}
            if terminal:
                state = "TERMINATED" if row["state"] == "LAUNCHING" else row["state"]
                conn.execute(
                    update(paid_reviews)
                    .where(paid_reviews.c.id == row["id"])
                    .values(state=state, termination_confirmed=True)
                )
                conn.execute(
                    update(jobs)
                    .where(jobs.c.id == job["id"])
                    .values(state="FINISHED", lease_token=None, lease_expires_at=None)
                )
                conn.execute(
                    update(tasks)
                    .where(tasks.c.id == task["id"])
                    .values(
                        state="CANCELLED"
                        if job["cancel_requested"]
                        else "FAILED"
                        if state == "TERMINATED"
                        else "READY_FOR_APPROVAL"
                    )
                )
                self.event(conn, intent, "paid_runtime_terminated", {"remote_state": state})
            else:
                conn.execute(
                    update(tasks)
                    .where(tasks.c.id == task["id"])
                    .values(state="NEEDS_RECONCILIATION")
                )
                self.event(conn, intent, "paid_cleanup_remote_unconfirmed", {})
