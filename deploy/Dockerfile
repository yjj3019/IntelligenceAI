# Build recipe only. No cloud account, database or deployment is created.
FROM node:24.15.0-bookworm-slim AS frontend
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts
COPY web/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.11.11 AS uv
FROM python:3.14-slim-bookworm AS app
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ ./src/
RUN uv sync --frozen --extra web --no-dev --no-editable
COPY --from=frontend /build/web/dist/ ./static/
ENV IAI_STATIC_DIR=/app/static IAI_LISTEN_HOST=0.0.0.0
USER 10001:10001
EXPOSE 8080
CMD ["/app/.venv/bin/python", "-m", "intelligenceai.web.serve"]
