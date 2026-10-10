"""Ephemeral test signatures and mock process/HTTP only; no paid provider or OS proof."""

import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier, Event
from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

import httpx
from authlib.jose import JsonWebKey, JsonWebSignature
from sqlalchemy import create_engine, select, update
from test_claude_transport import request, stream
from test_paid_admission import post, quote, setup
from test_web import fixture as shared_fixture

from intelligenceai.security import SafetyError, digest
from intelligenceai.web import claude_runner
from intelligenceai.web.claude_contracts import ClaudeProfile, PaidReviewIntent
from intelligenceai.web.claude_runner import ClaudeReviewRunner
from intelligenceai.web.live_authority import REQUIRED_CONTROLS, TOKEN_TYPE, ReceiptVerifier
from intelligenceai.web.paid_dispatch import (
    ControlFact,
    DispatchRuntime,
    PaidDispatcher,
    run_descriptor,
    worker_descriptor,
)
from intelligenceai.web.paid_store import PaidLedger
from intelligenceai.web.store import (
    members,
    now,
    paid_budgets,
    paid_dispatches,
    paid_profiles,
    paid_requests,
    paid_reviews,
    sessions,
    tasks,
    uid,
)

fixture = shared_fixture


@pytest.fixture(autouse=True)
def deny_real_provider_transport(monkeypatch):
    monkeypatch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        lambda *args, **kwargs: pytest.fail("synthetic dispatch tests require MockTransport"),
    )


def queued(f):
    path, tid, headers, pid = setup(f)
    record, binding = quote(f, path, headers, pid)
    assert post(f, path + "/approve", headers, binding).status_code == 200
    assert post(f, path + "/request", headers, binding).status_code == 200
    with f["db"].connect() as conn:
        profile = ClaudeProfile.model_validate(
            conn.execute(select(paid_profiles.c.profile)).scalar_one()
        )
    runtime = DispatchRuntime(
        runner_digest="a" * 64, workspace=profile.image, egress_digest="e" * 64
    )
    facts = {
        name: ControlFact(
            evidence_digest=digest({"synthetic_control": name}),
            issued_at=now() - 1,
            expires_at=now() + 200,
        )
        for name in REQUIRED_CONTROLS - {"paid_call_authorization"}
    }
    keys = {
        name: JsonWebKey.generate_key("OKP", "Ed25519", is_private=True)
        for name in REQUIRED_CONTROLS
    }
    verifier = ReceiptVerifier({name: (name, key.as_dict()) for name, key in keys.items()})
    issued = []

    class SyntheticIssuer:
        def issue(self, statement):
            issued.append(statement)
            return (
                JsonWebSignature(algorithms=["EdDSA"])
                .serialize_compact(
                    {"alg": "EdDSA", "kid": statement.control, "typ": TOKEN_TYPE},
                    statement.model_dump_json().encode(),
                    keys[statement.control],
                )
                .decode()
            )

    dispatcher = PaidDispatcher(f["db"], verifier, SyntheticIssuer())
    return dispatcher, record, runtime, facts, issued, path, tid, headers


def accounting(f):
    with f["db"].connect() as conn:
        return (
            list(conn.execute(select(paid_reviews)).mappings()),
            conn.execute(select(paid_budgets)).mappings().one(),
            list(conn.execute(select(paid_dispatches)).mappings()),
        )


def test_request_consumption_hold_and_delivery_are_atomic_and_retries_keep_exact_receipts(fixture):
    d, r, runtime, facts, issued, path, _, headers = queued(fixture)
    result = d.prepare(r["id"], runtime, facts)
    descriptor = worker_descriptor(fixture["db"], r["id"])
    assert result == {"request_id": r["id"], "invocation_id": r["id"], "state": "RESERVED"}
    assert len(issued) == 6
    paid = next(statement for statement in issued if statement.control == "paid_call_authorization")
    assert paid.evidence_digest == r["quote_digest"]
    assert descriptor["profile"]["model"] == r["quote"]["model"]
    # Process restart/lost dispatch response do not regenerate tokens or reserve twice.
    restarted = PaidDispatcher(fixture["db"], d.verifier, None)
    assert restarted.prepare(r["id"], runtime, {}) == result
    assert worker_descriptor(fixture["db"], r["id"]) == descriptor
    rows, budget, deliveries = accounting(fixture)
    assert len(rows) == len(deliveries) == 1 and budget["held_microusd"] == 240
    assert (
        post(fixture, path + "/quote", headers, {"profile_id": r["profile_id"]}).status_code == 409
    )


@pytest.mark.parametrize(
    "failure",
    [
        "no_signer",
        "missing_control",
        "expired_control",
        "issuer_failure",
        "changed_statement",
        "transaction_failure",
    ],
)
def test_failed_dispatch_leaves_consent_and_budget_unchanged(fixture, monkeypatch, failure):
    d, r, runtime, facts, _, _, _, _ = queued(fixture)
    if failure == "no_signer":
        d.issuer = None
    elif failure == "missing_control":
        facts.pop(next(iter(facts)))
    elif failure == "expired_control":
        key = next(iter(facts))
        facts[key] = facts[key].model_copy(update={"expires_at": 1})
    elif failure == "issuer_failure":
        d.issuer = SimpleNamespace(
            issue=lambda *_: (_ for _ in ()).throw(ValueError("synthetic failure"))
        )
    elif failure == "changed_statement":
        original = d.issuer.issue
        d.issuer.issue = lambda st: original(st.model_copy(update={"evidence_digest": "0" * 64}))
    else:
        original = d.ledger.event

        def fail(conn, intent, name, details):
            original(conn, intent, name, details)
            if name == "paid_request_dispatched":
                raise SafetyError("synthetic rollback after reservation")

        monkeypatch.setattr(d.ledger, "event", fail)
    with pytest.raises(SafetyError):
        d.prepare(r["id"], runtime, facts)
    rows, budget, deliveries = accounting(fixture)
    assert rows == deliveries == []
    assert budget["held_microusd"] == budget["spent_microusd"] == 0
    with fixture["db"].connect() as conn:
        assert conn.execute(select(paid_requests.c.state)).scalar_one() == "REQUESTED"


@pytest.mark.parametrize("change", ["cancel", "session", "role", "profile", "quote", "candidate"])
def test_revocation_during_external_signing_blocks_consumption(fixture, change):
    d, r, runtime, facts, _, _, tid, _ = queued(fixture)
    original = d.issuer.issue

    def changed(statement):
        if statement.control == "paid_call_authorization":
            with fixture["db"].begin() as conn:
                if change == "cancel":
                    conn.execute(update(paid_requests).values(state="REVOKED"))
                elif change == "session":
                    conn.execute(update(sessions).values(revoked=True))
                elif change == "role":
                    conn.execute(
                        update(members)
                        .where(members.c.user_id == fixture["alice"])
                        .values(role="viewer")
                    )
                elif change == "profile":
                    conn.execute(update(paid_profiles).values(active=False))
                elif change == "quote":
                    conn.execute(update(paid_requests).values(quote_digest="0" * 64))
                else:
                    conn.execute(
                        update(tasks).where(tasks.c.id == tid).values(candidate_digest="0" * 64)
                    )
        return original(statement)

    d.issuer.issue = changed
    with pytest.raises(Exception):
        d.prepare(r["id"], runtime, facts)
    assert accounting(fixture)[0] == [] and accounting(fixture)[1]["held_microusd"] == 0


def mock_worker(f, d, tmp_path, monkeypatch, *, unknown=False, before_exchange=None):
    """Real runner/ledger/broker with synthetic process, cgroup and upstream seams."""
    runner = ClaudeReviewRunner.__new__(ClaudeReviewRunner)
    runner.ledger, runner.verifier = PaidLedger(f["db"]), d.verifier
    runner.credential = lambda: "SYNTHETIC_BROKER_VALUE_ONLY"
    runner.command = lambda *args: ("SYNTHETIC_PROCESS_ONLY",)
    runner.delegated_root = tmp_path

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
    calls, local = [], {"done": Event(), "broker": None, "cleanup": False, "error": None}

    def upstream(req):
        calls.append(req)
        if unknown:
            raise httpx.ReadError("SYNTHETIC_RESPONSE_LOST", request=req)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=stream(local["broker"].profile),
        )

    @contextmanager
    def relay(_root, broker, _capability):
        local["broker"] = broker
        broker._transport = httpx.MockTransport(upstream)
        yield

    monkeypatch.setattr(claude_runner, "UnixRelay", relay)

    def cleaned():
        local["cleanup"] = True
        if local.get("gate_holder") is not None:
            os.close(local.pop("gate_holder"))
        return True

    monkeypatch.setattr(
        claude_runner,
        "DelegatedCgroup",
        lambda *a: SimpleNamespace(attach=lambda pid: None, kill_and_verify=cleaned),
    )

    class Input:
        closed = False

        def write(self, value):
            try:
                parsed = json.loads(value)
                broker = local["broker"]
                assert parsed["prompt"] == broker.prompt
                if before_exchange:
                    before_exchange()
                broker.exchange(request(broker.profile, parsed["prompt"]))
            except Exception as exc:
                local["error"] = exc
            finally:
                local["done"].set()

        def close(self):
            self.closed = True

    child = SimpleNamespace(pid=123, stdin=Input(), stdout=io.BytesIO(), returncode=0)
    child.poll = lambda: 0 if local["done"].is_set() else None
    child.wait = lambda **kw: 0 if local["done"].wait(5) else -9
    child.kill = lambda: local["done"].set()

    def launched(*args, **kwargs):
        local["gate_holder"] = os.dup(kwargs["pass_fds"][0])
        return child

    monkeypatch.setattr(claude_runner.subprocess, "Popen", launched)
    return runner, calls, local


@pytest.mark.parametrize("unknown", [False, True])
def test_request_to_existing_worker_and_broker_delivers_once_and_never_recharges_unknown(
    fixture,
    tmp_path,
    monkeypatch,
    unknown,
):
    f = fixture
    d, r, runtime, facts, _, path, _, _ = queued(f)
    d.prepare(r["id"], runtime, facts)
    descriptor = worker_descriptor(f["db"], r["id"])
    runner, calls, local = mock_worker(f, d, tmp_path, monkeypatch, unknown=unknown)
    if unknown:
        with pytest.raises(SafetyError):
            run_descriptor(runner, descriptor, Event(), reserved=True)
    else:
        assert run_descriptor(runner, descriptor, Event(), reserved=True)["state"] == "IMPORTED"
        assert local["error"] is None
    rows, budget, _ = accounting(f)
    assert len(calls) == 1 and local["cleanup"]
    assert rows[0]["state"] == ("NEEDS_RECONCILIATION" if unknown else "IMPORTED")
    observed = f["client"].get(path).json()
    assert observed["live_model"] == ("UNKNOWN" if unknown else "RESULT_RECEIVED")
    assert observed["requests"][0]["worker_state"] == rows[0]["state"]
    assert "session_hash" not in json.dumps(observed) and "tokens" not in json.dumps(observed)
    assert budget["held_microusd"] == (240 if unknown else 0)
    assert budget["spent_microusd"] == (0 if unknown else 60)
    # Duplicate/stale delivery cannot even reach Popen; lost completion is inspected.
    with pytest.raises(SafetyError):
        worker_descriptor(f["db"], r["id"])
    with pytest.raises(SafetyError):
        run_descriptor(runner, descriptor, Event(), reserved=True)
    assert len(calls) == 1 and accounting(f)[1] == budget
    assert d.prepare(r["id"], runtime, facts)["state"] == rows[0]["state"]


def test_cancel_reserved_delivery_refunds_once_and_prevents_worker_replay(fixture):
    d, r, runtime, facts, _, _, tid, _ = queued(fixture)
    d.prepare(r["id"], runtime, facts)
    fixture["service"].cancel(fixture["alice"], fixture["project"], tid, uid())
    assert accounting(fixture)[1]["held_microusd"] == 0
    with pytest.raises(SafetyError):
        worker_descriptor(fixture["db"], r["id"])
    d.prepare(r["id"], runtime, facts)
    assert accounting(fixture)[1]["held_microusd"] == 0


def test_launch_claim_crash_and_cancellation_keep_hold_until_confirmed_cleanup(fixture):
    d, r, runtime, facts, _, _, tid, _ = queued(fixture)
    d.prepare(r["id"], runtime, facts)
    descriptor = worker_descriptor(fixture["db"], r["id"])
    intent = PaidReviewIntent.model_validate(descriptor["intent"])
    ledger = PaidLedger(fixture["db"])
    ledger.claim_launch(intent)
    assert d.prepare(r["id"], runtime, facts)["state"] == "LAUNCHING"
    with pytest.raises(SafetyError):
        worker_descriptor(fixture["db"], r["id"])
    result = fixture["service"].cancel(fixture["alice"], fixture["project"], tid, uid())
    assert result["state"] == "CANCEL_REQUESTED"
    assert accounting(fixture)[1]["held_microusd"] == 240
    ledger.runtime_ended(intent, cleanup_verified=True)
    assert accounting(fixture)[1]["held_microusd"] == 0
    assert (
        fixture["service"].task(fixture["alice"], fixture["project"], tid)["state"] == "CANCELLED"
    )


@pytest.mark.parametrize("change", ["cancel", "profile", "session"])
def test_gate_to_http_revocation_denies_upstream_and_refunds_proven_unsent(
    fixture,
    tmp_path,
    monkeypatch,
    change,
):
    d, r, runtime, facts, _, _, tid, _ = queued(fixture)
    d.prepare(r["id"], runtime, facts)
    descriptor = worker_descriptor(fixture["db"], r["id"])

    def revoke():
        if change == "cancel":
            fixture["service"].cancel(fixture["alice"], fixture["project"], tid, uid())
        else:
            with fixture["db"].begin() as conn:
                if change == "profile":
                    conn.execute(update(paid_profiles).values(active=False))
                else:
                    conn.execute(update(sessions).values(revoked=True))

    runner, calls, local = mock_worker(fixture, d, tmp_path, monkeypatch, before_exchange=revoke)
    with pytest.raises(SafetyError):
        run_descriptor(runner, descriptor, Event(), reserved=True)
    assert calls == [] and local["cleanup"]
    assert accounting(fixture)[1]["held_microusd"] == 0
    with pytest.raises(SafetyError):
        worker_descriptor(fixture["db"], r["id"])
    d.prepare(r["id"], runtime, facts)
    assert accounting(fixture)[1]["held_microusd"] == 0


def test_monitor_rollback_cannot_undo_profile_revocation(fixture, monkeypatch):
    d, r, runtime, facts, *_ = queued(fixture)
    d.prepare(r["id"], runtime, facts)
    intent = PaidReviewIntent.model_validate(worker_descriptor(fixture["db"], r["id"])["intent"])
    ledger = PaidLedger(fixture["db"])
    ledger.claim_launch(intent)
    original = ledger.locked
    monitor_connections = []

    def failed_monitor(conn, *args, **kwargs):
        monitor_connections.append(conn.connection.driver_connection)
        original(conn, *args, **kwargs)
        # A failed poll must roll back only its own transaction, including on PG
        # where the other connection cannot see the uncommitted profile UPDATE.
        raise SafetyError("synthetic_monitor_failure")

    monkeypatch.setattr(ledger, "locked", failed_monitor)
    with fixture["db"].begin() as writer:
        writer.execute(update(paid_profiles).values(active=False))
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(ledger.active, intent).result(timeout=5) is False
        assert monitor_connections[0] is not writer.connection.driver_connection
    monkeypatch.setattr(ledger, "locked", original)
    with fixture["db"].connect() as conn:
        assert conn.execute(select(paid_profiles.c.active)).scalar_one() is False
    # Recheck the actual irreversible HTTP admission boundary after commit.
    with pytest.raises(SafetyError, match="paid_dispatched_consent_revoked"):
        ledger.admit(intent, "a" * 64)
    assert accounting(fixture)[0][0]["state"] == "LAUNCHING"


@pytest.mark.parametrize("change", ["profile", "role", "session", "quote"])
def test_reserved_worker_rechecks_current_profile_consent_and_session_before_launch(
    fixture, change
):
    d, r, runtime, facts, _, _, _, _ = queued(fixture)
    d.prepare(r["id"], runtime, facts)
    descriptor = worker_descriptor(fixture["db"], r["id"])
    intent = PaidReviewIntent.model_validate(descriptor["intent"])
    with fixture["db"].begin() as conn:
        if change == "profile":
            conn.execute(update(paid_profiles).values(active=False))
        elif change == "role":
            conn.execute(
                update(members).where(members.c.user_id == fixture["alice"]).values(role="operator")
            )
        elif change == "session":
            conn.execute(update(sessions).values(revoked=True))
        else:
            conn.execute(update(paid_requests).values(quote_digest="0" * 64))
    with pytest.raises(Exception):
        PaidLedger(fixture["db"]).claim_launch(intent)
    assert accounting(fixture)[0][0]["state"] == "RESERVED"


def test_postgresql_competing_dispatchers_reserve_and_consume_once(fixture):
    if fixture["db"].dialect.name != "postgresql":
        pytest.skip("real PostgreSQL required; SQLite is not competing dispatch evidence")
    d, r, runtime, facts, _, _, _, _ = queued(fixture)
    barrier = Barrier(2)
    original = d.issuer.issue

    def synchronize(statement):
        if statement.control == sorted(REQUIRED_CONTROLS)[0]:
            barrier.wait(timeout=10)
        return original(statement)

    d.issuer.issue = synchronize
    pools = [create_engine(fixture["db"].url) for _ in range(2)]

    def dispatch(pool):
        try:
            return PaidDispatcher(pool, d.verifier, d.issuer).prepare(r["id"], runtime, facts)[
                "state"
            ]
        except Exception:
            return "denied"

    try:
        with ThreadPoolExecutor(2) as workers:
            assert sorted(workers.map(dispatch, pools)) == ["RESERVED", "denied"]
        rows, budget, deliveries = accounting(fixture)
        assert len(rows) == len(deliveries) == 1 and budget["held_microusd"] == 240
    finally:
        for pool in pools:
            pool.dispose()
