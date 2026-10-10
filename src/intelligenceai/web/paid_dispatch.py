"""Private request-to-worker dispatch. External signers; no key or credential loader."""

import base64
import json
from typing import Protocol

from pydantic import Field
from sqlalchemy import insert, select, update

from intelligenceai.contracts import Contract
from intelligenceai.isolation_contracts import (
    Digest,
    InvocationBudget,
    LaunchManifest,
    NetworkPolicy,
    PinnedRoot,
)
from intelligenceai.security import SafetyError, canonical, digest, require_no_secrets
from intelligenceai.web.claude_contracts import ClaudeProfile, PaidReviewIntent
from intelligenceai.web.live_authority import (
    REQUIRED_CONTROLS,
    Control,
    ControlStatement,
    PaidApprovalBinding,
    ReceiptVerifier,
    unique_object,
)
from intelligenceai.web.paid_admission import PaidAdmission
from intelligenceai.web.paid_store import PaidLedger
from intelligenceai.web.store import now, paid_dispatches, paid_requests, paid_reviews, uid


class ControlFact(Contract):
    """Operator-attested evidence, not a readiness inferred from file existence."""

    evidence_digest: Digest
    issued_at: float = Field(gt=0, allow_inf_nan=False)
    expires_at: float = Field(gt=0, allow_inf_nan=False)


class DispatchRuntime(Contract):
    """Independent private configuration. Never populated from a browser request."""

    runner_digest: Digest
    workspace: PinnedRoot
    egress_digest: Digest


class ReceiptIssuer(Protocol):
    def issue(self, statement: ControlStatement) -> str:
        """Return an exact JWS using an already configured external signing authority."""
        ...


def worker_descriptor(db, request_id):
    """Load only a reserved durable delivery; launch fencing happens in the worker."""
    with db.connect() as conn:
        row = (
            conn.execute(
                select(paid_dispatches, paid_reviews.c.state, paid_reviews.c.revoked)
                .join(paid_reviews, paid_reviews.c.id == paid_dispatches.c.invocation_id)
                .where(paid_dispatches.c.request_id == request_id)
            )
            .mappings()
            .first()
        )
        if row is None or row["state"] != "RESERVED" or row["revoked"]:
            raise SafetyError("paid_delivery_not_reserved_no_replay")
        descriptor = row["descriptor"]
        if digest(descriptor) != row["descriptor_digest"]:
            raise SafetyError("paid_delivery_descriptor_changed")
        return descriptor


def run_descriptor(runner, descriptor, cancel, *, reserved):
    """Both operator CLI paths enter the same existing gated Claude runner."""
    if set(descriptor) != {"manifest", "profile", "intent", "tokens", "session_hash"}:
        raise SafetyError("invalid_operator_descriptor")
    manifest = LaunchManifest.model_validate_json(canonical(descriptor["manifest"]))
    profile = ClaudeProfile.model_validate_json(canonical(descriptor["profile"]))
    intent = PaidReviewIntent.model_validate_json(canonical(descriptor["intent"]))
    return runner.run(
        manifest,
        profile,
        intent,
        tuple(descriptor["tokens"]),
        runner.ledger.review_prompt(intent),
        session_hash=descriptor["session_hash"],
        approved_by=intent.approved_by,
        cancel=cancel,
        reserved=reserved,
    )


class PaidDispatcher:
    def __init__(self, db, verifier: ReceiptVerifier, issuer: ReceiptIssuer | None):
        self.db, self.verifier, self.issuer = db, verifier, issuer
        self.admission, self.ledger = PaidAdmission(db), PaidLedger(db)

    def current(self, conn, request_id):
        # Read identity only; then take the shared project lock before mutable rows.
        identity = (
            conn.execute(select(paid_requests).where(paid_requests.c.id == request_id))
            .mappings()
            .first()
        )
        if identity is None:
            raise SafetyError("paid_dispatch_request_missing")
        project, task = self.admission.current(
            conn,
            identity["actor_id"],
            identity["project_id"],
            identity["task_id"],
            identity["session_hash"],
        )
        row = (
            conn.execute(
                select(paid_requests).where(paid_requests.c.id == request_id).with_for_update()
            )
            .mappings()
            .one()
        )
        _, profile = self.admission.profile(conn, row["project_id"], row["profile_id"])
        quote = row["quote"]
        expected = {
            "actor_id": row["actor_id"],
            "project_id": row["project_id"],
            "task_id": row["task_id"],
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
            "expires_at": quote.get("expires_at"),
        }
        if (
            row["state"] != "REQUESTED"
            or quote != expected
            or digest(quote) != row["quote_digest"]
            or quote["expires_at"] <= now()
        ):
            raise SafetyError("paid_dispatch_consent_changed")
        self.admission.budget(conn, row["project_id"], profile)
        return dict(row), profile

    def result(self, request_id):
        with self.db.connect() as conn:
            row = (
                conn.execute(
                    select(paid_dispatches.c.invocation_id, paid_reviews.c.state)
                    .join(paid_reviews, paid_reviews.c.id == paid_dispatches.c.invocation_id)
                    .where(paid_dispatches.c.request_id == request_id)
                )
                .mappings()
                .first()
            )
            return {"request_id": request_id, **row} if row else None

    def prepare(self, request_id, runtime: DispatchRuntime, facts: dict[Control, ControlFact]):
        # A committed delivery is the receipt for a lost response, even after launch.
        previous = self.result(request_id)
        if previous:
            return previous
        if self.issuer is None:
            raise SafetyError("paid_external_signer_unconfigured")
        runtime = DispatchRuntime.model_validate(runtime.model_dump())
        controls = REQUIRED_CONTROLS - {"paid_call_authorization"}
        if set(facts) != controls:
            raise SafetyError("paid_operator_control_evidence_required")
        facts = {
            name: ControlFact.model_validate(value.model_dump()) for name, value in facts.items()
        }
        with self.db.begin() as conn:
            row, profile = self.current(conn, request_id)
        q = row["quote"]
        expiry = float(min(q["expires_at"], *(fact.expires_at for fact in facts.values())))
        issued = float(now())
        if not issued < expiry or any(
            not f.issued_at <= issued < f.expires_at for f in facts.values()
        ):
            raise SafetyError("paid_operator_control_evidence_expired")
        approval = PaidApprovalBinding(
            operation="paid_model_execution",
            actor_id=row["actor_id"],
            project_id=row["project_id"],
            task_id=row["task_id"],
            generation=q["generation"],
            manifest_digest="0" * 64,
            candidate_digest=q["candidate_digest"],
            evidence_digest=q["evidence_digest"],
            policy_digest=q["policy_digest"],
            destination_id=q["destination_id"],
            expires_at=expiry,
        )
        intent = PaidReviewIntent(
            invocation_id=request_id,
            approved_by=row["actor_id"],
            approval=approval,
            profile_digest=profile.binding,
            prompt_digest="0" * 64,
            budget_microusd=q["cost_ceiling_microusd"],
        )
        prompt = self.ledger.review_prompt(intent)
        require_no_secrets(prompt)
        if len(prompt.encode()) > 128 * 1024:
            raise SafetyError("paid_prompt_limit")
        prompt_digest = digest(prompt)
        manifest = LaunchManifest(
            invocation_id=request_id,
            task_id=row["task_id"],
            project_id=row["project_id"],
            actor_id=row["actor_id"],
            generation=q["generation"],
            provider="claude",
            model=profile.model,
            effort=profile.effort,
            mode="read_only",
            host_os="Linux",
            backend="linux-bwrap-claude-relay-v1",
            backend_binary_digest=profile.backend_digest,
            vendor_binary_digest=profile.cli_digest,
            runner_digest=runtime.runner_digest,
            policy_digest=q["policy_digest"],
            image=profile.image,
            workspace=runtime.workspace,
            network=NetworkPolicy(
                provider_hosts=("api.anthropic.com",), enforcement_digest=runtime.egress_digest
            ),
            overlay_digest=digest(
                {
                    "profile": profile.binding,
                    "prompt": prompt_digest,
                    "budget": intent.budget_microusd,
                    "approved_by": intent.approved_by,
                }
            ),
            caller_context_digest=digest(
                {
                    "actor_id": row["actor_id"],
                    "project_id": row["project_id"],
                    "session_hash": row["session_hash"],
                }
            ),
            deadline=expiry,
            budget=InvocationBudget(max_invocations=1, max_cost_microusd=intent.budget_microusd),
        )
        approval = approval.model_copy(update={"manifest_digest": manifest.binding})
        intent = intent.model_copy(update={"approval": approval, "prompt_digest": prompt_digest})
        statements = []
        tokens = []
        for name in sorted(REQUIRED_CONTROLS):
            statement = ControlStatement(
                receipt_id=uid(),
                audience="intelligenceai-trusted-linux-runner-v1",
                scope="LIVE_PROVIDER",
                control=name,
                manifest_digest=manifest.binding,
                approval_digest=approval.binding,
                evidence_digest=row["quote_digest"]
                if name == "paid_call_authorization"
                else facts[name].evidence_digest,
                issued_at=issued if name == "paid_call_authorization" else facts[name].issued_at,
                expires_at=expiry,
            )
            statements.append(statement)
            try:
                tokens.append(self.issuer.issue(statement))
            except Exception:
                raise SafetyError("paid_receipt_issuer_unavailable") from None
        checked = self.verifier.verify(manifest, approval, tuple(tokens), now=now())
        for token, statement in zip(tokens, statements, strict=True):
            # The external issuer cannot replace any evidence or signed scope field.
            try:
                payload = token.split(".")[1]
                actual = json.loads(
                    base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)),
                    object_pairs_hook=unique_object,
                )
            except Exception:
                raise SafetyError("paid_issuer_statement_changed") from None
            if actual != statement.model_dump(mode="json"):
                raise SafetyError("paid_issuer_statement_changed")
        descriptor = {
            "manifest": manifest.model_dump(mode="json"),
            "profile": profile.model_dump(mode="json"),
            "intent": intent.model_dump(mode="json"),
            "tokens": tokens,
            "session_hash": row["session_hash"],
        }
        # Signers are called outside locks. Recheck every binding immediately before
        # atomically consuming consent, holding the budget and recording delivery.
        with self.db.begin() as conn:
            fresh, current_profile = self.current(conn, request_id)
            if fresh != row or current_profile.binding != profile.binding:
                raise SafetyError("paid_dispatch_snapshot_changed")
            checked = self.verifier.verify(manifest, approval, tuple(tokens), now=now())
            self.ledger.reserve_in(
                conn,
                intent,
                profile,
                session_hash=row["session_hash"],
                approved_by=intent.approved_by,
                receipt_digest=checked.receipt_set_digest,
            )
            conn.execute(
                update(paid_requests)
                .where(paid_requests.c.id == request_id)
                .values(state="DISPATCHED")
            )
            conn.execute(
                insert(paid_dispatches).values(
                    request_id=request_id,
                    invocation_id=intent.invocation_id,
                    descriptor=descriptor,
                    descriptor_digest=digest(descriptor),
                    quote_digest=row["quote_digest"],
                    created_at=now(),
                )
            )
            self.ledger.event(conn, intent, "paid_request_dispatched", {"request_id": request_id})
        return self.result(request_id)
