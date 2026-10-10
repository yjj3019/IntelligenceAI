"""Real loopback HTTP/OIDC/API/supervisor regression; no installed browser or live model."""

import socket
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

import httpx
import uvicorn
from support import web_fixture

from intelligenceai.web.store import uid


def test_signed_loopback_issuer_durable_admission_and_core_receipt(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    if not (root / "web" / "dist" / "index.html").exists():
        pytest.skip("build the frontend before running the loopback fullstack fixture")
    directory = root / ".tools" / "fs" / uid().replace("-", "")[:8]
    directory.mkdir(parents=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    monkeypatch.setattr(web_fixture, "ORIGIN", origin)
    monkeypatch.setattr(web_fixture, "ISSUER", origin + "/oidc")
    server = uvicorn.Server(
        uvicorn.Config(
            web_fixture.browser_app(directory),
            host="127.0.0.1",
            port=port,
            access_log=False,
            log_level="critical",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started
        with httpx.Client(
            base_url=origin, follow_redirects=True, trust_env=False, timeout=20
        ) as client:
            assert client.get("/api/projects").status_code == 401
            assert client.get("/auth/login").status_code == 200
            session = client.get("/api/session").json()
            assert session["user"]["name"] == "LOCAL TEST USER"
            project = client.get("/api/projects").json()[0]["id"]
            base = f"/api/projects/{project}"
            headers = {"Origin": origin, "X-CSRF-Token": session["csrf"], "Idempotency-Key": uid()}
            payload = {
                "title": "Owned fullstack fixture",
                "request": "Synthetic static configuration review",
                "profile": "json-review",
            }
            saved = client.post(base + "/tasks", json=payload, headers=headers)
            assert saved.status_code == 201
            tid = saved.json()["id"]
            assert client.post(base + "/tasks", json=payload, headers=headers).json()["id"] == tid
            task_path = base + "/tasks/" + tid
            for path in [task_path, task_path + "/events", task_path + "/logs"]:
                assert client.get(path).status_code == 200
            assert client.get(task_path).json()["runs"] == []
            queued = client.post(
                task_path + "/run-fixture", json={}, headers={**headers, "Idempotency-Key": uid()}
            )
            assert queued.json()["state"] == "QUEUED"
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                task = client.get(task_path).json()
                if task["state"] in {"READY_FOR_APPROVAL", "NEEDS_RECONCILIATION", "BLOCKED"}:
                    break
                time.sleep(0.1)
            assert task["state"] == "READY_FOR_APPROVAL", task["state"]
            receipt = task["runs"][0]["receipt"]
            assert receipt["live_model"] == "NOTRUN" and receipt["os_sandbox"] == "UNVERIFIED"
            assert len(receipt["invocations"]) == 1 and task["model_calls"] == 0
            artifact = client.get(task_path + "/artifacts/" + task["artifacts"][0]["id"])
            assert artifact.headers["content-type"].startswith("text/plain")
            assert artifact.text == '{"enabled":true,"version":42}\n'
            details = client.get(base).json()
            binding = {
                key: task[key]
                for key in ["candidate_digest", "evidence_digest", "destination_id", "generation"]
            }
            binding.update(
                policy_digest=details["policy_digest"], expires_at=int(time.time()) + 600
            )
            approval = client.post(
                task_path + "/approve", json=binding, headers={**headers, "Idempotency-Key": uid()}
            )
            assert approval.status_code == 200 and approval.json()["execution_enabled"] is False
            assert client.get(task_path).json()["runs"] == task["runs"]
            assert client.post("/api/logout", json={}, headers=headers).status_code == 200
            assert client.get(task_path).status_code == 401
    finally:
        server.should_exit = True
        thread.join(timeout=100)
        assert not thread.is_alive(), (
            "owned loopback fixture did not stop within its bounded child deadline"
        )
