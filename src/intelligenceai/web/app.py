import json
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from authlib.integrations.starlette_client import OAuth
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from starlette.middleware.trustedhost import TrustedHostMiddleware

from intelligenceai.isolation_contracts import live_readiness
from intelligenceai.security import clean
from intelligenceai.web.auth import ServerSessions
from intelligenceai.web.config import Settings
from intelligenceai.web.contracts import ApprovalInput, EmptyInput, MemberInput, TaskInput, preview
from intelligenceai.web.errors import SafeErrors
from intelligenceai.web.pc_contracts import (
    PC_ROUTES,
    AttemptInput,
    ConfirmInput,
    ExchangeInput,
    PairInput,
    ResultInput,
)
from intelligenceai.web.pc_service import PCs
from intelligenceai.web.service import Problem, Service, session_data
from intelligenceai.web.store import engine, execution_grants, now, users

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'self'"
)


def static_routes(app, static_dir):
    root = Path(static_dir).resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def static(path: str):
        if path.startswith(("api/", "auth/")):
            raise Problem(404, "route_not_found")
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise Problem(404, "route_not_found")
        allowed = path in {"index.html", "fonts.css"} or (
            path.startswith("assets/") and target.suffix in {".js", ".css"}
        )
        if path and target.is_file() and allowed:
            return FileResponse(target)
        if path.startswith("assets/") or "." in Path(path).name:
            raise Problem(404, "asset_not_found")
        if not (root / "index.html").is_file():
            raise Problem(503, "frontend_build_required")
        return FileResponse(root / "index.html")


def boundary(app, origin, *, secure):
    @app.exception_handler(Problem)
    async def problem(_, exc):
        return JSONResponse({"error": exc.code}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(_, exc):
        # Never echo input values, raw validation messages or credentials.
        return JSONResponse({"error": "invalid_request"}, status_code=422)

    @app.middleware("http")
    async def protections(request, call_next):
        if request.headers.get("host", "").lower() != urlsplit(origin).netloc.lower():
            response = JSONResponse({"error": "host_rejected"}, status_code=400)
        elif request.headers.get("origin") not in {None, origin}:
            response = JSONResponse({"error": "origin_rejected"}, status_code=403)
        elif (
            request.method not in {"GET", "HEAD"}
            and (
                request.headers.get("origin") != origin
                or request.headers.get("sec-fetch-site") not in {None, "same-origin"}
            )
            and request.url.path not in PC_ROUTES
        ):
            response = JSONResponse({"error": "same_origin_required"}, status_code=403)
        elif (
            request.headers.get("content-length", "0").isdigit()
            and int(request.headers.get("content-length", "0")) > 16384
        ):
            response = JSONResponse({"error": "request_too_large"}, status_code=413)
        elif secure and request.url.scheme != "https":
            response = JSONResponse({"error": "https_required"}, status_code=400)
        else:
            # Bound chunked bodies too, before parsing. Only small JSON mutations are accepted.
            if request.method not in {"GET", "HEAD"}:
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 16384:
                        response = JSONResponse({"error": "request_too_large"}, status_code=413)
                        break
                else:
                    request._body = bytes(body)
                    response = await call_next(request)
            else:
                response = await call_next(request)
        response.headers.update(
            {
                "Content-Security-Policy": CSP,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            }
        )
        if secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(origin).hostname])


def create_app(settings: Settings, *, db=None, testing=False):
    if not testing and (not settings.secure or not settings.origin.startswith("https://")):
        raise ValueError("production requires HTTPS secure sessions")
    db = db if db is not None else engine(settings.database_url, testing=testing)
    if not testing and db.dialect.name != "postgresql":
        raise ValueError("production requires PostgreSQL")
    app = FastAPI(title="IntelligenceAI private console", docs_url=None, redoc_url=None)
    service = Service(db)
    pcs = PCs(db, testing=testing)
    app.state.service = service
    oauth = OAuth()
    oauth.register(
        "oidc",
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        server_metadata_url=settings.issuer + "/.well-known/openid-configuration",
        client_kwargs={"scope": "openid profile", "code_challenge_method": "S256"},
    )

    def actor(request):
        user_id = request.session.get("user_id")
        with db.connect() as conn:
            row = (
                conn.execute(select(users).where(users.c.id == user_id, users.c.active.is_(True)))
                .mappings()
                .first()
            )
        if row is None:
            raise Problem(401, "sign_in_required")
        return dict(row)

    def mutation(request):
        user = actor(request)
        supplied = request.headers.get("x-csrf-token", "")
        if not supplied or not secrets.compare_digest(supplied, request.session.get("csrf", "")):
            raise Problem(403, "csrf_rejected")
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise Problem(415, "json_required")
        return user["id"], request.headers.get("idempotency-key", "")

    def pc_token(request):
        # Cookie/session/CSRF authority never substitutes for a runner capability.
        value = request.headers.get("authorization", "")
        if request.headers.get("origin") or request.headers.get("sec-fetch-site"):
            raise Problem(403, "pc_machine_client_required")
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise Problem(415, "json_required")
        token = value.removeprefix("Bearer ")
        if (
            value == token
            or len(token) != 43
            or not all(char.isascii() and (char.isalnum() or char in "_-") for char in token)
        ):
            raise Problem(401, "pc_authorization_required")
        return token

    @app.get("/api/projects/{project_id}/pcs")
    def pc_list(request: Request, project_id: str):
        return pcs.list(actor(request)["id"], project_id)

    @app.post("/api/projects/{project_id}/pcs/pair")
    def pc_pair(request: Request, project_id: str, data: PairInput):
        user, key = mutation(request)
        return pcs.pair(user, project_id, key, data)

    @app.post("/api/projects/{project_id}/pcs/{runner_id}/confirm")
    def pc_confirm(request: Request, project_id: str, runner_id: str, data: ConfirmInput):
        user, key = mutation(request)
        return pcs.change(user, project_id, runner_id, key, data, "confirm")

    @app.post("/api/projects/{project_id}/pcs/{runner_id}/revoke")
    def pc_revoke(request: Request, project_id: str, runner_id: str, data: EmptyInput):
        user, key = mutation(request)
        return pcs.change(user, project_id, runner_id, key, data, "revoke")

    @app.post("/api/pc/exchange")
    def pc_exchange(request: Request, data: ExchangeInput):
        return pcs.exchange(pc_token(request), data)

    @app.post("/api/pc/claim")
    def pc_claim(request: Request, data: EmptyInput):
        return pcs.claim(pc_token(request))

    @app.post("/api/pc/start")
    def pc_start(request: Request, data: AttemptInput):
        return pcs.start(pc_token(request), data)

    @app.post("/api/pc/heartbeat")
    def pc_heartbeat(request: Request, data: AttemptInput):
        return pcs.heartbeat(pc_token(request), data)

    @app.post("/api/pc/result")
    def pc_result(request: Request, data: ResultInput):
        return pcs.result(pc_token(request), data)

    @app.get("/healthz")
    def health():
        # No DB credentials, provider identities or server filesystem paths in readiness.
        with db.connect() as conn:
            conn.execute(select(users.c.id).limit(1))
        return {"status": "ok", "execution_enabled": False}

    @app.get("/auth/login")
    async def login(request: Request):
        request.session.clear()
        request.session.update(session_data())
        request.scope["rotate_session"] = True
        return await oauth.oidc.authorize_redirect(
            request, settings.origin + "/auth/callback", prompt="select_account"
        )

    @app.get("/auth/callback")
    async def callback(request: Request):
        try:
            token = await oauth.oidc.authorize_access_token(request)
            info = token.get("userinfo")
            if not info or info.get("iss", "").rstrip("/") != settings.issuer:
                raise ValueError("issuer mismatch")
            # Authlib verifies discovery keys, signature, audience, expiry, state and nonce.
            with db.connect() as conn:
                user_id = conn.execute(
                    select(users.c.id).where(
                        users.c.issuer == settings.issuer,
                        users.c.subject == info["sub"],
                        users.c.active.is_(True),
                    )
                ).scalar()
            if not user_id:
                raise ValueError("identity is not provisioned")
        except Exception:
            request.scope["logout_session"] = True
            request.session.clear()
            return JSONResponse({"error": "oidc_sign_in_failed"}, status_code=401)
        request.session.clear()
        request.session.update(session_data(user_id))
        request.scope["rotate_session"] = True
        return RedirectResponse("/app", status_code=303)

    @app.get("/api/session")
    def session(request: Request):
        user = actor(request)
        return {"user": {"id": user["id"], "name": user["name"]}, "csrf": request.session["csrf"]}

    @app.post("/api/logout")
    def logout(request: Request, data: EmptyInput):
        mutation(request)
        request.scope["logout_session"] = True
        request.session.clear()
        return {"signed_out": True}

    @app.get("/api/projects")
    def project_list(request: Request):
        return service.project_list(actor(request)["id"])

    @app.get("/api/projects/{project_id}")
    def project(request: Request, project_id: str):
        return service.project(actor(request)["id"], project_id)

    @app.get("/api/projects/{project_id}/connections")
    def connections(request: Request, project_id: str):
        with db.connect() as conn:
            project, _ = service.authorize(conn, actor(request)["id"], project_id)
            grant = (
                conn.execute(
                    select(execution_grants).where(execution_grants.c.project_id == project_id)
                )
                .mappings()
                .first()
            )
            fixture = bool(
                grant
                and grant["mode"] == "fixed-fixture"
                and grant["expires_at"] > now()
                and grant["policy_digest"] == project["policy_digest"]
            )
        return {
            "execution_enabled": False,
            "providers": "DISABLED",
            "sandbox": "UNVERIFIED",
            "runner": "FIXTURE_ONLY_CAPABILITY" if fixture else "NOT_CONFIGURED",
            "database": "POSTGRESQL" if db.dialect.name == "postgresql" else "TEST_FIXTURE_SQLITE",
            "external_effects": "DISABLED",
            "fixture_execution": "AUTHORIZED" if fixture else "DISABLED",
            "live_model": "NOTRUN",
            "provider_readiness": [
                live_readiness(provider, mode)
                for provider in ("claude", "codex", "grok", "gemini-cli", "antigravity")
                for mode in ("read_only", "write")
            ],
        }

    @app.post("/api/projects/{project_id}/preview")
    def plan(request: Request, project_id: str, data: TaskInput):
        user_id, _ = mutation(request)
        with db.connect() as conn:
            service.authorize(conn, user_id, project_id, {"owner", "operator"})
        return preview(data)

    @app.get("/api/projects/{project_id}/tasks")
    def task_list(request: Request, project_id: str):
        return service.task_list(actor(request)["id"], project_id)

    @app.post("/api/projects/{project_id}/tasks", status_code=201)
    def submit(request: Request, project_id: str, data: TaskInput):
        user_id, key = mutation(request)
        return service.submit(user_id, project_id, key, data)

    @app.get("/api/projects/{project_id}/tasks/{task_id}")
    def task(request: Request, project_id: str, task_id: str):
        return service.task(actor(request)["id"], project_id, task_id)

    from intelligenceai.web.cli_service import (
        ConsentInput as CLIConsentInput,
    )
    from intelligenceai.web.cli_service import (
        LocalCLI,
    )
    from intelligenceai.web.cli_service import (
        PrepareInput as CLIPrepareInput,
    )
    from intelligenceai.web.paid_admission import ConsentInput, PaidAdmission, QuoteInput

    local_cli = LocalCLI(db)

    @app.get("/api/projects/{project_id}/tasks/{task_id}/local-cli")
    def cli_status(request: Request, project_id: str, task_id: str):
        return local_cli.status(actor(request)["id"], project_id, task_id)

    @app.post("/api/projects/{project_id}/tasks/{task_id}/local-cli/prepare")
    def cli_prepare(request: Request, project_id: str, task_id: str, data: CLIPrepareInput):
        user_id, key = mutation(request)
        return local_cli.prepare(
            user_id, project_id, task_id, key, data, request.scope.get("server_session_hash")
        )

    @app.post("/api/projects/{project_id}/tasks/{task_id}/local-cli/approve")
    def cli_approve(request: Request, project_id: str, task_id: str, data: CLIConsentInput):
        user_id, key = mutation(request)
        return local_cli.approve(
            user_id, project_id, task_id, key, data, request.scope.get("server_session_hash")
        )

    paid_admission = PaidAdmission(db)

    @app.get("/api/projects/{project_id}/tasks/{task_id}/paid-review")
    def paid_status(request: Request, project_id: str, task_id: str):
        return paid_admission.status(
            actor(request)["id"], project_id, task_id, request.scope.get("server_session_hash")
        )

    @app.post("/api/projects/{project_id}/tasks/{task_id}/paid-review/quote")
    def paid_quote(request: Request, project_id: str, task_id: str, data: QuoteInput):
        user_id, key = mutation(request)
        return paid_admission.quote(
            user_id, project_id, task_id, key, data, request.scope.get("server_session_hash")
        )

    @app.post("/api/projects/{project_id}/tasks/{task_id}/paid-review/{action}")
    def paid_consent(
        request: Request, project_id: str, task_id: str, action: str, data: ConsentInput
    ):
        user_id, key = mutation(request)
        if action not in {"approve", "request"}:
            raise Problem(404, "action_not_available")
        return paid_admission.transition(
            user_id,
            project_id,
            task_id,
            key,
            data,
            request.scope.get("server_session_hash"),
            action,
        )

    @app.get("/api/projects/{project_id}/tasks/{task_id}/approval-receipts/{key}")
    def approval_receipt(request: Request, project_id: str, task_id: str, key: str):
        return service.approval_receipt(actor(request)["id"], project_id, task_id, key)

    @app.post("/api/projects/{project_id}/tasks/{task_id}/approve")
    def approve(request: Request, project_id: str, task_id: str, data: ApprovalInput):
        user_id, key = mutation(request)
        return service.approve(user_id, project_id, task_id, key, data)

    @app.post("/api/projects/{project_id}/tasks/{task_id}/{action}")
    def action(request: Request, project_id: str, task_id: str, action: str, data: EmptyInput):
        user_id, key = mutation(request)
        if action == "run-approved-fixture":
            return service.run_approved_fixture(
                user_id,
                project_id,
                task_id,
                key,
                session_hash=request.scope.get("server_session_hash"),
            )
        actions = {
            "cancel": service.cancel,
            "recover": service.recover,
            "reject": service.reject,
            "run-fixture": service.run_fixture,
        }
        if action not in actions:
            raise Problem(404, "action_not_available")
        return actions[action](user_id, project_id, task_id, key)

    @app.put("/api/projects/{project_id}/members")
    def member(request: Request, project_id: str, data: MemberInput):
        user_id, key = mutation(request)
        return service.member(user_id, project_id, key, data)

    @app.get("/api/projects/{project_id}/audit")
    def events(request: Request, project_id: str):
        return service.events(actor(request)["id"], project_id)

    @app.get("/api/projects/{project_id}/tasks/{task_id}/logs")
    def logs(request: Request, project_id: str, task_id: str):
        return service.events(actor(request)["id"], project_id, task_id=task_id)

    @app.get("/api/projects/{project_id}/tasks/{task_id}/events")
    def snapshot_event(request: Request, project_id: str, task_id: str):
        # One finite snapshot per reconnect: authorization and session rechecked every request.
        # No long-lived stream can keep receiving after membership/session revocation.
        result = service.task(actor(request)["id"], project_id, task_id)
        payload = json.dumps(clean(result), ensure_ascii=True)
        return Response(
            "retry: 5000\nevent: snapshot\ndata: " + payload + "\n\n",
            media_type="text/event-stream",
        )

    @app.get("/api/projects/{project_id}/tasks/{task_id}/artifacts/{artifact_id}")
    def artifact(request: Request, project_id: str, task_id: str, artifact_id: str):
        result = service.artifact(actor(request)["id"], project_id, task_id, artifact_id)
        # Always plain text. Never embed HTML/SVG or redirect to arbitrary signed URLs.
        return Response(
            clean(result["content"]),
            media_type="text/plain",
            headers={"Content-Disposition": 'attachment; filename="artifact.txt"'},
        )

    static_routes(app, settings.static_dir)
    boundary(app, settings.origin, secure=settings.secure)
    app.add_middleware(ServerSessions, db=db, secure=settings.secure)
    # Host validation must wrap sessions: rejected hosts never create sessions.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(settings.origin).hostname])
    if not testing:
        app.add_middleware(SafeErrors)
    return app


def production_app():
    try:
        return create_app(Settings.from_env())
    except Exception:
        raise RuntimeError("Web configuration unavailable; see deployment guide") from None


def public_demo_app():
    """Static-only hosting target. No private API, auth bypass, session or database."""
    import os

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    def health():
        return {"status": "ok", "mode": "synthetic-read-only-demo"}

    @app.get("/auth/login")
    def unavailable():
        raise Problem(503, "private_console_not_configured")

    static_routes(app, os.environ.get("IAI_STATIC_DIR", "web/dist-public"))
    boundary(app, os.environ.get("IAI_PUBLIC_ORIGIN", "http://127.0.0.1:4173"), secure=False)
    return app
