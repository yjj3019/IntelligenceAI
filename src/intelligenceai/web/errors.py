"""Fail closed without writing raw exceptions, SQL parameters or credentials to logs."""

from starlette.responses import JSONResponse


class SafeErrors:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False

        async def guarded_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, guarded_send)
        except Exception:
            if not started:
                await JSONResponse(
                    {"error": "service_unavailable"},
                    status_code=503,
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
                )(scope, receive, send)
            # Never append exception details to a response already in flight.
