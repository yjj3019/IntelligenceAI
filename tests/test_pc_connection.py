"""Synthetic PC enrollment/outbound regressions. No real enrollment or provider calls."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

from sqlalchemy import delete, select, update
from test_local_cli import approve, setup
from test_web import fixture as shared_fixture

from intelligenceai.web.cli_worker import Worker
from intelligenceai.web.pc_client import API, Client
from intelligenceai.web.pc_contracts import AttemptInput
from intelligenceai.web.pc_service import PCs
from intelligenceai.web.service import Problem
from intelligenceai.web.store import (
    artifacts,
    audit,
    jobs,
    local_cli_profiles,
    local_cli_requests,
    members,
    now,
    pc_attempts,
    pc_runners,
    projects,
    receipts,
    sessions,
    tasks,
    uid,
    users,
)

fixture = shared_fixture
TOKEN = "s" * 43  # Fixed synthetic capability, never an actual account credential.


def machine(f, action, body=None, token=TOKEN):
    return f["client"].post(
        "/api/pc/" + action, json=body or {}, headers={"Authorization": "Bearer " + token}
    )


def enroll(f, runtime, headers, *, confirm=True, token=TOKEN):
    path = f["base"] + "/pcs"
    paired = f["client"].post(
        path + "/pair",
        json={"provider": runtime.provider},
        headers={**headers, "Idempotency-Key": uid()},
    )
    assert paired.status_code == 200, paired.text
    pair = paired.json()
    manifest = {
        "provider": runtime.provider,
        "version": "SYNTHETIC",
        "binary_digest": "b" * 64,
        "runtime_digest": runtime.runtime_digest,
        "scope": "FAKE_CLI_TEST_ONLY",
    }
    proposed = machine(f, "exchange", {"token": token, "manifest": manifest}, pair["pairing_code"])
    assert proposed.status_code == 200, proposed.text
    if confirm:
        response = f["client"].post(
            path + "/" + pair["id"] + "/confirm",
            json={"manifest_digest": proposed.json()["manifest_digest"]},
            headers={**headers, "Idempotency-Key": uid()},
        )
        assert response.status_code == 200, response.text
    return pair, proposed.json()


def queued(f, tmp_path):
    tid, path, headers, old, worker = setup(f, tmp_path)
    pair, _ = enroll(f, worker.runtime, headers)
    with f["db"].begin() as conn:
        conn.execute(delete(local_cli_requests).where(local_cli_requests.c.id == old["id"]))
        profile = conn.execute(
            select(pc_runners.c.profile_id).where(pc_runners.c.id == pair["id"])
        ).scalar_one()
    result = f["client"].post(
        path + "/prepare",
        json={"profile_id": profile},
        headers={**headers, "Idempotency-Key": uid()},
    )
    assert result.status_code == 200, result.text
    record = result.json()
    assert record["binding"]["runner_id"] == pair["id"]
    approve(f, path, headers, record)
    return tid, path, headers, record, worker.runtime, pair


def claim(f):
    response = machine(f, "claim")
    assert response.status_code == 200, response.text
    value = response.json()["attempt"]
    assert value is not None
    assert "session_hash" not in value and "argv" not in value and "path" not in value
    return value, {key: value[key] for key in AttemptInput.model_fields}


def report(bound, **values):
    return (
        bound
        | {
            "outcome": "COMPLETED",
            "text": "Synthetic device review",
            "cleanup_reported": True,
            "availability": "AVAILABLE",
            "input_tokens": 0,
            "output_tokens": 2,
        }
        | values
    )


def test_pairing_requires_owner_confirmation_and_only_hashes_are_stored(fixture, tmp_path):
    f = fixture
    _, _, headers, _, worker = setup(f, tmp_path)
    pair, proposed = enroll(f, worker.runtime, headers, confirm=False)
    assert machine(f, "claim").status_code == 403
    assert (
        machine(f, "exchange", {"token": TOKEN, "manifest": {}}, pair["pairing_code"]).status_code
        == 422
    )
    assert (
        machine(
            f,
            "exchange",
            {
                "token": TOKEN,
                "manifest": {
                    "provider": "codex",
                    "version": "SYNTHETIC",
                    "binary_digest": "b" * 64,
                    "runtime_digest": worker.runtime.runtime_digest,
                    "scope": "FAKE_CLI_TEST_ONLY",
                },
            },
            pair["pairing_code"],
        ).status_code
        == 401
    )
    with f["db"].connect() as conn:
        row = conn.execute(select(pc_runners)).mappings().one()
        assert row["pair_hash"] is None and row["token_hash"] != TOKEN
        stored = (
            repr(conn.execute(select(receipts)).mappings().all())
            + repr(conn.execute(select(audit)).mappings().all())
            + repr(row)
        )
        assert TOKEN not in stored and pair["pairing_code"] not in stored
    assert "token_hash" not in f["client"].get(f["base"] + "/pcs").text
    mismatch = f["client"].post(
        f["base"] + f"/pcs/{pair['id']}/confirm",
        json={"manifest_digest": "f" * 64},
        headers={**headers, "Idempotency-Key": uid()},
    )
    assert mismatch.status_code == 409
    for actor in (f["bob"], f["viewer"]):
        foreign = f["sign_in"](actor)
        response = f["client"].post(
            f["base"] + f"/pcs/{pair['id']}/confirm",
            json={"manifest_digest": proposed["manifest_digest"]},
            headers=foreign,
        )
        assert response.status_code in {403, 404}


@pytest.mark.parametrize("phase", ["PAIRING", "PENDING"])
def test_pairing_expiry_and_revocation(fixture, tmp_path, phase):
    f = fixture
    _, _, headers, _, worker = setup(f, tmp_path)
    if phase == "PENDING":
        pair, proposed = enroll(f, worker.runtime, headers, confirm=False)
        with f["db"].begin() as conn:
            conn.execute(update(pc_runners).values(expires_at=now() - 1))
        response = f["client"].post(
            f["base"] + f"/pcs/{pair['id']}/confirm",
            json={"manifest_digest": proposed["manifest_digest"]},
            headers={**headers, "Idempotency-Key": uid()},
        )
        assert response.status_code == 409
    else:
        paired = (
            f["client"]
            .post(
                f["base"] + "/pcs/pair",
                json={"provider": "codex"},
                headers={**headers, "Idempotency-Key": uid()},
            )
            .json()
        )
        with f["db"].begin() as conn:
            conn.execute(update(pc_runners).values(expires_at=now() - 1))
        manifest = {
            "provider": "codex",
            "version": "SYNTHETIC",
            "binary_digest": "b" * 64,
            "runtime_digest": worker.runtime.runtime_digest,
            "scope": "FAKE_CLI_TEST_ONLY",
        }
        assert (
            machine(
                f, "exchange", {"token": TOKEN, "manifest": manifest}, paired["pairing_code"]
            ).status_code
            == 409
        )


def test_pairing_receipt_retry_never_repeats_plaintext(fixture):
    f = fixture
    headers = f["sign_in"](f["alice"])
    first = (
        f["client"]
        .post(f["base"] + "/pcs/pair", json={"provider": "codex"}, headers=headers)
        .json()
    )
    second = (
        f["client"]
        .post(f["base"] + "/pcs/pair", json={"provider": "codex"}, headers=headers)
        .json()
    )
    assert first["id"] == second["id"] and first["pairing_code"] and second["pairing_code"] is None


def test_start_is_single_use_and_results_are_reports_and_idempotent(fixture, tmp_path):
    f = fixture
    tid, path, _, _, runtime, _ = queued(f, tmp_path)
    _, bound = claim(f)
    assert machine(f, "start", bound).status_code == 200
    assert machine(f, "start", bound).status_code == 409
    assert machine(f, "heartbeat", bound).json() == {"continue": True}
    value = report(bound, text="Synthetic result api_key=IAI_SYNTHETIC_SECRET_OUTPUT")
    first = machine(f, "result", value)
    assert first.status_code == 200, first.text
    assert first.json()["source"] == "USER_DEVICE_REPORT"
    assert first.json()["live_model"] == "NOTRUN"
    assert first.json()["local_termination_confirmed"] is False
    assert first.json()["device_cleanup_reported"] is True
    assert first.json()["usage"]["values"]["input_tokens"] == 0
    assert first.json()["cli_invocations"] is None and first.json()["model_calls"] is None
    assert machine(f, "result", value).json() == first.json()
    assert machine(f, "result", value | {"text": "Different"}).status_code == 409
    assert machine(f, "claim").json()["attempt"] is None
    with f["db"].connect() as conn:
        content = conn.execute(
            select(artifacts.c.content).where(artifacts.c.kind == "cli-result")
        ).scalar_one()
        assert "[REDACTED]" in content and "IAI_SYNTHETIC_SECRET_OUTPUT" not in content
    assert runtime.calls == 0
    f["sign_in"](f["bob"])
    assert f["client"].get(path).status_code == 404
    assert f["client"].get(f["base"] + f"/tasks/{tid}/logs").status_code == 404


@pytest.mark.parametrize(
    "change", ["session", "role", "user", "generation", "policy", "candidate", "profile", "expiry"]
)
def test_snapshot_and_authority_change_prevents_start(fixture, tmp_path, change):
    f = fixture
    tid, _, _, _, runtime, pair = queued(f, tmp_path)
    _, bound = claim(f)
    with f["db"].begin() as conn:
        if change == "session":
            conn.execute(update(sessions).values(revoked=True))
        elif change == "role":
            conn.execute(
                update(members).where(members.c.user_id == f["alice"]).values(role="revoked")
            )
        elif change == "user":
            conn.execute(update(users).where(users.c.id == f["alice"]).values(active=False))
        elif change == "generation":
            conn.execute(update(tasks).where(tasks.c.id == tid).values(generation=2))
        elif change == "policy":
            conn.execute(
                update(projects).where(projects.c.id == f["project"]).values(policy_digest="f" * 64)
            )
        elif change == "candidate":
            conn.execute(update(tasks).where(tasks.c.id == tid).values(candidate_digest="f" * 64))
        elif change == "profile":
            conn.execute(
                update(local_cli_profiles)
                .where(local_cli_profiles.c.metadata["runner_id"].as_string() == pair["id"])
                .values(active=False)
            )
        else:
            conn.execute(update(pc_attempts).values(expires_at=now() - 1))
    assert machine(f, "start", bound).status_code in {403, 404, 409}
    assert runtime.calls == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_id", "f" * 36),
        ("generation", 99),
        ("binding_digest", "f" * 64),
        ("lease", "f" * 64),
        ("attempt_id", "f" * 36),
    ],
)
def test_attempt_cannot_cross_bindings(fixture, tmp_path, field, value):
    f = fixture
    queued(f, tmp_path)
    _, bound = claim(f)
    assert machine(f, "start", bound | {field: value}).status_code in {404, 409}


@pytest.mark.parametrize(
    "field,value",
    [
        ("path", "../../outside"),
        ("actor_id", "forged"),
        ("project_id", "other"),
        ("argv", ["command"]),
        ("env", {"KEY": "value"}),
    ],
)
def test_machine_rejects_untrusted_commands_paths_and_principals(fixture, tmp_path, field, value):
    f = fixture
    queued(f, tmp_path)
    _, bound = claim(f)
    assert machine(f, "start", bound | {field: value}).status_code == 422
    assert machine(f, "result", report(bound) | {field: value}).status_code == 422


def test_machine_requires_bearer_never_cookie_or_browser_origin(fixture, tmp_path):
    f = fixture
    queued(f, tmp_path)
    assert f["client"].post("/api/pc/claim", json={}).status_code == 401
    assert machine(f, "claim", token="different-synthetic-" + "z" * 23).status_code in {401, 403}
    response = f["client"].post(
        "/api/pc/claim",
        json={},
        headers={"Origin": "http://testserver", "Authorization": "Bearer " + TOKEN},
    )
    assert response.status_code == 403
    assert (
        f["client"]
        .post(
            "/api/pc/claim",
            json={},
            headers={"Host": "attacker.example", "Authorization": "Bearer " + TOKEN},
        )
        .status_code
        == 400
    )
    assert (
        f["client"]
        .post("/api/pc/claim", content="x" * 16385, headers={"Authorization": "Bearer " + TOKEN})
        .status_code
        == 413
    )


def test_disconnect_stops_new_start_and_retains_unknown_lease(fixture, tmp_path):
    f = fixture
    tid, _, headers, _, runtime, pair = queued(f, tmp_path)
    _, bound = claim(f)
    result = f["client"].post(
        f["base"] + f"/pcs/{pair['id']}/revoke",
        json={},
        headers={**headers, "Idempotency-Key": uid()},
    )
    assert result.status_code == 200
    assert machine(f, "start", bound).status_code == 403
    assert machine(f, "claim").status_code == 403
    with f["db"].connect() as conn:
        assert conn.execute(select(local_cli_requests.c.state)).scalar_one() == "UNKNOWN"
        assert (
            conn.execute(select(jobs.c.lease_token).where(jobs.c.task_id == tid)).scalar_one()
            == bound["lease"]
        )
    assert runtime.calls == 0


def test_cancellation_is_requested_before_device_cleanup_report(fixture, tmp_path):
    f = fixture
    tid, _, headers, _, _, _ = queued(f, tmp_path)
    _, bound = claim(f)
    assert machine(f, "start", bound).status_code == 200
    response = f["client"].post(
        f["base"] + f"/tasks/{tid}/cancel", json={}, headers={**headers, "Idempotency-Key": uid()}
    )
    assert response.json()["state"] == "CANCEL_REQUESTED"
    assert machine(f, "heartbeat", bound).json()["continue"] is False
    assert machine(f, "result", report(bound)).status_code == 409
    assert machine(f, "result", report(bound, outcome="CANCELLED", text="")).status_code == 200
    assert f["client"].get(f["base"] + f"/tasks/{tid}").json()["state"] == "CANCELLED"
    again = f["client"].post(
        f["base"] + f"/tasks/{tid}/cancel", json={}, headers={**headers, "Idempotency-Key": uid()}
    )
    assert again.json()["state"] == "CANCELLED"
    with f["db"].connect() as conn:
        saved = conn.execute(select(local_cli_requests.c.result)).scalar_one()
        assert saved["scope"] == "PC_REPORTED" and saved["local_termination_confirmed"] is False


def test_expired_lease_stale_upload_does_not_replay(fixture, tmp_path):
    f = fixture
    tid, path, _, _, _, _ = queued(f, tmp_path)
    _, bound = claim(f)
    assert machine(f, "start", bound).status_code == 200
    with f["db"].begin() as conn:
        conn.execute(update(pc_attempts).values(expires_at=now() - 1))
    assert machine(f, "result", report(bound)).status_code == 409
    assert f["client"].get(path).json()["requests"][0]["state"] == "UNKNOWN"
    assert f["client"].get(f["base"] + f"/tasks/{tid}").json()["state"] == "BLOCKED"
    assert machine(f, "claim").json()["attempt"] is None
    with f["db"].connect() as conn:
        assert conn.execute(select(local_cli_requests.c.state)).scalar_one() == "UNKNOWN"


class FixtureAPI:
    def __init__(self, f, *, lose=None):
        self.f, self.lose = f, lose

    def call(self, action, data):
        response = machine(self.f, action, data)
        assert response.status_code == 200, response.text
        if action == self.lose:
            self.lose = None
            raise TimeoutError("synthetic response lost")
        return response.json()


def test_pc_client_runs_without_db_or_oidc_configuration_and_reuploads_only_result(
    fixture, tmp_path, monkeypatch
):
    f = fixture
    _, _, _, _, runtime, _ = queued(f, tmp_path)
    for name in (
        "IAI_DATABASE_URL",
        "IAI_OIDC_CLIENT_SECRET",
        "IAI_OIDC_ISSUER",
        "IAI_OIDC_CLIENT_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    from intelligenceai.web.config import Settings

    monkeypatch.setattr(
        Settings, "from_env", lambda: pytest.fail("PC must not load server configuration")
    )
    api = FixtureAPI(f, lose="result")
    client = Client(api, runtime, tmp_path / "pc")
    with pytest.raises(TimeoutError):
        client.once()
    assert runtime.calls == 1
    journal = next((tmp_path / "pc").glob("*.json"))
    stored = json.loads(journal.read_text(encoding="utf-8"))
    assert stored["result"]["outcome"] == "COMPLETED"
    assert client.retry_result(journal.stem)["source"] == "USER_DEVICE_REPORT"
    assert client.once() is False and runtime.calls == 1


def test_lost_start_response_journal_prevents_native_call_and_restart_replay(fixture, tmp_path):
    f = fixture
    _, _, _, _, runtime, _ = queued(f, tmp_path)
    client = Client(FixtureAPI(f, lose="start"), runtime, tmp_path / "pc")
    with pytest.raises(TimeoutError):
        client.once()
    assert runtime.calls == 0
    journal = next((tmp_path / "pc").glob("*.json"))
    assert json.loads(journal.read_text(encoding="utf-8"))["state"] == "CONSUMED_UNKNOWN"
    restarted = Client(FixtureAPI(f), runtime, tmp_path / "pc")
    assert restarted.once() is False and runtime.calls == 0
    with pytest.raises(ValueError, match="cannot_replay"):
        restarted.retry_result(journal.stem)
    with f["db"].begin() as conn:
        conn.execute(update(pc_attempts).values(expires_at=now() - 1))
    assert restarted.once() is False
    with f["db"].connect() as conn:
        assert conn.execute(select(local_cli_requests.c.state)).scalar_one() == "UNKNOWN"


def test_db_worker_cannot_execute_outbound_pc_profile(fixture, tmp_path):
    f = fixture
    _, _, _, _, runtime, pair = queued(f, tmp_path)
    with f["db"].connect() as conn:
        profile = conn.execute(
            select(pc_runners.c.profile_id).where(pc_runners.c.id == pair["id"])
        ).scalar_one()
    with pytest.raises(ValueError, match="outbound_pc"):
        Worker(f["db"], profile, runtime, tmp_path / "db-worker").once()
    assert runtime.calls == 0


@pytest.mark.parametrize("other_owner", [False, True])
def test_other_runner_token_cannot_access_an_attempt(fixture, tmp_path, other_owner):
    f = fixture
    _, _, headers, _, runtime, _ = queued(f, tmp_path)
    _, bound = claim(f)
    if other_owner:
        headers = f["sign_in"](f["bob"])
        target = f | {"base": f"/api/projects/{f['other']}"}
    else:
        target = f
    token = "t" * 43
    enroll(target, runtime, headers, token=token)
    for action in ("start", "heartbeat", "result"):
        body = report(bound) if action == "result" else bound
        assert machine(f, action, body, token=token).status_code == 404
    assert machine(f, "claim", token=token).json()["attempt"] is None


def test_local_runtime_change_cannot_execute_server_work(fixture, tmp_path):
    f = fixture
    _, _, _, _, runtime, _ = queued(f, tmp_path)
    runtime.provider = "claude"
    with pytest.raises(ValueError, match="allowlist_changed"):
        Client(FixtureAPI(f), runtime, tmp_path / "pc").once()
    assert runtime.calls == 0


def test_result_cannot_claim_completion_without_consistent_report(fixture, tmp_path):
    f = fixture
    queued(f, tmp_path)
    _, bound = claim(f)
    assert machine(f, "start", bound).status_code == 200
    for value in ({"text": ""}, {"cleanup_reported": False}, {"availability": "EXECUTION_ERROR"}):
        assert machine(f, "result", report(bound, **value)).status_code == 422


@pytest.mark.parametrize(
    "origin",
    [
        "http://server",
        "https://user:pass@server",
        "https://server/path",
        "https://server?q=x",
        "https://server#x",
    ],
)
def test_pc_client_origin_cannot_redirect_or_embed_credentials(origin):
    with pytest.raises(ValueError):
        API(origin, TOKEN)


@pytest.mark.parametrize("phase", ["claim", "start"])
def test_independent_postgresql_claim_and_start_are_once(fixture, tmp_path, phase):
    f = fixture
    if f["db"].dialect.name != "postgresql":
        pytest.skip("real PostgreSQL lock fixture required")
    queued(f, tmp_path)
    pc = PCs(f["db"], testing=True)
    barrier = Barrier(2)
    if phase == "start":
        _, bound = claim(f)

    def operation():
        barrier.wait(timeout=5)
        try:
            return pc.claim(TOKEN) if phase == "claim" else pc.start(TOKEN, AttemptInput(**bound))
        except Problem as exc:
            return {"error": exc.code}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: operation(), range(2)))
    if phase == "claim":
        assert sum(value.get("attempt") is not None for value in results) == 1
    else:
        assert sum(value.get("authorized") is True for value in results) == 1
