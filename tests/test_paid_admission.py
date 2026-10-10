"""Synthetic consent/queue contracts only. No credential/provider or live dispatch."""

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

from sqlalchemy import insert, select, update
from test_approved_vendor import seeded_review
from test_claude_transport import profile_for
from test_web import fixture as shared_fixture

from intelligenceai.web.store import (
    members,
    now,
    paid_budgets,
    paid_profiles,
    paid_requests,
    projects,
    sessions,
    tasks,
    uid,
)

fixture = shared_fixture


def setup(f):
    task_id, headers = seeded_review(f)
    profile = profile_for(f)
    profile_id = uid()
    with f["db"].begin() as conn:
        conn.execute(
            insert(paid_profiles).values(
                id=profile_id,
                project_id=f["project"],
                name="SYNTHETIC_PROFILE_ONLY",
                profile=profile.model_dump(mode="json"),
                active=True,
            )
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
    return f["base"] + "/tasks/" + task_id + "/paid-review", task_id, headers, profile_id


def post(f, path, headers, payload, key=None):
    return f["client"].post(
        path, json=payload, headers={**headers, "Idempotency-Key": key or uid()}
    )


def quote(f, path, headers, profile_id):
    response = post(f, path + "/quote", headers, {"profile_id": profile_id})
    assert response.status_code == 200, response.text
    record = response.json()
    return record, {"request_id": record["id"], "quote_digest": record["quote_digest"]}


def test_exact_consent_and_one_time_request_remain_notrun_and_hold_no_funds(fixture):
    f = fixture
    path, task_id, headers, profile_id = setup(f)
    record, binding = quote(f, path, headers, profile_id)
    assert record["profile_id"] == profile_id
    q = record["quote"]
    assert (q["actor_id"], q["project_id"], q["task_id"], q["generation"]) == (
        f["alice"],
        f["project"],
        task_id,
        1,
    )
    assert q["provider"] == "claude" and q["model"] == "claude-fixture-test"
    assert q["effort"] == "low" and q["max_calls"] == 1 and q["currency"] == "USD"
    assert q["cost_ceiling_microusd"] == 240
    assert post(f, path + "/request", headers, binding).status_code == 409
    assert post(f, path + "/approve", headers, binding).json()["state"] == "APPROVED"
    key = uid()
    request = post(f, path + "/request", headers, binding, key).json()
    assert request["state"] == "REQUESTED" and request["live_model"] == "NOTRUN"
    assert post(f, path + "/request", headers, binding, key).json() == request
    assert post(f, path + "/request", headers, binding).status_code == 409
    assert post(f, path + "/quote", headers, {"profile_id": profile_id}).status_code == 409
    status = f["client"].get(path).json()
    assert status["requests"][0]["profile_id"] == profile_id
    assert status["requests"][0]["quote_digest"] == record["quote_digest"]
    assert status["requests"][0]["quote"] == record["quote"]
    assert (
        status["execution_enabled"] is False
        and "signed_control_receipts_required" in status["blockers"]
    )
    with f["db"].connect() as conn:
        budget = conn.execute(select(paid_budgets)).mappings().one()
        assert budget["held_microusd"] == budget["spent_microusd"] == 0
        assert len(conn.execute(select(paid_requests)).all()) == 1


@pytest.mark.parametrize(
    "change",
    [
        "candidate",
        "evidence",
        "policy",
        "generation",
        "cancel",
        "expiry",
        "session",
        "profile",
        "role",
        "budget",
    ],
)
def test_mutation_rechecks_current_scope_and_quote_before_consent(fixture, change):
    f = fixture
    path, task_id, headers, profile_id = setup(f)
    record, binding = quote(f, path, headers, profile_id)
    with f["db"].begin() as conn:
        if change == "candidate":
            conn.execute(update(tasks).values(candidate_digest="0" * 64))
        elif change == "evidence":
            conn.execute(update(tasks).values(evidence_digest="0" * 64))
        elif change == "policy":
            conn.execute(update(projects).values(policy_digest="0" * 64))
        elif change == "generation":
            conn.execute(update(tasks).values(generation=2))
        elif change == "cancel":
            conn.execute(update(tasks).values(state="CANCELLED"))
        elif change == "expiry":
            expired = {**record["quote"], "expires_at": now() - 1}
            conn.execute(update(paid_requests).values(quote=expired))
        elif change == "session":
            conn.execute(update(sessions).values(revoked=True))
        elif change == "profile":
            conn.execute(update(paid_profiles).values(active=False))
        elif change == "role":
            conn.execute(
                update(members).where(members.c.user_id == f["alice"]).values(role="viewer")
            )
        else:
            conn.execute(update(paid_budgets).values(limit_microusd=1))
    assert post(f, path + "/approve", headers, binding).status_code in {401, 403, 409}
    with f["db"].connect() as conn:
        assert conn.execute(select(paid_requests.c.state)).scalar_one() == "QUOTED"


def test_new_session_and_cross_user_cannot_reuse_consent(fixture):
    f = fixture
    path, _, headers, profile_id = setup(f)
    _, binding = quote(f, path, headers, profile_id)
    new_session = f["sign_in"](f["alice"])
    assert post(f, path + "/approve", new_session, binding).status_code == 409
    assert f["client"].get(path).json()["requests"][0]["state"] == "STALE"
    viewer = f["sign_in"](f["viewer"])
    assert f["client"].get(path).json()["requests"] == []
    assert post(f, path + "/approve", viewer, binding).status_code == 403
    f["sign_in"](f["bob"])
    assert f["client"].get(path).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"provider": "claude"},
        {"model": "latest"},
        {"effort": "max"},
        {"actor_id": "other"},
        {"cost_ceiling_microusd": 999999},
        {"currency": "KRW"},
        {"command": "shell"},
        {"env": {"KEY": "fixture"}},
        {"livegate": True},
        {"url": "http://169.254.169.254/"},
    ],
)
def test_browser_authority_cost_and_url_fields_are_forbidden(fixture, payload):
    f = fixture
    path, _, headers, profile_id = setup(f)
    assert (
        post(f, path + "/quote", headers, {"profile_id": profile_id, **payload}).status_code == 422
    )


def test_default_pending_and_csrf_origin_checks(fixture):
    f = fixture
    task_id, headers = seeded_review(f)
    path = f["base"] + "/tasks/" + task_id + "/paid-review"
    status = f["client"].get(path).json()
    assert status["profiles"] == [] and status["requests"] == []
    assert status["execution_enabled"] is False and status["live_model"] == "NOTRUN"
    for change in ({"Origin": "https://attacker.example"}, {"X-CSRF-Token": "wrong"}):
        response = f["client"].post(
            path + "/quote", json={"profile_id": uid()}, headers={**headers, **change}
        )
        assert response.status_code == 403


def test_fresh_quote_supersedes_old_consent_and_cancel_revokes_pending_request(fixture):
    f = fixture
    path, task_id, headers, profile_id = setup(f)
    old, binding = quote(f, path, headers, profile_id)
    assert post(f, path + "/approve", headers, binding).status_code == 200
    fresh, fresh_binding = quote(f, path, headers, profile_id)
    assert fresh["id"] != old["id"]
    assert post(f, path + "/request", headers, binding).status_code == 409
    assert post(f, path + "/approve", headers, fresh_binding).status_code == 200
    assert post(f, path + "/request", headers, fresh_binding).status_code == 200
    f["service"].cancel(f["alice"], f["project"], task_id, uid())
    with f["db"].connect() as conn:
        assert (
            conn.execute(
                select(paid_requests.c.state).where(paid_requests.c.id == fresh["id"])
            ).scalar_one()
            == "REVOKED"
        )
    assert all(row["state"] == "STALE" for row in f["client"].get(path).json()["requests"])


def test_postgresql_competing_requests_consume_consent_once(fixture):
    f = fixture
    if f["db"].dialect.name != "postgresql":
        pytest.skip("real ephemeral PostgreSQL required; SQLite is not concurrency proof")
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy import create_engine

    from intelligenceai.web.paid_admission import ConsentInput, PaidAdmission
    from intelligenceai.web.service import Problem

    path, task_id, headers, profile_id = setup(f)
    _, binding = quote(f, path, headers, profile_id)
    assert post(f, path + "/approve", headers, binding).status_code == 200
    with f["db"].connect() as conn:
        session_hash = conn.execute(select(paid_requests.c.session_hash)).scalar_one()
    barrier = Barrier(2)
    pools = [create_engine(f["db"].url) for _ in range(2)]

    def request(pool):
        barrier.wait(timeout=5)
        try:
            return PaidAdmission(pool).transition(
                f["alice"],
                f["project"],
                task_id,
                uid(),
                ConsentInput(**binding),
                session_hash,
                "request",
            )["state"]
        except Problem as exc:
            assert exc.status == 409
            return "denied"

    try:
        with ThreadPoolExecutor(2) as workers:
            assert sorted(workers.map(request, pools)) == ["REQUESTED", "denied"]
    finally:
        for pool in pools:
            pool.dispose()
