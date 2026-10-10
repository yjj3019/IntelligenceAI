"""Ephemeral signing keys verify contracts, never real broker/OS/model success."""

import base64
import json
from uuid import uuid4

import pytest

pytest.importorskip("authlib")

from authlib.jose import JsonWebKey, JsonWebSignature
from pydantic import ValidationError

from intelligenceai.isolation_contracts import (
    InvocationBudget,
    LaunchManifest,
    NetworkPolicy,
    PinnedRoot,
)
from intelligenceai.security import SafetyError
from intelligenceai.web.live_authority import (
    REQUIRED_CONTROLS,
    TOKEN_TYPE,
    ControlStatement,
    PaidApprovalBinding,
    ReceiptVerifier,
)

NOW = 1000.0


@pytest.fixture
def authority(tmp_path):
    manifest = LaunchManifest(
        invocation_id=str(uuid4()),
        task_id=str(uuid4()),
        project_id=str(uuid4()),
        actor_id=str(uuid4()),
        generation=1,
        provider="codex",
        model="fixture-model",
        effort=None,
        mode="read_only",
        host_os="Linux",
        backend="linux-bwrap-offline-v1",
        backend_binary_digest="a" * 64,
        vendor_binary_digest="b" * 64,
        runner_digest="c" * 64,
        policy_digest="d" * 64,
        image=PinnedRoot(path=str(tmp_path), tree_digest="e" * 64),
        workspace=PinnedRoot(path=str(tmp_path), tree_digest="f" * 64),
        network=NetworkPolicy(),
        overlay_digest="a" * 64,
        caller_context_digest="b" * 64,
        deadline=1060.0,
        budget=InvocationBudget(max_invocations=1, max_cost_microusd=1),
    )
    approval = PaidApprovalBinding(
        operation="paid_model_execution",
        actor_id=manifest.actor_id,
        project_id=manifest.project_id,
        task_id=manifest.task_id,
        generation=manifest.generation,
        manifest_digest=manifest.binding,
        candidate_digest="a" * 64,
        evidence_digest="b" * 64,
        policy_digest=manifest.policy_digest,
        destination_id="private-review",
        expires_at=1030.0,
    )
    keys = {
        role: JsonWebKey.generate_key("OKP", "Ed25519", is_private=True)
        for role in REQUIRED_CONTROLS
    }
    verifier = ReceiptVerifier({role: (role, key.as_dict()) for role, key in keys.items()})
    statements = {
        role: ControlStatement(
            receipt_id=str(uuid4()),
            audience="intelligenceai-trusted-linux-runner-v1",
            scope="LIVE_PROVIDER",
            control=role,
            manifest_digest=manifest.binding,
            approval_digest=approval.binding,
            evidence_digest="c" * 64,
            issued_at=999.0,
            expires_at=1020.0,
        )
        for role in REQUIRED_CONTROLS
    }

    def signed(values=statements, *, header=None):
        return tuple(
            JsonWebSignature(algorithms=["EdDSA"])
            .serialize_compact(
                header or {"alg": "EdDSA", "kid": role, "typ": TOKEN_TYPE},
                value.model_dump_json().encode(),
                keys[role],
            )
            .decode()
            for role, value in values.items()
        )

    return manifest, approval, verifier, statements, signed, keys


def test_signature_control_does_not_enable_or_spawn(authority, monkeypatch):
    manifest, approval, verifier, _, signed, _ = authority
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda *args, **kwargs: pytest.fail("receipt verifier spawned a process"),
    )
    result = verifier.verify(manifest, approval, signed(), now=NOW)
    reverse = verifier.verify(manifest, approval, tuple(reversed(signed())), now=NOW)
    assert result.receipt_set_digest == reverse.receipt_set_digest
    assert result.status == "VERIFIED_SIGNATURES_ONLY"
    assert result.execution == "BLOCKED" and result.live_model == "NOTRUN"


@pytest.mark.parametrize(
    "field",
    [
        "actor_id",
        "project_id",
        "task_id",
        "generation",
        "policy_digest",
        "manifest_digest",
        "expires_at",
    ],
)
def test_paid_approval_cannot_cross_binding(authority, field):
    manifest, approval, verifier, _, signed, _ = authority
    value = (
        2
        if field == "generation"
        else NOW
        if field == "expires_at"
        else (str(uuid4()) if field.endswith("_id") else "f" * 64)
    )
    with pytest.raises(SafetyError, match="paid_approval_binding_mismatch"):
        verifier.verify(manifest, approval.model_copy(update={field: value}), signed(), now=NOW)


@pytest.mark.parametrize(
    "field",
    ["control", "manifest_digest", "approval_digest", "issued_at", "expires_at", "receipt_id"],
)
def test_signed_wrong_role_binding_expiry_or_replay_is_rejected(authority, field):
    manifest, approval, verifier, statements, signed, _ = authority
    role, other = list(statements)[:2]
    replacement = {
        "control": other,
        "manifest_digest": "f" * 64,
        "approval_digest": "e" * 64,
        "issued_at": NOW + 1,
        "expires_at": NOW,
        "receipt_id": statements[other].receipt_id,
    }[field]
    altered = statements | {role: statements[role].model_copy(update={field: replacement})}
    with pytest.raises(SafetyError, match="control_receipt_binding_mismatch"):
        verifier.verify(manifest, approval, signed(altered), now=NOW)


def test_complete_distinct_receipts_and_trusted_keys_required(authority):
    manifest, approval, verifier, _, signed, _ = authority
    tokens = signed()
    with pytest.raises(SafetyError, match="receipt_verifier_unconfigured"):
        ReceiptVerifier({}).verify(manifest, approval, tokens, now=NOW)
    with pytest.raises(SafetyError, match="complete_control_receipts_required"):
        verifier.verify(manifest, approval, tokens[:-1], now=NOW)
    with pytest.raises(SafetyError, match="control_receipt_binding_mismatch"):
        verifier.verify(manifest, approval, (tokens[0],) * 6, now=NOW)
    with pytest.raises(SafetyError, match="invalid_control_receipt"):
        verifier.verify(
            manifest,
            approval,
            signed(
                header={
                    "alg": "EdDSA",
                    "kid": "untrusted",
                    "typ": TOKEN_TYPE,
                }
            ),
            now=NOW,
        )


def test_signature_tampering_and_remote_key_header_rejected(authority):
    manifest, approval, verifier, _, signed, _ = authority
    tokens = signed()
    head, payload, signature = tokens[0].split(".")
    statement = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    statement["evidence_digest"] = "f" * 64
    changed = base64.urlsafe_b64encode(json.dumps(statement).encode()).decode().rstrip("=")
    with pytest.raises(SafetyError, match="invalid_control_receipt"):
        verifier.verify(
            manifest, approval, (f"{head}.{changed}.{signature}",) + tokens[1:], now=NOW
        )
    role = next(iter(authority[3]))
    with pytest.raises(SafetyError, match="invalid_control_receipt"):
        verifier.verify(
            manifest,
            approval,
            signed(
                header={
                    "alg": "EdDSA",
                    "kid": role,
                    "typ": TOKEN_TYPE,
                    "jku": "https://invalid.example",
                }
            ),
            now=NOW,
        )


@pytest.mark.parametrize("now", [float("nan"), float("inf"), float("-inf"), True])
def test_invalid_clock_rejected(authority, now):
    manifest, approval, verifier, _, signed, _ = authority
    with pytest.raises(SafetyError, match="invalid_authority_clock"):
        verifier.verify(manifest, approval, signed(), now=now)


def test_private_keys_and_offline_scope_cannot_become_live_authority(authority):
    manifest, approval, verifier, _, signed, keys = authority
    role = next(iter(keys))
    with pytest.raises(SafetyError, match="invalid_trusted_receipt_key"):
        ReceiptVerifier({role: (role, keys[role].as_dict(is_private=True))})
    with pytest.raises(SafetyError, match="live_receipt_scope_required"):
        verifier.verify(
            manifest.model_copy(update={"provider": "isolation-probe"}), approval, signed(), now=NOW
        )
    with pytest.raises(ValidationError):
        PaidApprovalBinding.model_validate(approval.model_dump() | {"enable_live": True})
    with pytest.raises(ValidationError):
        PaidApprovalBinding.model_validate(approval.model_dump(exclude={"operation"}))
    with pytest.raises(ValidationError):
        PaidApprovalBinding.model_validate(approval.model_dump() | {"operation": "private_review"})


def test_signed_duplicate_json_and_symmetric_algorithm_are_rejected(authority):
    manifest, approval, verifier, statements, signed, keys = authority
    role = next(iter(statements))
    payload = statements[role].model_dump_json()
    duplicate = payload[:-1] + ',"control":' + json.dumps(role) + "}"
    header = {"alg": "EdDSA", "kid": role, "typ": TOKEN_TYPE}
    token = (
        JsonWebSignature(algorithms=["EdDSA"])
        .serialize_compact(header, duplicate.encode(), keys[role])
        .decode()
    )
    remaining = signed({name: value for name, value in statements.items() if name != role})
    with pytest.raises(SafetyError, match="invalid_control_receipt"):
        verifier.verify(manifest, approval, (token,) + remaining, now=NOW)
    token = (
        JsonWebSignature(algorithms=["HS256"])
        .serialize_compact(
            header | {"alg": "HS256"}, payload.encode(), keys[role].as_dict()["x"].encode()
        )
        .decode()
    )
    with pytest.raises(SafetyError, match="invalid_control_receipt"):
        verifier.verify(manifest, approval, (token,) + remaining, now=NOW)


@pytest.mark.parametrize("field", ["candidate_digest", "evidence_digest", "destination_id"])
def test_approval_content_drift_invalidates_existing_signatures(authority, field):
    manifest, approval, verifier, _, signed, _ = authority
    value = "other-destination" if field == "destination_id" else "f" * 64
    with pytest.raises(SafetyError, match="control_receipt_binding_mismatch"):
        verifier.verify(manifest, approval.model_copy(update={field: value}), signed(), now=NOW)


def test_receipt_cannot_outlive_approval_or_long_manifest(authority):
    manifest, approval, verifier, statements, signed, _ = authority
    role = next(iter(statements))
    changed = statements | {
        role: statements[role].model_copy(update={"expires_at": approval.expires_at + 1})
    }
    with pytest.raises(SafetyError, match="control_receipt_binding_mismatch"):
        verifier.verify(manifest, approval, signed(changed), now=NOW)
    manifest = manifest.model_copy(update={"deadline": NOW + 301})
    approval = approval.model_copy(update={"manifest_digest": manifest.binding})
    with pytest.raises(SafetyError, match="paid_approval_binding_mismatch"):
        verifier.verify(manifest, approval, signed(), now=NOW)


def test_one_public_key_cannot_sign_different_control_roles(authority):
    keys = authority[-1]
    first, second = list(keys)[:2]
    with pytest.raises(SafetyError, match="invalid_trusted_receipt_key"):
        ReceiptVerifier(
            {first: (first, keys[first].as_dict()), second: (second, keys[first].as_dict())}
        )
