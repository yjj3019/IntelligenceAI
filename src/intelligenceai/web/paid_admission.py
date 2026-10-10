"""Session-bound consent and one-time durable requests; never a provider launcher."""

from pydantic import Field
from sqlalchemy import insert, select, update

from intelligenceai.security import digest
from intelligenceai.web.claude_contracts import ClaudeProfile
from intelligenceai.web.contracts import Input
from intelligenceai.web.service import Problem, Service
from intelligenceai.web.store import (
    jobs,
    now,
    paid_budgets,
    paid_profiles,
    paid_requests,
    paid_reviews,
    sessions,
    tasks,
    uid,
)


class QuoteInput(Input):
    profile_id: str = Field(pattern=r"^[a-f0-9-]{36}$")


class ConsentInput(Input):
    request_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    quote_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


BLOCKERS = [
    "signed_control_receipts_required",
    "verified_linux_runtime_required",
    "provider_credential_confirmation_required",
]


class PaidAdmission:
    def __init__(self, db):
        self.db, self.service = db, Service(db)

    @staticmethod
    def public(row):
        return {
            "id": row["id"],
            "state": "REQUESTED"
            if row["state"] == "DISPATCHED"
            else row["state"]
            if row["state"] in {"QUOTED", "APPROVED", "REQUESTED"}
            else "STALE",
            "quote": row["quote"],
            "quote_digest": row["quote_digest"],
            "profile_id": row["profile_id"],
            "live_model": "NOTRUN",
        }

    def current(self, conn, actor, project_id, task_id, session_hash):
        project, _ = self.service.authorize(conn, actor, project_id, {"owner"}, lock=True)
        task = self.service.task_row(conn, project_id, task_id)
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
            or (session["data"].get("user_id") != actor)
        ):
            raise Problem(403, "paid_session_changed")
        if (
            task["state"] != "READY_FOR_APPROVAL"
            or not task["evidence_verified"]
            or (
                not task["candidate_digest"]
                or not task["evidence_digest"]
                or job["cancel_requested"]
                or job["lease_token"] is not None
                or task["generation"] != job["generation"]
            )
        ):
            raise Problem(409, "paid_candidate_unavailable")
        self.service.check_snapshot(conn, task)
        return project, task

    @staticmethod
    def profile(conn, project_id, profile_id):
        row = (
            conn.execute(
                select(paid_profiles).where(
                    paid_profiles.c.id == profile_id,
                    paid_profiles.c.project_id == project_id,
                    paid_profiles.c.active.is_(True),
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise Problem(409, "paid_operator_profile_required")
        return row, ClaudeProfile.model_validate(row["profile"])

    @staticmethod
    def budget(conn, project_id, profile):
        budget = (
            conn.execute(
                select(paid_budgets)
                .where(paid_budgets.c.project_id == project_id)
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
                or budget["limit_microusd"] - budget["held_microusd"] - budget["spent_microusd"]
                < profile.reservation
            )
        ):
            raise Problem(409, "paid_project_budget_unavailable")

    def status(self, actor, project_id, task_id, session_hash):
        with self.db.connect() as conn:
            project, role = self.service.authorize(conn, actor, project_id)
            task = self.service.task_row(conn, project_id, task_id)
            profiles = []
            for row in conn.execute(
                select(paid_profiles).where(
                    paid_profiles.c.project_id == project_id, paid_profiles.c.active.is_(True)
                )
            ).mappings():
                profile = ClaudeProfile.model_validate(row["profile"])
                profiles.append(
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "provider": "claude",
                        "model": profile.model,
                        "effort": profile.effort,
                        "max_calls": 1,
                        "currency": "USD",
                        "cost_ceiling_microusd": profile.reservation,
                    }
                )
            rows = conn.execute(
                select(paid_requests)
                .where(
                    paid_requests.c.project_id == project_id,
                    paid_requests.c.task_id == task_id,
                    paid_requests.c.actor_id == actor,
                )
                .order_by(paid_requests.c.created_at.desc(), paid_requests.c.id)
                .limit(20)
            ).mappings()
            requests = []
            for row in rows:
                quote = row["quote"]
                value = self.public(row)
                review = conn.execute(
                    select(paid_reviews.c.state).where(
                        paid_reviews.c.id == row["id"],
                        paid_reviews.c.project_id == project_id,
                        paid_reviews.c.task_id == task_id,
                        paid_reviews.c.actor_id == actor,
                        paid_reviews.c.generation == quote["generation"],
                    )
                ).scalar_one_or_none()
                value["worker_state"] = review
                value["live_model"] = (
                    "NOTRUN"
                    if review is None or review in {"RESERVED", "TERMINATED"}
                    else "REQUEST_STARTED"
                    if review == "STARTED"
                    else "RESULT_RECEIVED"
                    if review in {"SETTLED", "IMPORTED"}
                    else "UNKNOWN"
                )
                active_profile = (
                    conn.execute(
                        select(paid_profiles).where(
                            paid_profiles.c.id == row["profile_id"],
                            paid_profiles.c.active.is_(True),
                        )
                    )
                    .mappings()
                    .first()
                )
                if (
                    role != "owner"
                    or row["session_hash"] != session_hash
                    or quote["expires_at"] <= now()
                    or (
                        quote["generation"] != task["generation"]
                        or task["state"] != "READY_FOR_APPROVAL"
                        or not task["evidence_verified"]
                        or quote["candidate_digest"] != task["candidate_digest"]
                        or quote["evidence_digest"] != task["evidence_digest"]
                        or quote["policy_digest"] != project["policy_digest"]
                        or digest(quote) != row["quote_digest"]
                    )
                ):
                    value["state"] = "STALE"
                if (
                    not active_profile
                    or ClaudeProfile.model_validate(active_profile["profile"]).binding
                    != quote["profile_digest"]
                ):
                    value["state"] = "STALE"
                requests.append(value)
            return {
                "profiles": profiles,
                "requests": requests,
                "generation": task["generation"],
                "can_consent": role == "owner",
                "execution_enabled": False,
                "live_model": next(
                    (
                        r["live_model"]
                        for r in requests
                        if r["quote"]["generation"] == task["generation"] and r["worker_state"]
                    ),
                    "NOTRUN",
                ),
                "blockers": ([] if profiles else ["paid_operator_profile_required"]) + BLOCKERS,
            }

    def quote(self, actor, project_id, task_id, key, data, session_hash):
        def operation(conn, _):
            project, task = self.current(conn, actor, project_id, task_id, session_hash)
            _, profile = self.profile(conn, project_id, data.profile_id)
            if profile.policy_digest != project["policy_digest"]:
                raise Problem(409, "paid_quote_changed")
            self.budget(conn, project_id, profile)
            consumed = (
                conn.execute(
                    select(paid_requests.c.id).where(
                        paid_requests.c.task_id == task_id,
                        paid_requests.c.state.in_(["REQUESTED", "DISPATCHED"]),
                    )
                )
                .scalars()
                .all()
            )
            if any(
                conn.execute(
                    select(paid_requests.c.quote).where(paid_requests.c.id == rid)
                ).scalar_one()["generation"]
                == task["generation"]
                for rid in consumed
            ):
                raise Problem(409, "paid_generation_consumed")
            quote = {
                "actor_id": actor,
                "project_id": project_id,
                "task_id": task_id,
                "generation": task["generation"],
                "provider": "claude",
                "model": profile.model,
                "effort": profile.effort,
                "max_calls": 1,
                "currency": "USD",
                "cost_ceiling_microusd": profile.reservation,
                "profile_digest": profile.binding,
                "candidate_digest": task["candidate_digest"],
                "evidence_digest": task["evidence_digest"],
                "policy_digest": project["policy_digest"],
                "destination_id": "private-model-review",
                "expires_at": min(
                    now() + 300,
                    conn.execute(
                        select(sessions.c.expires_at).where(sessions.c.token_hash == session_hash)
                    ).scalar_one(),
                ),
            }
            conn.execute(
                update(paid_requests)
                .where(
                    paid_requests.c.task_id == task_id,
                    paid_requests.c.actor_id == actor,
                    paid_requests.c.state.in_(["QUOTED", "APPROVED"]),
                )
                .values(state="SUPERSEDED")
            )
            row = {
                "id": uid(),
                "project_id": project_id,
                "task_id": task_id,
                "actor_id": actor,
                "session_hash": session_hash,
                "profile_id": data.profile_id,
                "quote": quote,
                "quote_digest": digest(quote),
                "state": "QUOTED",
                "created_at": now(),
            }
            conn.execute(insert(paid_requests).values(**row))
            self.service.record(
                conn,
                project_id,
                actor,
                "paid.quote",
                {"request_id": row["id"], "quote_digest": row["quote_digest"]},
                task_id,
            )
            return self.public(row)

        return self.service.mutate(
            actor,
            project_id,
            key,
            {"paid.quote": data.model_dump(), "task_id": task_id, "session": digest(session_hash)},
            {"owner"},
            operation,
        )

    def transition(self, actor, project_id, task_id, key, data, session_hash, action):
        def operation(conn, _):
            project, task = self.current(conn, actor, project_id, task_id, session_hash)
            row = (
                conn.execute(
                    select(paid_requests)
                    .where(
                        paid_requests.c.id == data.request_id,
                        paid_requests.c.project_id == project_id,
                        paid_requests.c.task_id == task_id,
                        paid_requests.c.actor_id == actor,
                    )
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if row is None:
                raise Problem(404, "paid_request_not_found")
            _, profile = self.profile(conn, project_id, row["profile_id"])
            quote = row["quote"]
            if (
                row["session_hash"] != session_hash
                or row["quote_digest"] != data.quote_digest
                or (
                    digest(quote) != data.quote_digest
                    or quote["expires_at"] <= now()
                    or quote["generation"] != task["generation"]
                    or quote["candidate_digest"] != task["candidate_digest"]
                    or quote["evidence_digest"] != task["evidence_digest"]
                    or quote["policy_digest"] != project["policy_digest"]
                    or quote["profile_digest"] != profile.binding
                )
            ):
                raise Problem(409, "paid_quote_changed")
            self.budget(conn, project_id, profile)
            expected, state = (
                ("QUOTED", "APPROVED") if action == "approve" else ("APPROVED", "REQUESTED")
            )
            if row["state"] != expected:
                raise Problem(409, "paid_request_consumed_or_unapproved")
            if state == "REQUESTED":
                for other in conn.execute(
                    select(paid_requests).where(
                        paid_requests.c.task_id == task_id,
                        paid_requests.c.state.in_(["REQUESTED", "DISPATCHED"]),
                    )
                ).mappings():
                    if other["quote"]["generation"] == task["generation"]:
                        raise Problem(409, "paid_generation_consumed")
            conn.execute(
                update(paid_requests).where(paid_requests.c.id == row["id"]).values(state=state)
            )
            self.service.record(
                conn,
                project_id,
                actor,
                "paid." + action,
                {
                    "request_id": row["id"],
                    "quote_digest": row["quote_digest"],
                    "state": state,
                    "live_model": "NOTRUN",
                },
                task_id,
            )
            return self.public({**row, "state": state})

        return self.service.mutate(
            actor,
            project_id,
            key,
            {
                "paid." + action: data.model_dump(),
                "task_id": task_id,
                "session": digest(session_hash),
            },
            {"owner"},
            operation,
        )
