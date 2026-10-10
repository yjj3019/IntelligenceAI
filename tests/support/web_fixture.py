"""Explicit loopback-only browser fixture. NEVER included in deployment images.

Ephemeral signing key and users; exercises the real OIDC client against a synthetic issuer.
This is not validation of an external OIDC provider, PostgreSQL, model or sandbox.
"""

import base64
import hashlib
import secrets
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from joserfc import jwt
from joserfc.jwk import RSAKey
from sqlalchemy import insert, select, update

from intelligenceai.web.app import create_app
from intelligenceai.web.config import Settings
from intelligenceai.web.contracts import TaskInput
from intelligenceai.web.runner import Runner
from intelligenceai.web.service import Service, bootstrap
from intelligenceai.web.store import (
    engine,
    execution_grants,
    jobs,
    members,
    metadata,
    now,
    projects,
    tasks,
    uid,
    users,
)
from intelligenceai.web.vendor_runner import ApprovedFixtureRunner

ORIGIN = "http://127.0.0.1:4173"
ISSUER = ORIGIN + "/oidc"


def test_provider(client_value):
    provider = FastAPI(docs_url=None, openapi_url=None)
    key = RSAKey.generate_key(2048)
    key.ensure_kid()
    codes = {}

    @provider.get("/.well-known/openid-configuration")
    def discovery():
        return {
            "issuer": ISSUER,
            "authorization_endpoint": ISSUER + "/authorize",
            "token_endpoint": ISSUER + "/token",
            "jwks_uri": ISSUER + "/jwks",
            "response_types_supported": ["code"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic"],
            "code_challenge_methods_supported": ["S256"],
        }

    @provider.get("/jwks")
    def jwks():
        return {"keys": [key.as_dict(private=False)]}

    @provider.get("/authorize")
    def authorize(request: Request):
        query = request.query_params
        if (
            query.get("redirect_uri") != ORIGIN + "/auth/callback"
            or query.get("client_id") != "local-browser-fixture"
            or query.get("code_challenge_method") != "S256"
            or not query.get("nonce")
        ):
            return JSONResponse({"error": "invalid_request"}, 400)
        code = secrets.token_urlsafe(32)
        codes[code] = {
            "nonce": query["nonce"],
            "challenge": query["code_challenge"],
            "expires": now() + 60,
        }
        return RedirectResponse(
            ORIGIN + "/auth/callback?" + urlencode({"code": code, "state": query["state"]})
        )

    @provider.post("/token")
    async def token(request: Request):
        data = await request.form()
        expected = (
            "Basic " + base64.b64encode(("local-browser-fixture:" + client_value).encode()).decode()
        )
        receipt = codes.pop(str(data.get("code", "")), None)
        challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(str(data.get("code_verifier", "")).encode()).digest()
            )
            .decode()
            .rstrip("=")
        )
        if (
            request.headers.get("authorization") != expected
            or receipt is None
            or receipt["expires"] < now()
            or receipt["challenge"] != challenge
            or data.get("redirect_uri") != ORIGIN + "/auth/callback"
        ):
            return JSONResponse({"error": "invalid_grant"}, 400)
        identity = jwt.encode(
            {"alg": "RS256", "kid": key.kid},
            {
                "iss": ISSUER,
                "sub": "fixture-owner",
                "aud": "local-browser-fixture",
                "iat": now(),
                "exp": now() + 120,
                "nonce": receipt["nonce"],
                "name": "LOCAL TEST USER",
            },
            key,
        )
        return {
            "access_token": "synthetic-unused-token",
            "token_type": "Bearer",
            "id_token": identity,
        }

    return provider


def browser_app(directory):
    root = Path(__file__).resolve().parents[2]
    db = engine("sqlite:///" + str(Path(directory) / "fixture.sqlite3"), testing=True)
    metadata.create_all(db)
    owner, project = bootstrap(db, ISSUER, "fixture-owner", "LOCAL TEST USER", "LOCAL TEST FIXTURE")
    viewer = uid()
    with db.begin() as conn:
        conn.execute(
            insert(users).values(
                id=viewer, issuer=ISSUER, subject="fixture-viewer", name="FIXTURE VIEWER"
            )
        )
        conn.execute(insert(members).values(project_id=project, user_id=viewer, role="viewer"))
    service = Service(db)
    with db.begin() as conn:
        policy = conn.execute(
            select(projects.c.policy_digest).where(projects.c.id == project)
        ).scalar_one()
        conn.execute(
            insert(execution_grants).values(
                project_id=project,
                mode="fixed-fixture",
                policy_digest=policy,
                expires_at=now() + 3600,
            )
        )
    runner = Runner(db, Path(directory) / "runner")
    vendor = ApprovedFixtureRunner(db, Path(directory) / "vendor")
    for title in ["Held fixture task", "Failed fixture task", "Uncertain fixture task"]:
        result = service.submit(
            owner,
            project,
            uid(),
            TaskInput(
                title=title,
                request="Synthetic browser test only. No model execution.",
                profile="python-review",
            ),
        )
        with db.begin() as conn:
            if title.startswith("Failed"):
                conn.execute(update(tasks).where(tasks.c.id == result["id"]).values(state="FAILED"))
            if title.startswith("Uncertain"):
                conn.execute(
                    update(tasks).where(tasks.c.id == result["id"]).values(state="CANCEL_REQUESTED")
                )
                conn.execute(
                    update(jobs)
                    .where(jobs.c.task_id == result["id"])
                    .values(
                        state="LEASED", lease_token="synthetic-lease", lease_expires_at=now() - 1
                    )
                )
    client_value = secrets.token_urlsafe(32)
    console = create_app(
        Settings(
            "sqlite://",
            ORIGIN,
            ISSUER,
            "local-browser-fixture",
            client_value,
            str(root / "web" / "dist"),
            False,
        ),
        db=db,
        testing=True,
    )

    @asynccontextmanager
    async def lifecycle(_):
        stop = threading.Event()

        def work():
            while not stop.wait(0.25):
                try:
                    runner.run_once()
                    vendor.run_once()
                except Exception:
                    continue  # Fail closed; exception text is never exposed or stored.

        worker = threading.Thread(target=work, name="owned-fixture-worker")
        worker.start()
        try:
            yield
        finally:
            stop.set()
            worker.join()
            db.dispose()

    app = FastAPI(docs_url=None, openapi_url=None, lifespan=lifecycle)
    app.mount("/oidc", test_provider(client_value))
    app.mount("/", console)
    return app


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    (root / ".tools").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wf-", dir=root / ".tools") as directory:
        print("LOOPBACK TEST FIXTURE ONLY · ephemeral users/issuer/SQLite · no models")
        uvicorn.run(browser_app(directory), host="127.0.0.1", port=4173, access_log=False)
