"""Offline web regressions. SQLite fixtures are NOT PostgreSQL/OIDC deployment evidence."""

import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient
from sqlalchemy import event, insert, select, update
from sqlalchemy.engine import make_url

from intelligenceai.security import digest
from intelligenceai.web.app import create_app, public_demo_app
from intelligenceai.web.auth import token_hash
from intelligenceai.web.config import Settings
from intelligenceai.web.contracts import ApprovalInput, TaskInput
from intelligenceai.web.service import Problem, Service, bootstrap, session_data
from intelligenceai.web.store import (
    approvals,
    artifacts,
    audit,
    engine,
    jobs,
    members,
    metadata,
    now,
    projects,
    receipts,
    sessions,
    tasks,
    uid,
    users,
)

ORIGIN = "http://testserver"
INPUT = {
    "title": "Review configuration",
    "request": "Review static defaults",
    "profile": "json-review",
}


@pytest.fixture
def fixture(tmp_path):
    url = os.environ.get("IAI_TEST_DATABASE_URL", "sqlite://")
    if url != "sqlite://":
        parsed = make_url(url)
        if parsed.database != "intelligenceai_test" or parsed.host not in {
            "localhost",
            "127.0.0.1",
        }:
            pytest.fail("only loopback intelligenceai_test database may be reset by these fixtures")
    db = engine(url, testing=True)
    metadata.drop_all(db)
    metadata.create_all(db)
    alice, project = bootstrap(db, "https://issuer.example", "alice", "Alice", "Private project")
    bob, other = bootstrap(db, "https://issuer.example", "bob", "Bob", "Other tenant")
    viewer = uid()
    with db.begin() as conn:
        conn.execute(
            insert(users).values(
                id=viewer, issuer="https://issuer.example", subject="viewer", name="Viewer"
            )
        )
        conn.execute(insert(members).values(project_id=project, user_id=viewer, role="viewer"))
    config = Settings(
        url, ORIGIN, "https://issuer.example", "client", "unused-test-value", str(tmp_path), False
    )
    app = create_app(config, db=db, testing=True)
    client = TestClient(app)

    def sign_in(user_id):
        token = secrets.token_urlsafe(32)
        data = session_data(user_id)
        with db.begin() as conn:
            conn.execute(
                insert(sessions).values(
                    token_hash=token_hash(token), data=data, expires_at=now() + 3600
                )
            )
        client.cookies.clear()
        client.cookies.set("iai_test_session", token)
        return {"Origin": ORIGIN, "X-CSRF-Token": data["csrf"], "Idempotency-Key": uid()}

    yield {
        "db": db,
        "app": app,
        "client": client,
        "alice": alice,
        "bob": bob,
        "viewer": viewer,
        "project": project,
        "other": other,
        "sign_in": sign_in,
        "base": f"/api/projects/{project}",
        "service": Service(db),
    }
    client.close()
    metadata.drop_all(db)
    db.dispose()


def submit(f, headers=None):
    headers = headers or f["sign_in"](f["alice"])
    response = f["client"].post(f["base"] + "/tasks", json=INPUT, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"], headers


def ready(f, task_id):
    with f["db"].begin() as conn:
        conn.execute(
            update(tasks)
            .where(tasks.c.id == task_id)
            .values(
                candidate_digest="a" * 64,
                evidence_digest="c" * 64,
                evidence_verified=True,
                state="READY_FOR_APPROVAL",
            )
        )
        policy = conn.execute(
            select(projects.c.policy_digest).where(projects.c.id == f["project"])
        ).scalar()
    return {
        "candidate_digest": "a" * 64,
        "evidence_digest": "c" * 64,
        "policy_digest": policy,
        "destination_id": "private-review",
        "generation": 1,
        "expires_at": now() + 600,
    }


def test_private_read_write_requires_session_and_no_anonymous_session_allocation(fixture):
    f = fixture
    for path in ["/api/session", "/api/projects", f["base"], f["base"] + "/tasks"]:
        response = f["client"].get(path)
        assert response.status_code == 401
        assert "set-cookie" not in response.headers
    assert (
        f["client"].post(f["base"] + "/tasks", json=INPUT, headers={"Origin": ORIGIN}).status_code
        == 401
    )
    with f["db"].connect() as conn:
        assert conn.execute(select(sessions)).all() == []


def test_submit_duplicate_and_restart_preserves_held_job(fixture):
    f = fixture
    task_id, headers = submit(f)
    repeat = f["client"].post(f["base"] + "/tasks", json=INPUT, headers=headers)
    assert repeat.json()["id"] == task_id
    conflict = f["client"].post(
        f["base"] + "/tasks", json={**INPUT, "title": "Different request"}, headers=headers
    )
    assert conflict.status_code == 409
    detail = Service(f["db"]).task(f["alice"], f["project"], task_id)
    assert detail["state"] == "BLOCKED"
    assert detail["execution_enabled"] is False and detail["model_calls"] == 0
    with f["db"].connect() as conn:
        assert len(conn.execute(select(jobs)).all()) == 1
        assert conn.execute(select(jobs.c.state)).scalar() == "HELD"


@pytest.mark.parametrize(
    "extra",
    [
        {"actor": "admin"},
        {"principal": "root"},
        {"tenant_id": "other"},
        {"env": {"TOKEN": "credential"}},
        {"argv": ["sh", "-c", "echo unsafe"]},
        {"repo": "/etc"},
        {"livegate": True},
        {"destination": "http://169.254.169.254"},
        {"provider": "paid"},
        {"scope": ["../../.ssh"]},
    ],
)
def test_authority_fields_rejected(fixture, extra):
    f = fixture
    headers = f["sign_in"](f["alice"])
    response = f["client"].post(f["base"] + "/tasks", json={**INPUT, **extra}, headers=headers)
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_request"}
    with f["db"].connect() as conn:
        assert conn.execute(select(tasks)).all() == []


def test_csrf_host_origin_cors_and_body_limits(fixture):
    f = fixture
    headers = f["sign_in"](f["alice"])
    for change in [
        {"Origin": "https://evil.example"},
        {"X-CSRF-Token": "bad"},
        {"Sec-Fetch-Site": "cross-site"},
    ]:
        assert (
            f["client"]
            .post(f["base"] + "/tasks", json=INPUT, headers={**headers, **change})
            .status_code
            == 403
        )
    assert (
        f["client"]
        .post(f["base"] + "/tasks", json=INPUT, headers={"X-CSRF-Token": headers["X-CSRF-Token"]})
        .status_code
        == 403
    )
    assert f["client"].get("/api/session", headers={"Host": "evil.example"}).status_code == 400
    assert f["client"].get("/api/session", headers={"Origin": "null"}).status_code == 403
    assert (
        f["client"].options(f["base"], headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert (
        f["client"].post(f["base"] + "/tasks", content="x" * 17000, headers=headers).status_code
        == 413
    )
    chunked = (b"x" * 9000 for _ in range(2))
    assert (
        f["client"].post(f["base"] + "/tasks", content=chunked, headers=headers).status_code == 413
    )
    response = f["client"].get("/api/session")
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "access-control-allow-origin" not in response.headers


def test_provider_readiness_is_authorized_read_only_and_never_exposes_paths(fixture):
    f = fixture
    path = f["base"] + "/connections"
    assert f["client"].get(path).status_code == 401
    f["sign_in"](f["alice"])
    writes = []

    def observe(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(f["db"], "before_cursor_execute", observe)
    try:
        for _ in range(2):
            response = f["client"].get(path)
            assert response.status_code == 200
            status = response.json()
            assert status["execution_enabled"] is False
            reports = status["provider_readiness"]
            assert len(reports) == 10
            assert all(
                row["status"] == "BLOCKED" and row["live_model"] == "NOTRUN" for row in reports
            )
            assert all(row["wrapper_attempts"] == 1 for row in reports)
            assert not any(
                key in row for row in reports for key in ("argv", "env", "path", "credential_refs")
            )
        assert writes == []
    finally:
        event.remove(f["db"], "before_cursor_execute", observe)
    f["sign_in"](f["bob"])
    assert f["client"].get(path).status_code == 404
    f["sign_in"](f["alice"])
    with f["db"].begin() as conn:
        conn.execute(update(members).where(members.c.user_id == f["alice"]).values(role="revoked"))
    assert f["client"].get(path).status_code == 404


def test_cross_tenant_object_read_logs_artifact_sse_and_mutations(fixture):
    f = fixture
    task_id, _ = submit(f)
    artifact_id = uid()
    with f["db"].begin() as conn:
        conn.execute(
            insert(artifacts).values(
                id=artifact_id,
                task_id=task_id,
                name="diff",
                kind="diff",
                content="private bytes",
                digest="d" * 64,
            )
        )
    headers = f["sign_in"](f["bob"])
    paths = [
        f["base"],
        f["base"] + "/tasks",
        f["base"] + "/audit",
        f["base"] + "/connections",
        f["base"] + f"/tasks/{task_id}",
        f["base"] + f"/tasks/{task_id}/logs",
        f["base"] + f"/tasks/{task_id}/events",
        f["base"] + f"/tasks/{task_id}/artifacts/{artifact_id}",
    ]
    for path in paths:
        response = f["client"].get(path)
        assert response.status_code == 404
        assert "private bytes" not in response.text
    for action in ["cancel", "recover", "reject"]:
        assert (
            f["client"]
            .post(f["base"] + f"/tasks/{task_id}/{action}", json={}, headers=headers)
            .status_code
            == 404
        )
    assert f["client"].post(f["base"] + "/tasks", json=INPUT, headers=headers).status_code == 404
    other_base = f"/api/projects/{f['other']}"
    assert f["client"].get(other_base + f"/tasks/{task_id}").status_code == 404


def test_permission_revocation_applies_to_reconnect_and_receipt_replay(fixture):
    f = fixture
    task_id, headers = submit(f)
    path = f["base"] + f"/tasks/{task_id}"
    assert f["client"].get(path + "/events").status_code == 200
    with f["db"].begin() as conn:
        conn.execute(update(members).where(members.c.user_id == f["alice"]).values(role="revoked"))
    assert f["client"].get(path + "/events").status_code == 404
    assert f["client"].post(f["base"] + "/tasks", json=INPUT, headers=headers).status_code == 404


def test_viewer_cannot_mutate_or_change_members(fixture):
    f = fixture
    headers = f["sign_in"](f["viewer"])
    assert f["client"].get(f["base"]).status_code == 200
    assert f["client"].post(f["base"] + "/tasks", json=INPUT, headers=headers).status_code == 403
    assert (
        f["client"]
        .put(
            f["base"] + "/members", json={"user_id": f["alice"], "role": "revoked"}, headers=headers
        )
        .status_code
        == 403
    )


def test_confirmed_unstarted_cancel_and_recovery_generation(fixture):
    f = fixture
    task_id, headers = submit(f)
    path = f["base"] + f"/tasks/{task_id}"
    result = f["client"].post(
        path + "/cancel", json={}, headers={**headers, "Idempotency-Key": uid()}
    )
    assert result.json()["state"] == "CANCELLED"
    recovery_headers = {**headers, "Idempotency-Key": uid()}
    result = f["client"].post(path + "/recover", json={}, headers=recovery_headers)
    assert result.json()["generation"] == 2
    assert (
        f["client"].post(path + "/recover", json={}, headers=recovery_headers).json()["generation"]
        == 2
    )
    detail = f["client"].get(path).json()
    assert detail["state"] == "BLOCKED" and detail["evidence_verified"] is False


def test_uncertain_cancel_preserves_lease_and_blocks_recovery(fixture):
    f = fixture
    task_id, headers = submit(f)
    with f["db"].begin() as conn:
        conn.execute(
            update(jobs)
            .where(jobs.c.task_id == task_id)
            .values(state="LEASED", lease_token="fixture-lease", lease_expires_at=now() - 10)
        )
        conn.execute(update(tasks).where(tasks.c.id == task_id).values(state="RUNNING"))
    path = f["base"] + f"/tasks/{task_id}"
    response = f["client"].post(
        path + "/cancel", json={}, headers={**headers, "Idempotency-Key": uid()}
    )
    assert response.json()["state"] == "CANCEL_REQUESTED"
    assert (
        f["client"]
        .post(path + "/recover", json={}, headers={**headers, "Idempotency-Key": uid()})
        .status_code
        == 409
    )
    with f["db"].connect() as conn:
        assert conn.execute(select(jobs.c.lease_token)).scalar() == "fixture-lease"


@pytest.mark.parametrize(
    "field,value",
    [
        ("candidate_digest", "e" * 64),
        ("policy_digest", "f" * 64),
        ("evidence_digest", "e" * 64),
        ("generation", 2),
        ("expires_at", 1),
    ],
)
def test_stale_approval_binding_rejected(fixture, field, value):
    f = fixture
    task_id, headers = submit(f)
    binding = ready(f, task_id)
    binding[field] = value
    response = f["client"].post(
        f["base"] + f"/tasks/{task_id}/approve",
        json=binding,
        headers={**headers, "Idempotency-Key": uid()},
    )
    assert response.status_code == 409
    with f["db"].connect() as conn:
        assert conn.execute(select(approvals)).all() == []


def test_approval_receipt_reads_never_create_or_replay_approval(fixture, monkeypatch):
    f = fixture
    task_id, headers = submit(f)
    binding = ready(f, task_id)
    key = uid()
    path = f["base"] + f"/tasks/{task_id}/approval-receipts/"
    writes = []

    def observe(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    def snapshot():
        with f["db"].connect() as conn:
            return {
                table.name: conn.execute(select(table)).all()
                for table in (tasks, approvals, receipts, audit)
            }

    event.listen(f["db"], "before_cursor_execute", observe)
    try:
        before = snapshot()
        for lookup in (key, key, headers["Idempotency-Key"]):
            response = f["client"].get(path + lookup)
            assert response.status_code == 200 and response.json() == {"found": False}
        assert f["client"].get(f["base"] + f"/tasks/{task_id}").status_code == 200
        assert snapshot() == before and writes == []
    finally:
        event.remove(f["db"], "before_cursor_execute", observe)

    response = f["client"].post(
        f["base"] + f"/tasks/{task_id}/approve",
        json=binding,
        headers={**headers, "Idempotency-Key": key},
    )
    assert response.status_code == 200
    monkeypatch.setattr("intelligenceai.web.service.now", lambda: binding["expires_at"] + 1)
    writes.clear()
    event.listen(f["db"], "before_cursor_execute", observe)
    try:
        before = snapshot()
        for _ in range(3):
            response = f["client"].get(path + key)
            assert response.status_code == 200
            assert response.json() == {
                "found": True,
                "result": {
                    "id": task_id,
                    "review_approved": True,
                    "execution_enabled": False,
                },
            }
        assert snapshot() == before and writes == []
    finally:
        event.remove(f["db"], "before_cursor_execute", observe)


def test_approval_receipt_authorizes_project_task_actor_and_current_role(fixture):
    f = fixture
    task_id, headers = submit(f)
    binding = ready(f, task_id)
    key = uid()
    path = f["base"] + f"/tasks/{task_id}/approval-receipts/{key}"
    assert (
        f["client"]
        .post(
            f["base"] + f"/tasks/{task_id}/approve",
            json=binding,
            headers={**headers, "Idempotency-Key": key},
        )
        .status_code
        == 200
    )
    assert f["client"].get(path.replace(f["project"], f["other"])).status_code == 404
    assert f["client"].get(path.replace(task_id, uid())).status_code == 404
    assert f["client"].get(path + ("x" * 129)).status_code == 400
    f["sign_in"](f["viewer"])
    assert f["client"].get(path).status_code == 403
    f["sign_in"](f["bob"])
    assert f["client"].get(path).status_code == 404
    with f["db"].begin() as conn:
        conn.execute(
            insert(members).values(project_id=f["project"], user_id=f["bob"], role="approver")
        )
    assert f["client"].get(path).json() == {"found": False}
    f["sign_in"](f["alice"])
    with f["db"].begin() as conn:
        conn.execute(update(members).where(members.c.user_id == f["alice"]).values(role="revoked"))
    assert f["client"].get(path).status_code == 404
    f["client"].cookies.clear()
    assert f["client"].get(path).status_code == 401


def test_approval_no_effect_dispatch_rechecks_candidate_and_permission(fixture):
    f = fixture
    task_id, headers = submit(f)
    binding = ready(f, task_id)
    response = f["client"].post(
        f["base"] + f"/tasks/{task_id}/approve",
        json=binding,
        headers={**headers, "Idempotency-Key": uid()},
    )
    assert response.status_code == 200
    assert response.json()["execution_enabled"] is False
    with pytest.raises(Problem) as caught:
        f["service"].dispatch(f["alice"], f["project"], task_id)
    assert caught.value.code == "runner_and_external_effects_disabled"
    with f["db"].begin() as conn:
        conn.execute(update(tasks).where(tasks.c.id == task_id).values(candidate_digest="d" * 64))
    with pytest.raises(Problem) as caught:
        f["service"].dispatch(f["alice"], f["project"], task_id)
    assert caught.value.code == "approval_binding_changed"
    with f["db"].begin() as conn:
        conn.execute(update(members).where(members.c.user_id == f["alice"]).values(role="viewer"))
    with pytest.raises(Problem) as caught:
        f["service"].dispatch(f["alice"], f["project"], task_id)
    assert caught.value.status == 403


def test_no_verified_evidence_no_approval_no_http_dispatch(fixture):
    f = fixture
    task_id, headers = submit(f)
    binding = ready(f, task_id)
    with f["db"].begin() as conn:
        conn.execute(update(tasks).where(tasks.c.id == task_id).values(evidence_verified=False))
    assert (
        f["client"]
        .post(
            f["base"] + f"/tasks/{task_id}/approve",
            json=binding,
            headers={**headers, "Idempotency-Key": uid()},
        )
        .status_code
        == 409
    )
    assert (
        f["client"]
        .post(f["base"] + f"/tasks/{task_id}/dispatch", json={}, headers=headers)
        .status_code
        == 404
    )


def test_sensitive_input_rejected_before_storage_and_validation_never_echoes(fixture):
    f = fixture
    headers = f["sign_in"](f["alice"])
    credential = "IAI_TEST_" + "SECRET_DONOTPERSIST"
    response = f["client"].post(
        f["base"] + "/tasks", json={**INPUT, "request": credential}, headers=headers
    )
    assert response.status_code == 422 and credential not in response.text
    with f["db"].begin() as conn:
        f["service"].record(
            conn, f["project"], f["alice"], "fixture.redaction", {"text": credential}
        )
        assert credential not in json.dumps(conn.execute(select(audit.c.detail)).scalar())
        assert conn.execute(select(tasks)).all() == []


def test_xss_is_data_and_artifacts_plain_text(fixture):
    f = fixture
    task_id, headers = submit(f)
    artifact_id = uid()
    content = '<svg onload="alert(1)"><script>unsafe()</script></svg>'
    with f["db"].begin() as conn:
        conn.execute(
            insert(artifacts).values(
                id=artifact_id,
                task_id=task_id,
                name="xss.svg",
                kind="text",
                content=content,
                digest=digest(content),
            )
        )
    response = f["client"].get(f["base"] + f"/tasks/{task_id}/artifacts/{artifact_id}")
    assert response.text == content
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert (
        f["client"]
        .post(
            f["base"] + "/tasks",
            json={**INPUT, "title": '<img src=x onerror="alert(1)">'},
            headers={**headers, "Idempotency-Key": uid()},
        )
        .status_code
        == 201
    )


def test_session_expiry_active_user_revoke_and_logout(fixture):
    f = fixture
    headers = f["sign_in"](f["alice"])
    assert f["client"].get("/api/session").status_code == 200
    old_cookie = f["client"].cookies.get("iai_test_session")
    assert f["client"].post("/api/logout", json={}, headers=headers).status_code == 200
    f["client"].cookies.clear()
    f["client"].cookies.set("iai_test_session", old_cookie)
    assert f["client"].get("/api/session").status_code == 401
    f["sign_in"](f["alice"])
    with f["db"].begin() as conn:
        conn.execute(update(sessions).values(expires_at=now() - 1))
    assert f["client"].get("/api/session").status_code == 401
    f["sign_in"](f["alice"])
    with f["db"].begin() as conn:
        conn.execute(update(users).where(users.c.id == f["alice"]).values(active=False))
    assert f["client"].get("/api/session").status_code == 401


def test_production_rejects_test_auth_and_sqlite():
    config = Settings(
        "sqlite://", "http://testserver", "https://issuer.example", "client", "unused", ".", False
    )
    with pytest.raises(ValueError):
        create_app(config)
    with pytest.raises(ValueError):
        engine("sqlite://")


def test_public_demo_has_no_private_write_or_auth_bypass(monkeypatch, tmp_path):
    monkeypatch.setenv("IAI_STATIC_DIR", str(tmp_path))
    monkeypatch.setenv("IAI_PUBLIC_ORIGIN", ORIGIN)
    (tmp_path / "index.html").write_text("<html>synthetic demo</html>")
    with TestClient(public_demo_app()) as client:
        assert client.get("/demo").status_code == 200
        assert client.get("/auth/login").status_code == 503
        assert client.get("/api/session").status_code == 404
        assert client.post("/api/projects", json={}, headers={"Origin": ORIGIN}).status_code == 405
        assert client.get("/assets/missing.js").status_code == 404
        assert "set-cookie" not in client.get("/demo").headers


def test_oidc_state_pkce_and_failed_callback_do_not_enroll(fixture, monkeypatch):
    f = fixture
    from authlib.integrations.httpx_client import AsyncOAuth2Client
    from httpx import Request, Response

    async def metadata(_self, *args, **kwargs):
        return Response(
            200,
            request=Request("GET", "https://issuer.example/.well-known/openid-configuration"),
            json={
                "issuer": "https://issuer.example",
                "authorization_endpoint": "https://issuer.example/authorize",
                "token_endpoint": "https://issuer.example/token",
                "jwks_uri": "https://issuer.example/jwks",
                "id_token_signing_alg_values_supported": ["RS256"],
            },
        )

    monkeypatch.setattr(AsyncOAuth2Client, "request", metadata)
    response = f["client"].get("/auth/login", follow_redirects=False)
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] and query["nonce"] and query["code_challenge"]
    assert query["redirect_uri"] == [ORIGIN + "/auth/callback"]
    response = f["client"].get("/auth/callback?code=bad&state=wrong", follow_redirects=False)
    assert response.status_code == 401
    assert response.json() == {"error": "oidc_sign_in_failed"}
    assert f["client"].get("/api/session").status_code == 401
    with f["db"].connect() as conn:
        assert len(conn.execute(select(users)).all()) == 3


def test_whitespace_and_unbounded_ttl_rejected(fixture):
    f = fixture
    headers = f["sign_in"](f["alice"])
    assert (
        f["client"]
        .post(f["base"] + "/tasks", json={**INPUT, "title": "   "}, headers=headers)
        .status_code
        == 422
    )
    task_id, headers = submit(f)
    binding = ready(f, task_id)
    binding["expires_at"] = now() + 901
    assert (
        f["client"]
        .post(
            f["base"] + f"/tasks/{task_id}/approve",
            json=binding,
            headers={**headers, "Idempotency-Key": uid()},
        )
        .status_code
        == 409
    )


def test_safe_task_contract_never_creates_command():
    data = TaskInput(**{**INPUT, "request": "$(curl http://169.254.169.254); /bin/sh"})
    assert data.request.startswith("$(")
    from intelligenceai.web.contracts import preview

    plan = preview(data)
    assert "argv" not in json.dumps(plan)
    assert plan["execution_enabled"] is False
    with pytest.raises(ValueError):
        ApprovalInput(
            candidate_digest="a" * 64,
            policy_digest="b" * 64,
            evidence_digest="c" * 64,
            destination_id="https://evil.example",
            generation=1,
            expires_at=now() + 10,
        )


@pytest.mark.parametrize(
    "case",
    ["valid", "bad_nonce", "bad_audience", "bad_issuer", "expired", "forged", "unprovisioned"],
)
def test_signed_offline_oidc_claims_and_session_rotation(fixture, monkeypatch, case):
    from authlib.integrations.httpx_client import AsyncOAuth2Client
    from httpx import Request, Response
    from joserfc import jwt
    from joserfc.jwk import RSAKey

    f = fixture
    key = RSAKey.generate_key(2048)
    key.ensure_kid()
    nonce = ""

    async def transport(_self, method, url, **kwargs):
        if "openid-configuration" in url:
            body = {
                "issuer": "https://issuer.example",
                "authorization_endpoint": "https://issuer.example/authorize",
                "token_endpoint": "https://issuer.example/token",
                "jwks_uri": "https://issuer.example/jwks",
                "id_token_signing_alg_values_supported": ["RS256"],
            }
        elif url.endswith("/jwks"):
            body = {"keys": [key.as_dict(private=False)]}
        elif url.endswith("/token"):
            claims = {
                "iss": "https://evil.example" if case == "bad_issuer" else "https://issuer.example",
                "sub": "unknown" if case == "unprovisioned" else "alice",
                "aud": "wrong" if case == "bad_audience" else "client",
                "nonce": "wrong" if case == "bad_nonce" else nonce,
                "iat": now() - 2000 if case == "expired" else now(),
                "exp": now() - 1000 if case == "expired" else now() + 300,
            }
            signed = jwt.encode(
                {"alg": "RS256", "kid": key.kid},
                claims,
                RSAKey.generate_key(2048) if case == "forged" else key,
            )
            body = {"access_token": "synthetic-unused", "token_type": "Bearer", "id_token": signed}
        else:
            raise AssertionError("unexpected OAuth URL")
        return Response(200, json=body, request=Request(method, url))

    monkeypatch.setattr(AsyncOAuth2Client, "request", transport)
    response = f["client"].get("/auth/login", follow_redirects=False)
    old_cookie = f["client"].cookies.get("iai_test_session")
    query = parse_qs(urlsplit(response.headers["location"]).query)
    nonce = query["nonce"][0]
    result = f["client"].get(
        "/auth/callback",
        params={"code": "synthetic-code", "state": query["state"][0]},
        follow_redirects=False,
    )
    if case == "valid":
        assert result.status_code == 303, result.text
        assert f["client"].get("/api/session").json()["user"]["id"] == f["alice"]
        assert f["client"].cookies.get("iai_test_session") != old_cookie
        with f["db"].connect() as conn:
            assert (
                conn.execute(
                    select(sessions.c.revoked).where(
                        sessions.c.token_hash == token_hash(old_cookie)
                    )
                ).scalar()
                is True
            )
    else:
        assert result.status_code == 401
        assert f["client"].get("/api/session").status_code == 401


def test_empty_mutation_body_does_not_accept_authority_fields(fixture):
    f = fixture
    task_id, headers = submit(f)
    for action in ["cancel", "recover", "reject"]:
        response = f["client"].post(
            f["base"] + f"/tasks/{task_id}/{action}",
            json={"principal": "root"},
            headers={**headers, "Idempotency-Key": uid()},
        )
        assert response.status_code == 422


def test_safe_exception_boundary_never_logs_raw_secrets(capsys):
    from intelligenceai.web.errors import SafeErrors

    credential = "IAI_TEST_" + "SECRET_EXCEPTION"

    async def fail(scope, receive, send):
        raise RuntimeError(credential)

    client = TestClient(SafeErrors(fail))
    response = client.get("/")
    client.close()
    assert response.status_code == 503
    assert response.json() == {"error": "service_unavailable"}
    assert credential not in capsys.readouterr().err


def test_postgres_concurrent_admission_has_one_durable_receipt(fixture):
    f = fixture
    if f["db"].dialect.name != "postgresql":
        pytest.skip(
            "requires actual loopback PostgreSQL row locks; SQLite is not concurrency evidence"
        )
    service = Service(f["db"])
    key = uid()
    data = TaskInput(**INPUT)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda _: service.submit(f["alice"], f["project"], key, data), range(8))
        )
    assert len({result["id"] for result in results}) == 1
    with f["db"].connect() as conn:
        assert len(conn.execute(select(jobs).where(jobs.c.task_id == results[0]["id"])).all()) == 1
    # A separate engine/pool observes committed state and the same idempotent result.
    reopened = engine(str(f["db"].url.render_as_string(hide_password=False)), testing=True)
    try:
        assert Service(reopened).submit(f["alice"], f["project"], key, data) == results[0]
    finally:
        reopened.dispose()
