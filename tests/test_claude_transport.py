"""No real credential/model calls. Mock provider traffic is not production evidence."""

import base64
import hashlib
import io
import json
import os
import socket
import struct
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

import httpx
from sqlalchemy import create_engine, insert, select, update
from test_approved_vendor import seeded_review
from test_web import fixture as shared_fixture

from intelligenceai.isolation_contracts import (
    InvocationBudget,
    LaunchManifest,
    NetworkPolicy,
    PinnedRoot,
)
from intelligenceai.security import SafetyError, canonical, digest
from intelligenceai.web import claude_runner, paid_store
from intelligenceai.web.claude_bridge import inference_target, receive
from intelligenceai.web.claude_broker import ClaudeBroker, bounded_request, stream_result
from intelligenceai.web.claude_contracts import ClaudeProfile, PaidReviewIntent, claude_argv
from intelligenceai.web.claude_runner import ClaudeReviewRunner, DelegatedCgroup, UnixRelay
from intelligenceai.web.live_authority import PaidApprovalBinding
from intelligenceai.web.paid_store import PaidLedger, paid_budgets, paid_reviews
from intelligenceai.web.store import artifacts, jobs, members, now, projects, sessions, tasks, uid

fixture = shared_fixture


def profile_for(f):
    with f["db"].connect() as conn:
        policy = conn.execute(
            select(projects.c.policy_digest).where(projects.c.id == f["project"])
        ).scalar_one()
    return ClaudeProfile(
        model="claude-fixture-test",
        effort="low",
        image=PinnedRoot(path=str(Path(__file__).resolve().parent), tree_digest="a" * 64),
        backend_digest="b" * 64,
        cli_digest="c" * 64,
        bridge_digest="d" * 64,
        input_token_ceiling=100,
        output_token_limit=10,
        input_price_ceiling=2,
        output_price_ceiling=4,
        pricing_evidence_digest="e" * 64,
        policy_digest=policy,
        memory_bytes=128 * 1024 * 1024,
        pids=8,
        cpu_quota_us=100_000,
        duration_seconds=10,
    )


def reservation(f, *, profile_override=None):
    task_id, _ = seeded_review(f)
    profile = profile_override or profile_for(f)
    with f["db"].connect() as conn:
        task = conn.execute(select(tasks).where(tasks.c.id == task_id)).mappings().one()
        session_hash = conn.execute(select(sessions.c.token_hash)).scalar_one()
    approval = PaidApprovalBinding(
        operation="paid_model_execution",
        actor_id=f["alice"],
        project_id=f["project"],
        task_id=task_id,
        generation=1,
        manifest_digest="f" * 64,
        candidate_digest=task["candidate_digest"],
        evidence_digest=task["evidence_digest"],
        policy_digest=profile.policy_digest,
        destination_id="private-model-review",
        expires_at=float(now() + 120),
    )
    placeholder = PaidReviewIntent(
        invocation_id=uid(),
        approved_by=f["viewer"],
        approval=approval,
        profile_digest=profile.binding,
        prompt_digest="a" * 64,
        budget_microusd=240,
    )
    ledger = PaidLedger(f["db"])
    prompt = ledger.review_prompt(placeholder)
    intent = placeholder.model_copy(update={"prompt_digest": digest(prompt)})
    with f["db"].begin() as conn:
        conn.execute(
            update(members)
            .where(members.c.project_id == f["project"], members.c.user_id == f["viewer"])
            .values(role="approver")
        )
        conn.execute(
            insert(paid_budgets).values(
                project_id=f["project"],
                policy_digest=profile.policy_digest,
                limit_microusd=240,
                held_microusd=0,
                spent_microusd=0,
                expires_at=now() + 3600,
            )
        )
    ledger.reserve(
        intent, profile, session_hash=session_hash, approved_by=f["viewer"], receipt_digest="0" * 64
    )
    return ledger, intent, profile, prompt


def request(profile, prompt):
    return canonical(
        {
            "model": profile.model,
            "max_tokens": 9999,
            "stream": True,
            "messages": [{"role": "user", "content": prompt}],
            "system": [{"type": "text", "text": "Review", "cache_control": {"type": "ephemeral"}}],
            "tools": [],
            "output_config": {"effort": profile.effort},
        }
    ).encode()


def stream(profile, text="FAKE_PROVIDER_TEST_ONLY"):
    frames = [
        (
            "message_start",
            {
                "message": {
                    "id": "msg_fixture",
                    "type": "message",
                    "role": "assistant",
                    "model": profile.model,
                    "content": [],
                    "usage": {"input_tokens": 20, "output_tokens": 1},
                }
            },
        ),
        ("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"index": 0}),
        ("message_delta", {"delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 5}}),
        ("message_stop", {}),
    ]
    return "".join(
        f"event: {name}\ndata: {canonical({'type': name, **value})}\n\n" for name, value in frames
    ).encode()


def stored(f, intent):
    with f["db"].connect() as conn:
        row = (
            conn.execute(select(paid_reviews).where(paid_reviews.c.id == intent.invocation_id))
            .mappings()
            .one()
        )
        budget = conn.execute(select(paid_budgets)).mappings().one()
    return dict(row), dict(budget)


def test_actual_broker_mock_wire_settles_before_private_import_and_no_retry(fixture):
    f = fixture
    ledger, intent, profile, prompt = reservation(f)
    ledger.claim_launch(intent)
    calls = []

    def upstream(req):
        calls.append(req)
        assert str(req.url) == "https://api.anthropic.com/v1/messages"
        assert req.headers["x-api-key"] == "fixture-broker-only"
        body = json.loads(req.content)
        assert body["max_tokens"] == 10
        assert "cache_control" not in body["system"][0]
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=stream(profile)
        )

    broker = ClaudeBroker(
        ledger,
        intent,
        profile,
        lambda: "fixture-broker-only",
        prompt,
        transport=httpx.MockTransport(upstream),
    )
    reply = broker.exchange(request(profile, prompt))
    assert broker.result == "FAKE_PROVIDER_TEST_ONLY"
    row, budget = stored(f, intent)
    assert row["state"] == "SETTLED"
    assert row["result"]["response_digest"] == hashlib.sha256(reply).hexdigest()
    assert budget["held_microusd"] == 0 and budget["spent_microusd"] == 60
    assert "fixture-broker-only" not in canonical(row)
    with pytest.raises(SafetyError):
        broker.exchange(request(profile, prompt))
    assert len(calls) == 1
    with pytest.raises(SafetyError, match="cleanup"):
        ledger.import_review(intent, broker.result, cleanup_verified=False)
    ledger.runtime_ended(intent, cleanup_verified=True)
    ledger.import_review(intent, broker.result, cleanup_verified=True)
    with f["db"].connect() as conn:
        assert (
            conn.execute(
                select(artifacts.c.content).where(artifacts.c.id == intent.invocation_id)
            ).scalar_one()
            == "FAKE_PROVIDER_TEST_ONLY"
        )
    assert stored(f, intent)[0]["state"] == "IMPORTED"
    with pytest.raises(SafetyError):
        ledger.import_review(intent, broker.result, cleanup_verified=True)


@pytest.mark.parametrize(
    "mutation",
    [
        "session",
        "requester",
        "approver",
        "generation",
        "candidate",
        "evidence",
        "policy",
        "cancel",
        "approval",
        "budget",
        "record",
    ],
)
def test_authority_revocation_prevents_http(fixture, mutation):
    f = fixture
    ledger, intent, profile, prompt = reservation(f)
    ledger.claim_launch(intent)
    with f["db"].begin() as conn:
        if mutation == "session":
            conn.execute(update(sessions).values(revoked=True))
        elif mutation in {"requester", "approver"}:
            conn.execute(
                update(members)
                .where(
                    members.c.project_id == f["project"],
                    members.c.user_id == (f["alice"] if mutation == "requester" else f["viewer"]),
                )
                .values(role="viewer")
            )
        elif mutation in {"generation", "candidate", "evidence"}:
            changes = (
                {"generation": 2} if mutation == "generation" else {mutation + "_digest": "1" * 64}
            )
            conn.execute(
                update(tasks).where(tasks.c.id == intent.approval.task_id).values(**changes)
            )
        elif mutation == "policy":
            conn.execute(
                update(projects).where(projects.c.id == f["project"]).values(policy_digest="1" * 64)
            )
        elif mutation == "cancel":
            conn.execute(update(jobs).values(cancel_requested=True))
        elif mutation == "approval":
            conn.execute(update(paid_reviews).values(revoked=True))
        elif mutation == "budget":
            conn.execute(update(paid_budgets).values(expires_at=now() - 1))
        else:
            conn.execute(update(paid_reviews).values(intent_digest="1" * 64))
    calls = []
    broker = ClaudeBroker(
        ledger,
        intent,
        profile,
        lambda: "fixture",
        prompt,
        transport=httpx.MockTransport(lambda req: calls.append(req)),
    )
    with pytest.raises(Exception):
        broker.exchange(request(profile, prompt))
    assert calls == [] and stored(f, intent)[1]["held_microusd"] == 240


@pytest.mark.parametrize(
    "kind",
    [
        "redirect",
        "error",
        "incomplete",
        "transport",
        "unknown_usage",
        "tool",
        "over_ceiling",
        "model",
    ],
)
def test_uncertain_remote_result_keeps_hold_and_cannot_replay(fixture, kind):
    f = fixture
    ledger, intent, profile, prompt = reservation(f)
    ledger.claim_launch(intent)
    calls = []

    def upstream(req):
        calls.append(req)
        if kind == "transport":
            raise httpx.ReadError("do not persist this body", request=req)
        body = stream(profile)
        if kind == "incomplete":
            body = body[: body.rfind(b"event: message_stop")]
        elif kind == "unknown_usage":
            body = body.replace(b'"input_tokens":20', b'"input_tokens":20,"unknown_charge":1')
        elif kind == "tool":
            body = body.replace(b'"type":"text"', b'"type":"tool_use"')
        elif kind == "over_ceiling":
            body = body.replace(b'"input_tokens":20', b'"input_tokens":1000')
        elif kind == "model":
            body = body.replace(profile.model.encode(), b"claude-other-model")
        status = 307 if kind == "redirect" else 500 if kind == "error" else 200
        return httpx.Response(
            status,
            content=body,
            headers={"content-type": "text/event-stream", "location": "http://127.0.0.1/"},
        )

    broker = ClaudeBroker(
        ledger, intent, profile, lambda: "fixture", prompt, transport=httpx.MockTransport(upstream)
    )
    with pytest.raises(SafetyError, match="reconciliation"):
        broker.exchange(request(profile, prompt))
    row, budget = stored(f, intent)
    assert row["state"] == "NEEDS_RECONCILIATION" and row["result"] is None
    assert budget["held_microusd"] == 240 and budget["spent_microusd"] == 0
    with pytest.raises(SafetyError):
        broker.exchange(request(profile, prompt))
    assert len(calls) == 1


def test_logout_after_http_still_accounts_usage_but_prevents_import(fixture):
    f = fixture
    ledger, intent, profile, prompt = reservation(f)
    ledger.claim_launch(intent)

    def upstream(_):
        with f["db"].begin() as conn:
            conn.execute(update(sessions).values(revoked=True))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=stream(profile, "password=fixture"),
        )

    broker = ClaudeBroker(
        ledger, intent, profile, lambda: "fixture", prompt, transport=httpx.MockTransport(upstream)
    )
    broker.exchange(request(profile, prompt))
    assert stored(f, intent)[0]["state"] == "SETTLED"
    assert stored(f, intent)[1]["spent_microusd"] == 60
    with pytest.raises(SafetyError, match="session"):
        ledger.import_review(intent, broker.result, cleanup_verified=True)
    with f["db"].connect() as conn:
        assert (
            conn.execute(select(artifacts).where(artifacts.c.id == intent.invocation_id)).first()
            is None
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "claude-other"),
        ("tools", [{"name": "shell"}]),
        ("stream", False),
        ("max_tokens", True),
        ("thinking", {"type": "enabled"}),
        ("output_config", {"effort": "max"}),
        (
            "messages",
            [
                {
                    "role": "user",
                    "content": [{"type": "image", "source": {"url": "http://169.254.169.254/"}}],
                }
            ],
        ),
    ],
)
def test_attack_input_has_no_upstream_effect(fixture, field, value):
    ledger, intent, profile, prompt = reservation(fixture)
    raw = json.loads(request(profile, prompt))
    raw[field] = value
    with pytest.raises(SafetyError):
        bounded_request(canonical(raw).encode(), profile)
    assert stored(fixture, intent)[0]["state"] == "RESERVED"


def test_prompt_change_duplicate_json_and_stream_terminal_are_rejected(fixture):
    ledger, intent, profile, prompt = reservation(fixture)
    ledger.claim_launch(intent)
    broker = ClaudeBroker(
        ledger,
        intent,
        profile,
        lambda: "fixture",
        prompt,
        transport=httpx.MockTransport(lambda _: pytest.fail("unexpected HTTP")),
    )
    with pytest.raises(SafetyError, match="prompt"):
        broker.exchange(request(profile, "different input"))
    with pytest.raises(SafetyError, match="json"):
        bounded_request(b'{"model":"a","model":"b"}', profile)
    with pytest.raises(SafetyError):
        stream_result(stream(profile) + stream(profile), profile)


@pytest.mark.parametrize(
    "target,accepted",
    [
        ("/v1/messages", True),
        ("/v1/messages?beta=true", True),
        ("/v1/messages?beta=false", False),
        ("/v1/messages?beta=true&beta=true", False),
        ("/v1/messages?beta=true&url=https://other", False),
        ("https://api.anthropic.com/v1/messages", False),
        ("//other/v1/messages", False),
        ("/v1/messages#fragment", False),
        ("/v1/messages?%62eta=true", False),
        ("/v1/messages?", False),
    ],
)
def test_fixed_inference_target_and_only_native_beta_query(target, accepted):
    assert inference_target(target) is accepted


def thinking_stream(profile, *, malformed=None):
    frames = stream(profile).decode().split("\n\n")
    extra = [
        (
            "content_block_start",
            {"index": 1, "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
        ),
        (
            "content_block_delta",
            {
                "index": 1,
                "delta": {"type": "thinking_delta", "thinking": "fixture-private-reasoning"},
            },
        ),
        (
            "content_block_delta",
            {
                "index": 1,
                "delta": {"type": "signature_delta", "signature": "fixture-opaque-signature"},
            },
        ),
        ("content_block_stop", {"index": 1}),
        (
            "content_block_start",
            {
                "index": 2,
                "content_block": {"type": "redacted_thinking", "data": "fixture-opaque-redaction"},
            },
        ),
        ("content_block_stop", {"index": 2}),
    ]
    if malformed == "missing_signature":
        extra.pop(2)
    wire = (
        [frames[0]]
        + [f"event: {name}\ndata: {canonical({'type': name, **value})}" for name, value in extra]
        + frames[1:4]
    )
    for value in (3, 5):
        delta = {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": value},
        }
        if malformed == "decreasing_usage" and value == 5:
            delta["usage"]["output_tokens"] = 2
        wire.append("event: message_delta\ndata: " + canonical(delta))
    wire.append(frames[5])
    return ("\n\n".join(wire) + "\n\n").encode()


def test_adaptive_thinking_and_cumulative_usage_settle_without_storing_reasoning(fixture):
    ledger, intent, profile, prompt = reservation(fixture)
    ledger.claim_launch(intent)
    calls = []

    def upstream(req):
        calls.append(req)
        assert json.loads(req.content)["thinking"] == {"type": "adaptive"}
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=thinking_stream(profile)
        )

    broker = ClaudeBroker(
        ledger, intent, profile, lambda: "fixture", prompt, transport=httpx.MockTransport(upstream)
    )
    raw = json.loads(request(profile, prompt))
    raw["thinking"] = {"type": "adaptive"}
    broker.exchange(canonical(raw).encode())
    assert len(calls) == 1 and broker.result == "FAKE_PROVIDER_TEST_ONLY"
    row, budget = stored(fixture, intent)
    assert row["result"]["usage"]["output_tokens"] == 5
    assert budget["held_microusd"] == 0 and budget["spent_microusd"] == 60
    ledger.runtime_ended(intent, cleanup_verified=True)
    ledger.import_review(intent, broker.result, cleanup_verified=True)
    with fixture["db"].connect() as conn:
        contents = conn.execute(
            select(artifacts.c.content).where(artifacts.c.kind == "review")
        ).scalar_one()
    assert "reasoning" not in contents and "signature" not in contents


@pytest.mark.parametrize("malformed", ["missing_signature", "decreasing_usage"])
def test_invalid_thinking_or_cumulative_usage_keeps_uncertain_hold(fixture, malformed):
    ledger, intent, profile, prompt = reservation(fixture)
    ledger.claim_launch(intent)
    broker = ClaudeBroker(
        ledger,
        intent,
        profile,
        lambda: "fixture",
        prompt,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=thinking_stream(profile, malformed=malformed),
            )
        ),
    )
    with pytest.raises(SafetyError):
        broker.exchange(request(profile, prompt))
    row, budget = stored(fixture, intent)
    assert row["state"] == "NEEDS_RECONCILIATION"
    assert budget["held_microusd"] == 240 and budget["spent_microusd"] == 0


@pytest.mark.parametrize("point", ["reserved_cancel", "pre_http_cleanup"])
def test_proven_no_send_refunds_once_and_new_generation_requires_fresh_approval(fixture, point):
    f = fixture
    ledger, intent, profile, _ = reservation(f)
    initial, _ = stored(f, intent)
    if point == "reserved_cancel":
        assert (
            f["service"].cancel(f["alice"], f["project"], intent.approval.task_id, uid())["state"]
            == "CANCELLED"
        )
        f["service"].cancel(f["alice"], f["project"], intent.approval.task_id, uid())
    else:
        ledger.claim_launch(intent)
        with pytest.raises(SafetyError):
            ledger.runtime_ended(intent, cleanup_verified=False)
        assert stored(f, intent)[1]["held_microusd"] == 240
        ledger.runtime_ended(intent, cleanup_verified=True)
        with pytest.raises(SafetyError):
            ledger.runtime_ended(intent, cleanup_verified=True)
    row, budget = stored(f, intent)
    assert row["state"] == "TERMINATED" and row["termination_confirmed"]
    assert budget["held_microusd"] == budget["spent_microusd"] == 0
    with pytest.raises(SafetyError):
        ledger.reserve(
            intent,
            profile,
            session_hash=initial["session_hash"],
            approved_by=intent.approved_by,
            receipt_digest="0" * 64,
        )
    f["service"].recover(f["alice"], f["project"], intent.approval.task_id, uid())
    # New fixture evidence for the recovered generation, never production attestation.
    with f["db"].begin() as conn:
        conn.execute(
            update(tasks)
            .where(tasks.c.id == intent.approval.task_id)
            .values(
                state="READY_FOR_APPROVAL",
                evidence_verified=True,
                candidate_digest=intent.approval.candidate_digest,
                evidence_digest=intent.approval.evidence_digest,
            )
        )
    fresh = intent.model_copy(
        update={
            "invocation_id": uid(),
            "approval": intent.approval.model_copy(
                update={
                    "generation": 2,
                    "manifest_digest": "1" * 64,
                    "expires_at": float(now() + 180),
                }
            ),
        }
    )
    ledger.reserve(
        fresh,
        profile,
        session_hash=initial["session_hash"],
        approved_by=intent.approved_by,
        receipt_digest="1" * 64,
    )
    assert stored(f, fresh)[1]["held_microusd"] == 240


def test_insufficient_budget_and_duplicate_reservation_do_not_hold_twice(fixture):
    ledger, intent, profile, _ = reservation(fixture)
    row, _ = stored(fixture, intent)
    with pytest.raises(SafetyError):
        ledger.reserve(
            intent,
            profile,
            session_hash=row["session_hash"],
            approved_by=intent.approved_by,
            receipt_digest="0" * 64,
        )
    assert stored(fixture, intent)[1]["held_microusd"] == 240
    with pytest.raises(SafetyError):
        ledger.reserve(
            intent.model_copy(update={"budget_microusd": 1}),
            profile,
            session_hash=row["session_hash"],
            approved_by=intent.approved_by,
            receipt_digest="0" * 64,
        )
    assert stored(fixture, intent)[1]["held_microusd"] == 240


@pytest.mark.parametrize("remote", ["never_started", "settled", "uncertain"])
def test_api_cancel_waits_for_paid_remote_and_local_confirmation(fixture, remote):
    f = fixture
    ledger, intent, profile, prompt = reservation(f)
    ledger.claim_launch(intent)
    if remote != "never_started":
        ledger.admit(intent, "a" * 64)
    if remote == "settled":
        ledger.settle(intent, profile, {"input_tokens": 20, "output_tokens": 5}, stream(profile))
    elif remote == "uncertain":
        ledger.uncertain(intent.invocation_id)
    result = f["service"].cancel(f["alice"], f["project"], intent.approval.task_id, uid())
    assert result["state"] == "CANCEL_REQUESTED"
    with pytest.raises(Exception):
        f["service"].recover(f["alice"], f["project"], intent.approval.task_id, uid())
    ledger.runtime_ended(intent, cleanup_verified=True)
    task = f["service"].task(f["alice"], f["project"], intent.approval.task_id)
    if remote == "uncertain":
        assert task["state"] == "NEEDS_RECONCILIATION"
        with f["db"].connect() as conn:
            assert conn.execute(select(jobs.c.lease_token)).scalar_one() == intent.invocation_id
        assert stored(f, intent)[1]["held_microusd"] == 240
    else:
        assert task["state"] == "CANCELLED"
        with f["db"].connect() as conn:
            assert conn.execute(select(jobs.c.lease_token)).scalar_one() is None


def test_redaction_and_cross_project_private_result_reads(fixture):
    f = fixture
    ledger, intent, profile, prompt = reservation(f)
    ledger.claim_launch(intent)
    broker = ClaudeBroker(
        ledger,
        intent,
        profile,
        lambda: "fixture",
        prompt,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=stream(profile, "password=fixture"),
            )
        ),
    )
    broker.exchange(request(profile, prompt))
    ledger.runtime_ended(intent, cleanup_verified=True)
    ledger.import_review(intent, broker.result, cleanup_verified=True)
    item = f["service"].artifact(
        f["alice"], f["project"], intent.approval.task_id, intent.invocation_id
    )
    assert item["content"] == "[REDACTED]"
    with pytest.raises(Exception):
        f["service"].artifact(f["bob"], f["project"], intent.approval.task_id, intent.invocation_id)


def test_postgresql_competing_launches_consume_once(fixture):
    if fixture["db"].dialect.name != "postgresql":
        pytest.skip("real ephemeral PostgreSQL required; SQLite is not concurrency evidence")
    ledger, intent, _, _ = reservation(fixture)
    pools = [create_engine(fixture["db"].url) for _ in range(2)]
    barrier = Barrier(2)

    def launch(pool):
        barrier.wait(timeout=5)
        try:
            PaidLedger(pool).claim_launch(intent)
            return "claimed"
        except SafetyError:
            return "denied"

    try:
        with ThreadPoolExecutor(2) as workers:
            assert sorted(workers.map(launch, pools)) == ["claimed", "denied"]
    finally:
        for pool in pools:
            pool.dispose()


@pytest.mark.parametrize("mutation", ["project", "session"])
def test_postgresql_gate_authority_retains_revocation_locks(fixture, mutation):
    if fixture["db"].dialect.name != "postgresql":
        pytest.skip("real ephemeral PostgreSQL required; SQLite cannot prove row locks")
    from sqlalchemy.exc import DBAPIError

    ledger, intent, _, _ = reservation(fixture)
    ledger.claim_launch(intent)
    pool = create_engine(fixture["db"].url, connect_args={"options": "-c lock_timeout=150ms"})

    def revoke():
        with pool.begin() as conn:
            if mutation == "project":
                conn.execute(
                    update(projects)
                    .where(projects.c.id == intent.approval.project_id)
                    .values(policy_digest="0" * 64)
                )
            else:
                conn.execute(update(sessions).values(revoked=True))

    try:
        with ledger.launch_authority(intent) as recheck:
            with ThreadPoolExecutor(1) as workers:
                future = workers.submit(revoke)
                with pytest.raises(DBAPIError) as error:
                    future.result(timeout=5)
                assert error.value.orig.sqlstate == "55P03"
            recheck()
        revoke()
        with pytest.raises(Exception):
            with ledger.launch_authority(intent):
                pytest.fail("committed revocation admitted a subsequent launch")
    finally:
        pool.dispose()


def test_fake_directory_cannot_assert_actual_cgroup_enforcement(tmp_path, fixture):
    profile = profile_for(fixture)
    (tmp_path / "cgroup.subtree_control").write_text("cpu memory pids")
    with pytest.raises(SafetyError):
        DelegatedCgroup(tmp_path, uid(), profile)


def test_live_runtime_rejects_sqlite_and_no_unsafe_cli_flags(fixture, tmp_path):
    profile = profile_for(fixture)
    argv = claude_argv(profile)
    assert "--bare" in argv and argv[argv.index("--tools") + 1] == ""
    assert "--dangerously-skip-permissions" not in argv
    assert "--allow-dangerously-skip-permissions" not in argv
    if fixture["db"].dialect.name == "sqlite":
        with pytest.raises(SafetyError, match="postgresql"):
            ClaudeReviewRunner(fixture["db"], tmp_path, tmp_path, tmp_path, None, None)


@pytest.mark.parametrize("changed", ["invocation", "session"])
def test_paid_invocation_and_exact_session_are_bound_before_any_launch(fixture, changed):
    ledger, intent, profile, prompt = reservation(fixture)
    row, _ = stored(fixture, intent)
    manifest = LaunchManifest(
        invocation_id=uid() if changed == "invocation" else intent.invocation_id,
        task_id=intent.approval.task_id,
        project_id=intent.approval.project_id,
        actor_id=intent.approval.actor_id,
        generation=1,
        provider="claude",
        model=profile.model,
        effort=profile.effort,
        mode="read_only",
        host_os="Linux",
        backend="linux-bwrap-claude-relay-v1",
        backend_binary_digest=profile.backend_digest,
        vendor_binary_digest=profile.cli_digest,
        runner_digest="a" * 64,
        policy_digest=profile.policy_digest,
        image=profile.image,
        workspace=profile.image,
        network=NetworkPolicy(provider_hosts=("api.anthropic.com",)),
        overlay_digest="a" * 64,
        caller_context_digest="a" * 64,
        deadline=float(now() + 60),
        budget=InvocationBudget(max_invocations=1, max_cost_microusd=240),
    )
    runner = ClaudeReviewRunner.__new__(ClaudeReviewRunner)
    runner.ledger = ledger
    with pytest.raises(SafetyError, match="invocation_or_session"):
        runner.run(
            manifest,
            profile,
            intent,
            (),
            prompt,
            session_hash=row["session_hash"],
            approved_by=intent.approved_by,
            cancel=__import__("threading").Event(),
        )
    assert stored(fixture, intent)[0]["state"] == "RESERVED"


def prepared_runner(f, tmp_path, monkeypatch):
    """Deterministic authority-boundary harness; no OS/provider enforcement claim."""
    ledger, intent, profile, prompt = reservation(f)
    row, _ = stored(f, intent)
    manifest = LaunchManifest(
        invocation_id=intent.invocation_id,
        task_id=intent.approval.task_id,
        project_id=intent.approval.project_id,
        actor_id=intent.approval.actor_id,
        generation=1,
        provider="claude",
        model=profile.model,
        effort=profile.effort,
        mode="read_only",
        host_os="Linux",
        backend="linux-bwrap-claude-relay-v1",
        backend_binary_digest=profile.backend_digest,
        vendor_binary_digest=profile.cli_digest,
        runner_digest="a" * 64,
        policy_digest=profile.policy_digest,
        image=profile.image,
        workspace=profile.image,
        network=NetworkPolicy(provider_hosts=("api.anthropic.com",)),
        caller_context_digest=digest(
            {
                "actor_id": intent.approval.actor_id,
                "project_id": intent.approval.project_id,
                "session_hash": row["session_hash"],
            }
        ),
        overlay_digest=digest(
            {
                "profile": profile.binding,
                "prompt": intent.prompt_digest,
                "budget": intent.budget_microusd,
                "approved_by": intent.approved_by,
            }
        ),
        deadline=float(now() + 60),
        budget=InvocationBudget(max_invocations=1, max_cost_microusd=240),
    )
    intent = intent.model_copy(
        update={
            "approval": intent.approval.model_copy(update={"manifest_digest": manifest.binding})
        }
    )
    with f["db"].begin() as conn:
        conn.execute(
            update(paid_reviews)
            .where(paid_reviews.c.id == intent.invocation_id)
            .values(intent=intent.model_dump(mode="json"), intent_digest=intent.binding)
        )
    # Reservation already exists; no synthetic signature is treated as a real receipt.
    monkeypatch.setattr(ledger, "reserve", lambda *a, **k: None)
    runner = ClaudeReviewRunner.__new__(ClaudeReviewRunner)
    runner.ledger = ledger
    runner.verifier = SimpleNamespace(
        verify=lambda *a, **k: SimpleNamespace(receipt_set_digest="0" * 64)
    )

    class PrivateRoot:
        def __fspath__(self):
            return str(tmp_path)

        def mkdir(self, **kwargs):
            pass

        def is_symlink(self):
            return False

        def stat(self):
            return SimpleNamespace(st_mode=0o700)

    runner.runtime_root = PrivateRoot()
    runner.delegated_root = tmp_path
    runner.command = lambda *a: ("fixture-only",)
    runner.credential = lambda: pytest.fail("no credential read at local launch")
    monkeypatch.setattr(claude_runner, "UnixRelay", lambda *a: nullcontext())
    monkeypatch.setattr(
        claude_runner,
        "DelegatedCgroup",
        lambda *a: SimpleNamespace(attach=lambda pid: None, kill_and_verify=lambda: True),
    )
    return runner, ledger, intent, profile, prompt, manifest, row["session_hash"]


@pytest.mark.parametrize(
    "mutation",
    [
        "cancel",
        "session",
        "requester",
        "approver",
        "record",
        "intent",
        "lease",
        "candidate",
        "policy",
    ],
)
def test_preparation_revocation_denies_popen_and_refunds_proven_unsent(
    fixture, tmp_path, monkeypatch, mutation
):
    f = fixture
    runner, ledger, intent, profile, prompt, manifest, session_hash = prepared_runner(
        f, tmp_path, monkeypatch
    )

    def prepare(*_):
        with f["db"].begin() as conn:
            if mutation == "cancel":
                conn.execute(update(jobs).values(cancel_requested=True))
            elif mutation == "session":
                conn.execute(update(sessions).values(revoked=True))
            elif mutation in {"requester", "approver"}:
                who = f["alice"] if mutation == "requester" else f["viewer"]
                conn.execute(update(members).where(members.c.user_id == who).values(role="viewer"))
            elif mutation == "record":
                conn.execute(update(paid_reviews).values(revoked=True))
            elif mutation == "intent":
                conn.execute(update(paid_reviews).values(intent={"tampered": True}))
            elif mutation == "lease":
                conn.execute(update(jobs).values(lease_token="different-invocation"))
            elif mutation == "candidate":
                conn.execute(update(tasks).values(candidate_digest="0" * 64))
            else:
                conn.execute(update(projects).values(policy_digest="0" * 64))
        return ("fixture-only",)

    runner.command = prepare
    monkeypatch.setattr(
        claude_runner.subprocess,
        "Popen",
        lambda *a, **k: pytest.fail("revoked authority launched after preparation"),
    )
    with pytest.raises(Exception):
        runner.run(
            manifest,
            profile,
            intent,
            (),
            prompt,
            session_hash=session_hash,
            approved_by=intent.approved_by,
            cancel=threading.Event(),
        )
    row, budget = stored(f, intent)
    if mutation in {"intent", "lease"}:
        # A corrupted durable fence cannot justify rewriting accounting.
        assert budget["held_microusd"] == 240
    else:
        assert row["state"] == "TERMINATED" and budget["held_microusd"] == 0


@pytest.mark.parametrize("change", ["approval_expiry", "session_expiry", "cancel_event"])
def test_gated_attachment_rechecks_deadlines_and_cancel_before_exec_permission(
    fixture, tmp_path, monkeypatch, change
):
    runner, ledger, intent, profile, prompt, manifest, session_hash = prepared_runner(
        fixture, tmp_path, monkeypatch
    )
    clock = [now()]
    monkeypatch.setattr(paid_store, "now", lambda: clock[0])
    if change == "session_expiry":
        with fixture["db"].begin() as conn:
            conn.execute(update(sessions).values(expires_at=clock[0] + 1))
    cancel = threading.Event()
    child = SimpleNamespace(pid=123, stdin=io.BytesIO(), stdout=io.BytesIO(), returncode=None)
    child.poll = lambda: child.returncode
    child.kill = lambda: setattr(child, "returncode", -9)
    child.wait = lambda **k: child.returncode
    monkeypatch.setattr(claude_runner.subprocess, "Popen", lambda *a, **k: child)

    def attach(_):
        if change == "approval_expiry":
            clock[0] = int(intent.approval.expires_at)
        elif change == "session_expiry":
            clock[0] += 2
        else:
            cancel.set()

    monkeypatch.setattr(
        claude_runner,
        "DelegatedCgroup",
        lambda *a: SimpleNamespace(attach=attach, kill_and_verify=lambda: True),
    )
    monkeypatch.setattr(
        claude_runner.os,
        "write",
        lambda *a: pytest.fail("expired/cancelled authority released exec gate"),
    )
    with pytest.raises(SafetyError):
        runner.run(
            manifest,
            profile,
            intent,
            (),
            prompt,
            session_hash=session_hash,
            approved_by=intent.approved_by,
            cancel=cancel,
        )
    assert child.returncode == -9 and child.stdin.closed and child.stdout.closed
    row, budget = stored(fixture, intent)
    assert row["state"] == "TERMINATED" and budget["held_microusd"] == 0


@pytest.mark.skipif(os.name == "nt", reason="actual Unix relay is Linux/macOS only")
def test_actual_unix_relay_capability_and_fixed_provider_wire(fixture, tmp_path):
    ledger, intent, profile, prompt = reservation(fixture)
    ledger.claim_launch(intent)
    calls = []

    def upstream(req):
        calls.append(req)
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=stream(profile)
        )

    broker = ClaudeBroker(
        ledger,
        intent,
        profile,
        lambda: "fixture-broker-only",
        prompt,
        transport=httpx.MockTransport(upstream),
    )
    capability = "fixture-relay-only"
    with UnixRelay(tmp_path, broker, capability):

        def send(cap):
            value = canonical(
                {"capability": cap, "body": base64.b64encode(request(profile, prompt)).decode()}
            ).encode()
            with socket.socket(socket.AF_UNIX) as channel:
                channel.settimeout(3)
                channel.connect(str(tmp_path / "broker.sock"))
                channel.sendall(struct.pack("!I", len(value)) + value)
                try:
                    length = struct.unpack("!I", receive(channel, 4))[0]
                    return receive(channel, length)
                except ValueError:
                    return None

        assert send("wrong-invocation") is None
        assert calls == []
        assert send(capability) == stream(profile)
        assert send(capability) is None
    assert len(calls) == 1 and stored(fixture, intent)[0]["state"] == "SETTLED"
