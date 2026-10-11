"""Synthetic native process/output tests. No provider/auth/billing calls."""

import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

from sqlalchemy import create_engine, event, insert, select, update
from test_web import fixture as shared_fixture
from test_web import submit

from intelligenceai.security import digest
from intelligenceai.web.cli_process import LocalProcess, native_environment
from intelligenceai.web.cli_results import parse
from intelligenceai.web.cli_worker import Worker
from intelligenceai.web.store import (
    artifacts,
    attempts,
    jobs,
    local_cli_profiles,
    local_cli_requests,
    members,
    now,
    projects,
    sessions,
    tasks,
    uid,
)

fixture = shared_fixture
FAKE = Path(__file__).parent / "fixtures" / "local_cli_fake.py"


class FakeRuntime:
    scope = "FAKE_CLI_TEST_ONLY"

    def __init__(self, provider="codex", mode="success"):
        self.provider, self.mode = provider, mode
        self.calls = 0
        self.launched = Event()
        self.before_gate = None

    @property
    def runtime_digest(self):
        return digest(
            {
                "provider": self.provider,
                "scope": self.scope,
                "sha": hashlib.sha256(FAKE.read_bytes()).hexdigest(),
            }
        )

    def start(self, cwd, prompt, before_start, *, on_spawn=None):
        self.calls += 1

        @contextmanager
        def gate():
            if self.before_gate:
                self.before_gate()
            with before_start() as recheck:
                yield recheck
                self.launched.set()

        return LocalProcess(
            [
                sys.executable,
                "-I",
                "-S",
                "-X",
                "utf8",
                str(FAKE.resolve()),
                self.provider,
                self.mode,
            ],
            cwd,
            prompt,
            before_start=gate,
            on_spawn=on_spawn,
        )


def setup(f, tmp_path, provider="codex", mode="success"):
    task_id, headers = submit(f)
    # An explicitly synthetic trusted producer snapshot, not core/OS/provider evidence.
    candidate = {"synthetic": True}
    evidence = [{"source": "synthetic-static-json", "status": "PASS"}]
    content = '{"fixture":"한글 원문"}\n'
    runtime = FakeRuntime(provider, mode)
    profile = uid()
    with f["db"].begin() as conn:
        task = conn.execute(select(tasks).where(tasks.c.id == task_id)).mappings().one()
        policy = conn.execute(
            select(projects.c.policy_digest).where(projects.c.id == f["project"])
        ).scalar_one()
        conn.execute(
            update(tasks)
            .where(tasks.c.id == task_id)
            .values(
                candidate_digest=digest(candidate),
                evidence_digest=digest(evidence),
                evidence_verified=True,
                state="READY_FOR_APPROVAL",
            )
        )
        conn.execute(update(jobs).where(jobs.c.task_id == task_id).values(state="FINISHED"))
        conn.execute(
            insert(artifacts).values(
                id=uid(),
                task_id=task_id,
                name="candidate.json",
                kind="candidate",
                content=content,
                digest=hashlib.sha256(content.encode()).hexdigest(),
            )
        )
        conn.execute(
            insert(attempts).values(
                core_task_id=uid(),
                project_id=f["project"],
                task_id=task_id,
                generation=1,
                phase="RECEIVED",
                profile="json-review",
                policy_digest=policy,
                plan_digest=digest(task["plan"]),
                receipt={
                    "kind": "completed",
                    "scope": "FIXTURE_STATIC_ONLY",
                    "candidate": candidate,
                    "evidence": evidence,
                    "contents": {"candidate.json": content},
                },
            )
        )
        conn.execute(
            insert(local_cli_profiles).values(
                id=profile,
                project_id=f["project"],
                actor_id=f["alice"],
                provider=provider,
                runtime_digest=runtime.runtime_digest,
                metadata={
                    "version": "SYNTHETIC",
                    "scope": runtime.scope,
                    "can_execute": True,
                    "installation": "FAKE_INSTALLED",
                    "availability": "FAKE_TEST_ONLY",
                },
            )
        )
    path = f["base"] + f"/tasks/{task_id}/local-cli"
    headers = {**headers, "Idempotency-Key": uid()}
    response = f["client"].post(path + "/prepare", json={"profile_id": profile}, headers=headers)
    assert response.status_code == 200, response.text
    record = response.json()
    assert "session_hash" not in record["binding"]
    return task_id, path, headers, record, Worker(f["db"], profile, runtime, tmp_path / "worker")


def approve(f, path, headers, record):
    response = f["client"].post(
        path + "/approve",
        json={"request_id": record["id"], "binding_digest": record["binding_digest"]},
        headers={**headers, "Idempotency-Key": uid()},
    )
    assert response.status_code == 200, response.text
    return response


@pytest.mark.parametrize("provider", ["claude", "codex", "grok"])
def test_gui_queue_worker_private_result_is_synthetic_and_once(fixture, tmp_path, provider):
    f = fixture
    tid, path, headers, record, worker = setup(f, tmp_path, provider)
    response = approve(f, path, headers, record)
    assert response.json()["state"] == "QUEUED" and worker.runtime.calls == 0
    assert worker.once() is True and worker.once() is False
    saved = f["client"].get(path).json()["requests"][0]
    assert saved["state"] == "COMPLETED", saved
    assert saved["result"]["live_model"] == "NOTRUN"
    assert saved["result"]["scope"] == "FAKE_CLI_TEST_ONLY"
    assert saved["result"]["cli_invocations"] == 1
    assert saved["result"]["usage"]["values"]["input_tokens"] == 12
    capture = json.loads(
        (worker.root / record["id"] / "input-capture.json").read_text(encoding="utf-8")
    )
    original = f["service"].task(f["alice"], f["project"], tid)["request"]
    assert capture["stdin"].count(original) == 1 and original not in capture["argv"]
    assert "한글 원문" in capture["stdin"] and "\\u" not in capture["stdin"]
    assert saved["binding"]["payload"]["payload_bytes"] == len(capture["stdin"].encode())
    assert saved["result"]["payload"]["truncated"] is False
    task = f["client"].get(f["base"] + f"/tasks/{tid}").json()
    result = next(value for value in task["artifacts"] if value["kind"] == "cli-result")
    artifact_path = f["base"] + f"/tasks/{tid}/artifacts/{result['id']}"
    text = f["client"].get(artifact_path).text
    assert "[REDACTED]" in text and ("IAI_TEST_" + "SECRET_OUTPUT") not in text
    f["sign_in"](f["bob"])
    assert f["client"].get(path).status_code == 404
    assert f["client"].get(artifact_path).status_code == 404


@pytest.mark.parametrize(
    "change", ["profile", "session", "role", "generation", "policy", "candidate", "expiry"]
)
def test_changed_authority_at_launch_never_imports_or_replays(fixture, tmp_path, change):
    f = fixture
    tid, path, headers, record, worker = setup(f, tmp_path)
    approve(f, path, headers, record)

    def revoke():
        with f["db"].begin() as conn:
            if change == "profile":
                conn.execute(update(local_cli_profiles).values(active=False))
            elif change == "session":
                conn.execute(update(sessions).values(revoked=True))
            elif change == "role":
                conn.execute(
                    update(members).where(members.c.user_id == f["alice"]).values(role="revoked")
                )
            elif change == "generation":
                conn.execute(update(tasks).where(tasks.c.id == tid).values(generation=2))
            elif change == "policy":
                conn.execute(
                    update(projects)
                    .where(projects.c.id == f["project"])
                    .values(policy_digest="e" * 64)
                )
            elif change == "candidate":
                conn.execute(
                    update(artifacts).where(artifacts.c.task_id == tid).values(content="changed")
                )
            else:
                binding = dict(record["binding"]) | {"expires_at": now() - 1}
                conn.execute(update(local_cli_requests).values(binding=binding))

    worker.runtime.before_gate = revoke
    assert worker.once() is True
    assert not worker.runtime.launched.is_set()
    with f["db"].connect() as conn:
        saved = conn.execute(select(local_cli_requests)).mappings().one()
        assert saved["state"] == "UNKNOWN"
        assert (
            conn.execute(select(artifacts.c.id).where(artifacts.c.kind == "cli-result")).first()
            is None
        )


def test_duplicate_queue_and_queued_cancel_do_not_launch(fixture, tmp_path):
    f = fixture
    tid, path, headers, record, worker = setup(f, tmp_path)
    body = {"request_id": record["id"], "binding_digest": record["binding_digest"]}
    key = {**headers, "Idempotency-Key": uid()}
    first = f["client"].post(path + "/approve", json=body, headers=key)
    assert f["client"].post(path + "/approve", json=body, headers=key).json() == first.json()
    assert (
        f["client"]
        .post(path + "/approve", json=body, headers={**headers, "Idempotency-Key": uid()})
        .status_code
        == 409
    )
    response = f["client"].post(
        f["base"] + f"/tasks/{tid}/cancel", json={}, headers={**headers, "Idempotency-Key": uid()}
    )
    assert response.json()["state"] == "CANCELLED"
    assert worker.once() is False and worker.runtime.calls == 0


@pytest.mark.parametrize("change", ["cancel", "session", "role"])
def test_commit_between_context_creation_and_gate_release_prevents_native_start(
    fixture, tmp_path, monkeypatch, change
):
    f = fixture
    tid, path, headers, record, worker = setup(f, tmp_path)
    approve(f, path, headers, record)
    original = worker.launch_authority

    def intervening(row, lease):
        context = original(row, lease)
        # The former successful callback return was vulnerable at this exact boundary.
        with f["db"].begin() as conn:
            if change == "cancel":
                conn.execute(
                    update(jobs).where(jobs.c.task_id == tid).values(cancel_requested=True)
                )
            elif change == "session":
                conn.execute(update(sessions).values(revoked=True))
            else:
                conn.execute(
                    update(members).where(members.c.user_id == f["alice"]).values(role="revoked")
                )
        return context

    monkeypatch.setattr(worker, "launch_authority", intervening)
    assert worker.once() is True
    assert not worker.runtime.launched.is_set()
    assert not (worker.root / record["id"] / "input-capture.json").exists()
    with f["db"].connect() as conn:
        assert (
            conn.execute(select(artifacts.c.id).where(artifacts.c.kind == "cli-result")).first()
            is None
        )


def test_expired_unstarted_queue_does_not_strand_later_valid_request(fixture, tmp_path):
    f = fixture
    first, path, headers, expired, worker = setup(f, tmp_path / "first")
    approve(f, path, headers, expired)
    second, path2, headers2, valid, _ = setup(f, tmp_path / "second")
    approve(f, path2, headers2, valid)
    with f["db"].begin() as conn:
        binding = conn.execute(
            select(local_cli_requests.c.binding).where(local_cli_requests.c.id == expired["id"])
        ).scalar_one()
        binding = dict(binding) | {"expires_at": now() - 1}
        conn.execute(
            update(local_cli_requests)
            .where(local_cli_requests.c.id == expired["id"])
            .values(binding=binding, binding_digest=digest(binding), created_at=now() - 10)
        )
        conn.execute(
            update(local_cli_requests)
            .where(local_cli_requests.c.id == valid["id"])
            .values(profile_id=worker.profile_id)
        )
    assert worker.once() is True and worker.runtime.calls == 0
    assert worker.once() is True and worker.runtime.calls == 1
    with f["db"].connect() as conn:
        rows = {row["task_id"]: row for row in conn.execute(select(local_cli_requests)).mappings()}
        assert rows[first]["state"] == "NEVER_STARTED"
        assert rows[first]["result"]["cli_invocations"] == 0
        assert rows[first]["result"]["live_model"] == "NOTRUN"
        assert rows[second]["state"] == "COMPLETED"


@pytest.mark.parametrize("mutation", ["project", "session", "role"])
def test_postgresql_gate_retains_authority_through_release(fixture, tmp_path, mutation):
    from sqlalchemy.exc import DBAPIError

    f = fixture
    if f["db"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL required to prove independent row locks")
    tid, path, headers, record, worker = setup(f, tmp_path)
    approve(f, path, headers, record)
    lease = uid()
    with f["db"].begin() as conn:
        conn.execute(
            update(local_cli_requests)
            .where(local_cli_requests.c.id == record["id"])
            .values(state="STARTING", lease_token=lease)
        )
        conn.execute(
            update(jobs)
            .where(jobs.c.task_id == tid)
            .values(state="LOCAL_CLI_RUNNING", lease_token=lease, lease_expires_at=now() + 65)
        )
        conn.execute(update(tasks).where(tasks.c.id == tid).values(state="LOCAL_CLI_RUNNING"))
        row = (
            conn.execute(select(local_cli_requests).where(local_cli_requests.c.id == record["id"]))
            .mappings()
            .one()
        )
    pool = create_engine(f["db"].url, connect_args={"options": "-c lock_timeout=150ms"})

    def revoke():
        with pool.begin() as conn:
            if mutation == "project":
                statement = (
                    update(projects)
                    .where(projects.c.id == f["project"])
                    .values(policy_digest="e" * 64)
                )
            elif mutation == "session":
                statement = update(sessions).values(revoked=True)
            else:
                statement = (
                    update(members).where(members.c.user_id == f["alice"]).values(role="revoked")
                )
            conn.execute(statement)

    try:
        with worker.launch_authority(row, lease) as recheck:
            with ThreadPoolExecutor(1) as executor:
                with pytest.raises(DBAPIError) as caught:
                    executor.submit(revoke).result(timeout=5)
                assert caught.value.orig.sqlstate == "55P03"
            recheck()
        revoke()
        with pytest.raises(Exception):
            with worker.launch_authority(row, lease):
                pytest.fail("committed revocation released gate")
    finally:
        pool.dispose()


def test_quota_status_has_no_db_locks_and_rejects_changed_runtime(fixture, tmp_path, monkeypatch):
    f = fixture
    _, _, _, _, worker = setup(f, tmp_path)

    def status(_):
        with f["db"].begin() as conn:
            conn.execute(
                update(local_cli_profiles)
                .where(local_cli_profiles.c.id == worker.profile_id)
                .values(runtime_digest="e" * 64)
            )
        return {"status": "PROVIDED", "limits": [], "measured_at": 123}

    monkeypatch.setattr(worker.runtime, "quota", status, raising=False)
    from intelligenceai.web.service import Problem

    with pytest.raises(Problem):
        worker.refresh_quota()
    with f["db"].connect() as conn:
        assert (
            "quota"
            not in conn.execute(
                select(local_cli_profiles.c.metadata).where(
                    local_cli_profiles.c.id == worker.profile_id
                )
            ).scalar_one()
        )


@pytest.mark.parametrize(
    "state,count", [("STARTING", None), ("RUNNING", None), ("UNKNOWN", None), ("COMPLETED", 1)]
)
def test_native_cli_invocations_do_not_imply_internal_model_call_count(
    fixture, tmp_path, state, count
):
    f = fixture
    tid, _, _, record, _ = setup(f, tmp_path)
    with f["db"].begin() as conn:
        conn.execute(
            update(local_cli_requests)
            .where(local_cli_requests.c.id == record["id"])
            .values(
                state=state,
                result={"scope": "LOCAL_NATIVE_CLI", "cli_invocations": 1}
                if state == "COMPLETED"
                else None,
            )
        )
    task = f["service"].task(f["alice"], f["project"], tid)
    assert task["model_calls"] is None
    assert task["local_cli_invocations"] == count


def test_postgresql_quota_waits_project_without_holding_profile(fixture, tmp_path, monkeypatch):
    f = fixture
    if f["db"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL required for lock-order barrier")
    _, _, _, _, worker = setup(f, tmp_path)
    queried = Event()
    monkeypatch.setattr(
        worker.runtime,
        "quota",
        lambda _: queried.set() or {"status": "NOT_PROVIDED", "limits": []},
        raising=False,
    )
    pool = create_engine(f["db"].url, connect_args={"options": "-c lock_timeout=150ms"})
    try:
        with ThreadPoolExecutor(1) as executor:
            with f["db"].begin() as conn:
                conn.execute(
                    select(projects.c.id).where(projects.c.id == f["project"]).with_for_update()
                ).one()
                future = executor.submit(worker.refresh_quota)
                assert queried.wait(5)
                # Worker may wait on project; it must not already own the profile lock.
                with pool.begin() as other:
                    other.execute(
                        select(local_cli_profiles.c.id)
                        .where(local_cli_profiles.c.id == worker.profile_id)
                        .with_for_update()
                    ).one()
            future.result(timeout=5)
    finally:
        pool.dispose()


def test_postgresql_owner_slot_does_not_block_api_audit_foreign_key(fixture, tmp_path):
    f = fixture
    if f["db"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL required for FK key-share barrier")
    _, _, _, _, worker = setup(f, tmp_path)
    owner_locked = Event()
    worker_pool = create_engine(f["db"].url)
    api_pool = create_engine(f["db"].url, connect_args={"options": "-c lock_timeout=300ms"})
    worker.db = worker_pool

    @event.listens_for(worker_pool, "after_cursor_execute")
    def locked(_conn, _cursor, statement, _parameters, _context, _many):
        if "web_users" in statement and "FOR NO KEY UPDATE" in statement:
            owner_locked.set()

    try:
        with ThreadPoolExecutor(1) as executor:
            with api_pool.begin() as conn:
                conn.execute(
                    select(projects.c.id).where(projects.c.id == f["project"]).with_for_update()
                ).one()
                future = executor.submit(worker.once)
                assert owner_locked.wait(5)
                f["service"].record(conn, f["project"], f["alice"], "synthetic-api-barrier", {})
            assert future.result(timeout=5) is False
    finally:
        worker_pool.dispose()
        api_pool.dispose()


def test_running_cancel_descendants_and_recovery_stay_honest(fixture, tmp_path):
    f = fixture
    tid, path, headers, record, worker = setup(f, tmp_path, mode="descendant")
    approve(f, path, headers, record)
    with ThreadPoolExecutor() as pool:
        running = pool.submit(worker.once)
        assert worker.runtime.launched.wait(5)
        time.sleep(0.15)
        response = f["client"].post(
            f["base"] + f"/tasks/{tid}/cancel",
            json={},
            headers={**headers, "Idempotency-Key": uid()},
        )
        assert response.json()["state"] == "CANCEL_REQUESTED"
        assert running.result(timeout=8) is True
    saved = f["client"].get(path).json()["requests"][0]
    assert saved["state"] == "UNKNOWN" and saved["result"]["remote_cancellation"] == "UNKNOWN"
    assert saved["result"]["local_termination_confirmed"] is True
    assert worker.once() is False and worker.runtime.calls == 1
    assert (
        f["client"]
        .post(
            f["base"] + f"/tasks/{tid}/recover",
            json={},
            headers={**headers, "Idempotency-Key": uid()},
        )
        .status_code
        == 409
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("env", {}),
        ("executable", "C:/private.exe"),
        ("actor_id", "other"),
        ("livegate", True),
        ("command", "shell"),
        ("endpoint", "http://169.254.169.254"),
    ],
)
def test_browser_authority_and_execution_inputs_rejected(fixture, tmp_path, field, value):
    f = fixture
    _, path, headers, record, _ = setup(f, tmp_path)
    response = f["client"].post(
        path + "/prepare",
        json={"profile_id": record["profile_id"], field: value},
        headers={**headers, "Idempotency-Key": uid()},
    )
    assert response.status_code == 422
    viewer_headers = f["sign_in"](f["viewer"])
    assert (
        f["client"]
        .post(
            path + "/approve",
            json={"request_id": record["id"], "binding_digest": record["binding_digest"]},
            headers=viewer_headers,
        )
        .status_code
        == 403
    )


def test_environment_only_reads_standard_keys(monkeypatch):
    monkeypatch.setenv("CODEX_API_KEY", "IAI_TEST_" + "SECRET_ENV")
    monkeypatch.setenv("XAI_API_KEY", "IAI_TEST_" + "SECRET_ENV")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://untrusted.invalid")
    monkeypatch.setenv("GROK_CONFIG", "untrusted config")
    assert not set(native_environment()) & {
        "CODEX_API_KEY",
        "XAI_API_KEY",
        "ANTHROPIC_BASE_URL",
        "GROK_CONFIG",
    }


@pytest.mark.parametrize("provider", ["claude", "codex", "grok"])
@pytest.mark.parametrize("condition", ["auth", "limited", "badjson", "rc_mismatch", "truncated"])
def test_native_parser_failure_does_not_become_success(provider, condition):
    native = {
        "claude": {"type": "result", "subtype": "success", "is_error": False, "result": "ok"},
        "codex": {"type": "turn.completed"},
        "grok": {"text": "ok", "stopReason": "end_turn"},
    }[provider]
    payload = json.dumps(native).encode()
    if condition == "badjson":
        payload = b"partial{"
    stderr = {"auth": b"authentication required", "limited": b"quota exceeded"}.get(condition, b"")
    result = parse(
        provider,
        payload,
        stderr,
        1 if condition in {"auth", "limited", "rc_mismatch"} else 0,
        now(),
        truncated=condition == "truncated",
    )
    assert result["availability"] != "AVAILABLE" and result["text"] is None


def test_grok_stream_usage_incomplete_and_codex_cache_not_added():
    events = [
        {"type": "text", "data": "fake result"},
        {
            "type": "end",
            "stopReason": "end_turn",
            "usage": {"input_tokens": 5, "cache_read_input_tokens": 7},
            "usage_is_incomplete": True,
        },
    ]
    result = parse("grok", "\n".join(json.dumps(value) for value in events).encode(), b"", 0, 123)
    assert result["availability"] == "AVAILABLE"
    assert result["usage"]["completeness"] == "INCOMPLETE"
    assert result["usage"]["values"]["input_tokens"] == 5
    events = [
        {"type": "item.completed", "item": {"type": "agent_message", "text": "fake"}},
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 12, "cached_input_tokens": 7, "output_tokens": 0},
        },
    ]
    result = parse("codex", "\n".join(json.dumps(value) for value in events).encode(), b"", 0, 123)
    assert result["usage"]["values"]["input_tokens"] == 12
    assert result["usage"]["values"]["output_tokens"] == 0
    assert result["usage"]["values"]["reasoning_output_tokens"] is None


@pytest.mark.parametrize(
    "diagnostic,terminal,expected",
    [
        ("item.error", "turn.completed", "PARTIAL_FAILURE"),
        ("error", "turn.completed", "PARTIAL_FAILURE"),
        ("item.error", "turn.failed", "REQUEST_FAILED"),
        ("item.error", None, "EXECUTION_ERROR"),
    ],
)
def test_codex_diagnostic_is_not_tool_or_success(diagnostic, terminal, expected):
    events = [
        {"type": "item.completed", "item": {"type": "error", "message": "SYNTHETIC_DIAGNOSTIC"}}
        if diagnostic == "item.error"
        else {"type": "error", "message": "SYNTHETIC_DIAGNOSTIC"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "SYNTHETIC_ANSWER"}},
    ]
    if terminal:
        events.append({"type": terminal, "usage": {"output_tokens": 4}})
    result = parse("codex", "\n".join(json.dumps(event) for event in events).encode(), b"", 0, 123)
    assert result["availability"] == expected and result["text"] is None
    assert result["native_outcome"]["unsupported_item_count"] == 0
    assert result["native_outcome"]["diagnostic_count"] == 1
    assert result["native_outcome"]["agent_message_count"] == 1
    assert "SYNTHETIC_DIAGNOSTIC" not in json.dumps(result)


@pytest.mark.parametrize(
    "final,expected",
    [("SYNTHETIC_FINAL", "AVAILABLE"), ("", "EXECUTION_ERROR"), ("   ", "EXECUTION_ERROR")],
)
def test_codex_commentary_then_final_uses_last_message_only(final, expected):
    events = [
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "SYNTHETIC_COMMENTARY"},
        },
        {"type": "item.completed", "item": {"type": "agent_message", "text": final}},
        {"type": "turn.completed", "usage": {"output_tokens": 4}},
    ]
    result = parse("codex", "\n".join(json.dumps(value) for value in events).encode(), b"", 0, 123)
    assert result["availability"] == expected
    assert result["text"] == (final if expected == "AVAILABLE" else None)


@pytest.mark.parametrize("provider,version", [("claude", "2.1.296"), ("codex", "0.162.1")])
def test_native_argv_never_repeats_stdin_or_changes_model(tmp_path, monkeypatch, provider, version):
    from intelligenceai.web import cli_runtime

    executable = tmp_path / "synthetic-executable"
    executable.write_bytes(b"SYNTHETIC_EXECUTABLE_NOT_RUN")
    captured = {}
    monkeypatch.setattr(cli_runtime.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_runtime.shutil, "which", lambda name: "SYNTHETIC_GIT_NOT_RUN")

    def process(argv, cwd, prompt, **kwargs):
        captured.update(argv=argv, stdin=prompt)
        return captured

    monkeypatch.setattr(cli_runtime, "LocalProcess", process)
    runtime = cli_runtime.NativeRuntime(provider, executable, version)
    runtime.start(tmp_path, "원문 요청은 STDIN_ONLY_749", lambda: None)
    assert captured["stdin"] == "원문 요청은 STDIN_ONLY_749"
    assert not any("STDIN_ONLY_749" in arg for arg in captured["argv"])
    assert "--model" not in captured["argv"] and "--effort" not in captured["argv"]
    assert "--resume" not in captured["argv"]


def test_context_keeps_sources_deduplicates_exact_content_and_has_no_other_task(fixture, tmp_path):
    from intelligenceai.web.cli_service import LocalCLI

    f = fixture
    tid, _, _, _, worker = setup(f, tmp_path)
    other, _ = submit(f)
    with f["db"].begin() as conn:
        candidate = (
            conn.execute(select(artifacts).where(artifacts.c.task_id == tid)).mappings().one()
        )
        conn.execute(
            insert(artifacts).values(
                id=uid(),
                task_id=tid,
                name="copy.json",
                kind="candidate",
                content=candidate["content"],
                digest=candidate["digest"],
            )
        )
        conn.execute(
            insert(artifacts).values(
                id=uid(),
                task_id=other,
                name="other.json",
                kind="candidate",
                content="OTHER_PRIVATE_CONTEXT",
                digest="e" * 64,
            )
        )
        task = conn.execute(select(tasks).where(tasks.c.id == tid)).mappings().one()
        prompt, metrics = LocalCLI(f["db"]).prompt(conn, task)
    value = json.loads(prompt)
    assert value["candidates"][0]["names"] == ["candidate.json", "copy.json"]
    assert len(value["candidates"]) == 1 and metrics["candidate_files"] == 2
    assert "OTHER_PRIVATE_CONTEXT" not in prompt
    assert value["evidence"] == [{"source": "synthetic-static-json", "status": "PASS"}]
    assert len(prompt.encode()) < len(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )
    assert metrics["history_messages"] == 0 and metrics["log_bytes"] == 0
    assert worker.runtime.calls == 0


def test_oversize_context_and_changed_request_never_reuse_approval(fixture, tmp_path):
    from intelligenceai.web.cli_service import LocalCLI
    from intelligenceai.web.service import Problem

    f = fixture
    tid, path, headers, record, worker = setup(f, tmp_path)
    with f["db"].begin() as conn:
        conn.execute(update(tasks).where(tasks.c.id == tid).values(request="changed request"))
    response = f["client"].post(
        path + "/approve",
        json={"request_id": record["id"], "binding_digest": record["binding_digest"]},
        headers={**headers, "Idempotency-Key": uid()},
    )
    assert response.status_code == 409 and worker.runtime.calls == 0
    with f["db"].begin() as conn:
        content = "x" * 9000
        conn.execute(
            update(artifacts)
            .where(artifacts.c.task_id == tid)
            .values(content=content, digest=hashlib.sha256(content.encode()).hexdigest())
        )
        task = conn.execute(select(tasks).where(tasks.c.id == tid)).mappings().one()
        with pytest.raises(Problem) as caught:
            LocalCLI(f["db"]).prompt(conn, task)
        assert caught.value.code == "cli_context_too_large"
    assert worker.runtime.calls == 0
