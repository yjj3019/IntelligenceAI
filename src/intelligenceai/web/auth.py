"""Opaque server sessions and Authlib OIDC authorization-code + PKCE flow."""

import copy
import hashlib
import secrets
from http.cookies import SimpleCookie

from sqlalchemy import insert, select, update

from intelligenceai.web.service import session_data
from intelligenceai.web.store import now, sessions


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class ServerSessions:
    def __init__(self, app, db, secure=True):
        self.app, self.db, self.secure = app, db, secure
        self.cookie = "__Host-iai_session" if secure else "iai_test_session"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        cookies = SimpleCookie()
        try:
            cookies.load(headers.get(b"cookie", b"").decode("latin1"))
            token = cookies[self.cookie].value if self.cookie in cookies else ""
        except Exception:
            token = ""
        row = None
        if 20 <= len(token) <= 128:
            with self.db.connect() as conn:
                row = (
                    conn.execute(
                        select(sessions).where(
                            sessions.c.token_hash == token_hash(token),
                            sessions.c.expires_at > now(),
                            sessions.c.revoked.is_(False),
                        )
                    )
                    .mappings()
                    .first()
                )
        original = copy.deepcopy(row["data"]) if row else None
        scope["session"] = copy.deepcopy(original) if original else session_data()

        async def wrapped_send(message):
            nonlocal token
            if message["type"] == "http.response.start":
                changed = scope["session"] != original
                rotate = scope.get("rotate_session", False)
                logout = scope.get("logout_session", False)
                set_cookie = False
                with self.db.begin() as conn:
                    if row and (rotate or logout):
                        conn.execute(
                            update(sessions)
                            .where(sessions.c.token_hash == row["token_hash"])
                            .values(revoked=True)
                        )
                    if not logout and rotate:
                        token = secrets.token_urlsafe(32)
                        conn.execute(
                            insert(sessions).values(
                                token_hash=token_hash(token),
                                data=scope["session"],
                                expires_at=now() + 3600,
                            )
                        )
                        set_cookie = True
                    elif row and changed and not logout:
                        # Concurrent callbacks cannot overwrite newer state or resurrect logout.
                        conn.execute(
                            update(sessions)
                            .where(
                                sessions.c.token_hash == row["token_hash"],
                                sessions.c.version == row["version"],
                                sessions.c.revoked.is_(False),
                            )
                            .values(data=scope["session"], version=row["version"] + 1)
                        )
                if set_cookie or logout:
                    cookie = SimpleCookie()
                    cookie[self.cookie] = "" if logout else token
                    cookie[self.cookie]["path"] = "/"
                    cookie[self.cookie]["httponly"] = True
                    cookie[self.cookie]["samesite"] = "Lax"
                    cookie[self.cookie]["max-age"] = "0" if logout else "3600"
                    if self.secure:
                        cookie[self.cookie]["secure"] = True
                    message["headers"].append(
                        (b"set-cookie", cookie.output(header="").strip().encode("latin1"))
                    )
            await send(message)

        await self.app(scope, receive, wrapped_send)
