"""Server-only receipt verification; signatures do not enable or launch providers."""

import base64
import json
import math
import re
from collections.abc import Mapping
from typing import Literal

from authlib.jose import JsonWebKey, JsonWebSignature
from pydantic import Field, model_validator

from intelligenceai.contracts import Contract
from intelligenceai.isolation_contracts import Digest, Identity, LaunchManifest
from intelligenceai.security import SafetyError, digest, require_no_secrets

Control = Literal[
    "provider_capability",
    "credential_broker",
    "provider_egress",
    "resource_limits",
    "cost_accounting",
    "paid_call_authorization",
]
REQUIRED_CONTROLS = frozenset(Control.__args__)
TOKEN_TYPE = "intelligenceai-live-authority+jws"


def unique_object(pairs):
    values = {}
    for name, value in pairs:
        if name in values:
            raise ValueError("duplicate receipt JSON key")
        values[name] = value
    return values


class PaidApprovalBinding(Contract):
    """Trusted server approval snapshot, never browser-supplied execution authority."""

    operation: Literal["paid_model_execution"]
    actor_id: Identity
    project_id: Identity
    task_id: Identity
    generation: int = Field(ge=1)
    manifest_digest: Digest
    candidate_digest: Digest
    evidence_digest: Digest
    policy_digest: Digest
    destination_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    expires_at: float = Field(gt=0, allow_inf_nan=False)

    @property
    def binding(self):
        return digest(self.model_dump(mode="json"))


class ControlStatement(Contract):
    version: Literal[1] = 1
    receipt_id: Identity
    audience: Literal["intelligenceai-trusted-linux-runner-v1"]
    scope: Literal["LIVE_PROVIDER"]
    control: Control
    manifest_digest: Digest
    approval_digest: Digest
    evidence_digest: Digest
    issued_at: float = Field(gt=0, allow_inf_nan=False)
    expires_at: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def time_window(self):
        if self.issued_at >= self.expires_at:
            raise ValueError("invalid receipt window")
        require_no_secrets(self.model_dump(mode="json"))
        return self


class CheckedAuthority(Contract):
    manifest_digest: Digest
    approval_digest: Digest
    receipt_set_digest: Digest
    status: Literal["VERIFIED_SIGNATURES_ONLY"] = "VERIFIED_SIGNATURES_ONLY"
    execution: Literal["BLOCKED"] = "BLOCKED"
    live_model: Literal["NOTRUN"] = "NOTRUN"


class ReceiptVerifier:
    """Keys and control roles must come from operator configuration, not a request.

    No private-key generation, secret loading, HTTP route, durable consumption or
    process-launch API exists here. A trusted runner still needs all those gates.
    """

    def __init__(self, signers: Mapping[str, tuple[Control, dict]]):
        self._signers = {}
        public_roles = {}
        for key_id, (role, public) in signers.items():
            if (
                not re.fullmatch(r"[a-zA-Z0-9._-]{1,80}", key_id)
                or role not in REQUIRED_CONTROLS
                or set(public) - {"kty", "crv", "x", "kid", "use", "key_ops", "alg"}
                or public.get("kty") != "OKP"
                or public.get("crv") != "Ed25519"
            ):
                raise SafetyError("invalid_trusted_receipt_key")
            try:
                encoded = public.get("x")
                if not isinstance(encoded, str) or len(encoded) != 43:
                    raise ValueError("invalid public key length")
                raw = base64.urlsafe_b64decode(encoded + "=")
                if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode().rstrip("=") != encoded:
                    raise ValueError("noncanonical public key")
                if raw in public_roles and public_roles[raw] != role:
                    raise ValueError("public key cannot span control roles")
                key = JsonWebKey.import_key(dict(public))
            except (TypeError, ValueError):
                raise SafetyError("invalid_trusted_receipt_key") from None
            self._signers[key_id] = (role, key)
            public_roles[raw] = role
        self._jws = JsonWebSignature(algorithms=["EdDSA"])

    def verify(
        self,
        manifest: LaunchManifest,
        approval: PaidApprovalBinding,
        tokens: tuple[str, ...],
        *,
        now: float,
    ) -> CheckedAuthority:
        manifest = manifest.revalidate()
        approval = PaidApprovalBinding.model_validate(approval.model_dump())
        if isinstance(now, bool) or not isinstance(now, (float, int)) or not math.isfinite(now):
            raise SafetyError("invalid_authority_clock")
        if manifest.provider == "isolation-probe" or manifest.host_os != "Linux":
            raise SafetyError("live_receipt_scope_required")
        if (
            approval.actor_id != manifest.actor_id
            or approval.project_id != manifest.project_id
            or approval.task_id != manifest.task_id
            or approval.generation != manifest.generation
            or approval.policy_digest != manifest.policy_digest
            or approval.manifest_digest != manifest.binding
            or not now < approval.expires_at <= manifest.deadline
            or not 0 < manifest.deadline - now <= 300
        ):
            raise SafetyError("paid_approval_binding_mismatch")
        if not self._signers:
            raise SafetyError("receipt_verifier_unconfigured")
        if not isinstance(tokens, tuple) or len(tokens) != len(REQUIRED_CONTROLS):
            raise SafetyError("complete_control_receipts_required")

        statements = {}
        receipt_ids = set()
        for token in tokens:
            if not isinstance(token, str) or len(token) > 8192:
                raise SafetyError("invalid_control_receipt")

            def trusted_key(header, _payload):
                signer = self._signers.get(header.get("kid"))
                if (
                    signer is None
                    or set(header) != {"alg", "kid", "typ"}
                    or header.get("alg") != "EdDSA"
                    or header.get("typ") != TOKEN_TYPE
                ):
                    raise SafetyError("untrusted_receipt_signer")
                return signer[1]

            try:
                header_part, _, _ = token.split(".")
                header_bytes = base64.urlsafe_b64decode(header_part + "=" * (-len(header_part) % 4))
                json.loads(header_bytes, object_pairs_hook=unique_object)
                signed = self._jws.deserialize_compact(token, trusted_key)
                statement = ControlStatement.model_validate(
                    json.loads(signed["payload"], object_pairs_hook=unique_object)
                )
                role = self._signers[signed["header"]["kid"]][0]
            except Exception:
                # Never include attacker-supplied token/header/payload or library errors.
                raise SafetyError("invalid_control_receipt") from None
            if (
                role != statement.control
                or statement.control in statements
                or statement.receipt_id in receipt_ids
                or statement.manifest_digest != manifest.binding
                or statement.approval_digest != approval.binding
                or not statement.issued_at <= now < statement.expires_at
                or statement.expires_at > approval.expires_at
            ):
                raise SafetyError("control_receipt_binding_mismatch")
            statements[statement.control] = statement.model_dump(mode="json")
            receipt_ids.add(statement.receipt_id)
        return CheckedAuthority(
            manifest_digest=manifest.binding,
            approval_digest=approval.binding,
            receipt_set_digest=digest(statements),
        )
