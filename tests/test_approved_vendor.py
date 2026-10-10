"""Actual fixed fake executable; synthetic DB unit fixtures are not OS/provider evidence."""

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

from sqlalchemy import create_engine, insert, select, update
from test_web import fixture as shared_fixture
from test_web import ready, submit
from test_web_runner import queued

from intelligenceai.security import digest
from intelligenceai.web import vendor_runner
from intelligenceai.web.runner import Runner
from intelligenceai.web.service import Problem, Service
from intelligenceai.web.store import (
    approvals,
    artifacts,
    attempts,
    execution_grants,
    jobs,
    members,
    now,
    projects,
    sessions,
    tasks,
    uid,
    users,
    vendor_invocations,
)
from intelligenceai.web.vendor_runner import ApprovedFixtureRunner

fixture = shared_fixture


@pytest.fixture
def tmp_path():
    path = Path(__file__).resolve().parents[1] / ".tools" / "vv" / uid().replace("-", "")[:10]
    path.mkdir(parents=True)
    return path


@pytest.fixture
def separate_pools(fixture):
    pools = [create_engine(fixture["db"].url) for _ in range(2)]
    try:
        yield pools
    finally:
        for pool in pools:
            pool.dispose()


def approve_and_reserve(f, task_id, headers, *, reserve=True):
    task = f["service"].task(f["alice"], f["project"], task_id)
    binding = {
        name: task[name]
        for name in ("candidate_digest", "evidence_digest", "destination_id", "generation")
    } | {
        "policy_digest": f["service"].project(f["alice"], f["project"])["policy_digest"],
        "expires_at": now() + 600,
    }
    response = f["client"].post(
        f["base"] + f"/tasks/{task_id}/approve",
        json=binding,
        headers={**headers, "Idempotency-Key": uid()},
    )
    assert response.status_code == 200, response.text
    headers = {**headers, "Idempotency-Key": uid()}
    if not reserve:
        return None, headers
    response = f["client"].post(
        f["base"] + f"/tasks/{task_id}/run-approved-fixture", json={}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json(), headers


def seeded_review(f):
    """Fast DB contract setup only; actual core subprocess coverage is separate below."""
    task_id, headers = submit(f)
    snapshot = {
        "kind": "completed",
        "scope": "FIXTURE_STATIC_ONLY",
        "candidate": {"synthetic-unit-fixture": True},
        "evidence": [{"kind": "synthetic-unit-fixture"}],
        "contents": {"candidate.json": '{"fixture":true}\n'},
    }
    with f["db"].begin() as conn:
        project = (
            conn.execute(select(projects).where(projects.c.id == f["project"])).mappings().one()
        )
        task = conn.execute(select(tasks).where(tasks.c.id == task_id)).mappings().one()
        conn.execute(
            update(tasks)
            .where(tasks.c.id == task_id)
            .values(
                state="READY_FOR_APPROVAL",
                candidate_digest=digest(snapshot["candidate"]),
                evidence_digest=digest(snapshot["evidence"]),
                evidence_verified=True,
            )
        )
        conn.execute(update(jobs).where(jobs.c.task_id == task_id).values(state="FINISHED"))
        conn.execute(
            insert(attempts).values(
                core_task_id=uid(),
                project_id=f["project"],
                task_id=task_id,
                generation=1,
                phase="RECEIVED",
                profile="json-review",
                policy_digest=project["policy_digest"],
                plan_digest=digest(task["plan"]),
                receipt=snapshot,
            )
        )
        conn.execute(
            insert(artifacts).values(
                id=uid(),
                task_id=task_id,
                name="candidate.json",
                kind="candidate",
                content=snapshot["contents"]["candidate.json"],
                digest=hashlib.sha256(snapshot["contents"]["candidate.json"].encode()).hexdigest(),
            )
        )
        conn.execute(
            insert(execution_grants).values(
                project_id=f["project"],
                mode="fixed-fixture",
                policy_digest=project["policy_digest"],
                expires_at=now() + 3600,
            )
        )
    return task_id, headers


def reserved(f):
    tid, headers = seeded_review(f)
    response, headers = approve_and_reserve(f, tid, headers)
    return tid, response["invocation_id"], headers


def expire(f, tid):
    with f["db"].begin() as conn:
        conn.execute(update(jobs).where(jobs.c.task_id == tid).values(lease_expires_at=now() - 1))
        conn.execute(
            update(vendor_invocations)
            .where(vendor_invocations.c.task_id == tid)
            .values(lease_expires_at=now() - 1)
        )


def test_actual_fake_vendor_executes_once_and_stores_private_result(fixture, tmp_path):
    f = fixture
    tid, invocation_id, headers = reserved(f)
    runner = ApprovedFixtureRunner(f["db"], tmp_path / "vendor")
    assert runner.run_once() == "FIXTURE_COMPLETED"
    assert runner.run_once() is None
    response = f["client"].post(
        f["base"] + f"/tasks/{tid}/run-approved-fixture", json={}, headers=headers
    )
    assert response.status_code == 200 and response.json()["invocation_id"] == invocation_id
    assert (
        f["client"]
        .post(
            f["base"] + f"/tasks/{tid}/run-approved-fixture",
            json={},
            headers={**headers, "Idempotency-Key": uid()},
        )
        .status_code
        == 409
    )
    detail = f["service"].task(f["alice"], f["project"], tid)
    result = detail["vendor_runs"][0]["result"]
    assert result["termination_confirmed"] and result["returncode"] == 0
    assert result["output"]["status"] == "SYNTHETIC_OUTPUT"
    assert result["live_model"] == "NOTRUN" and detail["model_calls"] == 0
    assert len(list(runner.root.glob("*/started.json"))) == 1
    artifact = next(value for value in detail["artifacts"] if value["kind"] == "vendor-result")
    assert (
        f["client"].get(f["base"] + f"/tasks/{tid}/artifacts/{artifact['id']}").status_code == 200
    )
    with pytest.raises(Problem) as error:
        f["service"].task(f["bob"], f["project"], tid)
    assert error.value.status == 404
    assert all(name not in json.dumps(detail) for name in ("session_hash", "lease_token", "argv"))


@pytest.mark.parametrize("profile", ["python-review", "json-review"])
def test_actual_core_approval_to_fake_vendor_acceptance(fixture, tmp_path, profile):
    f = fixture
    tid, headers = queued(f, profile)
    assert Runner(f["db"], tmp_path / "core").run_once() == "READY_FOR_APPROVAL"
    response, _ = approve_and_reserve(f, tid, headers)
    runner = ApprovedFixtureRunner(f["db"], tmp_path / "vendor")
    assert runner.run_once() == "FIXTURE_COMPLETED"
    detail = f["service"].task(f["alice"], f["project"], tid)
    assert detail["runs"][0]["receipt"]["scope"] == "FIXTURE_STATIC_ONLY"
    assert detail["vendor_runs"][0]["id"] == response["invocation_id"]
    assert detail["vendor_runs"][0]["result"]["scope"] == "FAKE_VENDOR_TEST_ONLY"
    assert len(detail["artifacts"]) == 2


@pytest.mark.parametrize(
    "change",
    [
        "member",
        "user",
        "session",
        "approval",
        "expiry",
        "policy",
        "candidate",
        "artifact",
        "cancel",
        "generation",
    ],
)
def test_current_authority_rechecked_before_spawn(fixture, tmp_path, monkeypatch, change):
    f = fixture
    tid, _, _ = reserved(f)
    runner = ApprovedFixtureRunner(f["db"], tmp_path / "vendor")
    claim = runner.claim()
    with f["db"].begin() as conn:
        if change == "member":
            conn.execute(
                update(members).where(members.c.user_id == f["alice"]).values(role="revoked")
            )
        elif change == "user":
            conn.execute(update(users).where(users.c.id == f["alice"]).values(active=False))
        elif change == "session":
            conn.execute(update(sessions).values(revoked=True))
        elif change in {"approval", "expiry"}:
            binding = conn.execute(select(approvals.c.binding)).scalar_one()
            binding = (
                binding | {"expires_at": now() - 1}
                if change == "expiry"
                else binding | {"candidate_digest": "f" * 64}
            )
            conn.execute(update(approvals).values(binding=binding))
        elif change == "policy":
            conn.execute(
                update(projects).where(projects.c.id == f["project"]).values(policy_digest="f" * 64)
            )
        elif change == "candidate":
            conn.execute(update(tasks).where(tasks.c.id == tid).values(candidate_digest="f" * 64))
        elif change == "artifact":
            conn.execute(
                update(artifacts).where(artifacts.c.task_id == tid).values(content="drift")
            )
        elif change == "cancel":
            conn.execute(update(jobs).where(jobs.c.task_id == tid).values(cancel_requested=True))
        else:
            conn.execute(update(tasks).where(tasks.c.id == tid).values(generation=2))
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("stale authority spawned"))
    with pytest.raises(Problem):
        runner.run_claim(claim)
    assert not list(runner.root.glob("*/started.json"))


@pytest.mark.parametrize(
    "boundary, expected",
    [
        ("claimed", "FIXTURE_COMPLETED"),
        ("starting", "NEEDS_RECONCILIATION"),
        ("receipt", "FIXTURE_COMPLETED"),
    ],
)
def test_restart_reconciles_without_replaying_consumed_start(fixture, tmp_path, boundary, expected):
    f = fixture
    tid, invocation_id, _ = reserved(f)
    runner = ApprovedFixtureRunner(f["db"], tmp_path / "vendor", crash_at=boundary)
    with pytest.raises(RuntimeError, match="injected"):
        runner.run_once()
    expire(f, tid)
    restarted = ApprovedFixtureRunner(f["db"], runner.root)
    assert restarted.reconcile(invocation_id) == expected
    assert len(list(runner.root.glob("*/started.json"))) == (0 if boundary == "starting" else 1)
    assert restarted.run_once() is None
    if boundary == "starting":
        assert (
            f["service"].cancel(f["alice"], f["project"], tid, uid())["state"] == "CANCEL_REQUESTED"
        )
        with pytest.raises(Problem, match="termination_receipt_required"):
            f["service"].recover(f["alice"], f["project"], tid, uid())
    else:
        assert restarted.reconcile(invocation_id) == expected


def test_unstarted_cancel_and_explicit_recovery_get_new_generation(fixture, tmp_path):
    f = fixture
    tid, _, _ = reserved(f)
    assert f["service"].cancel(f["alice"], f["project"], tid, uid())["state"] == "CANCELLED"
    assert ApprovedFixtureRunner(f["db"], tmp_path / "vendor").run_once() is None
    assert f["service"].recover(f["alice"], f["project"], tid, uid())["generation"] == 2
    with f["db"].connect() as conn:
        assert conn.execute(select(vendor_invocations.c.generation)).all() == [(1,)]


def test_arbitrary_pass_and_browser_execution_fields_cannot_enable_vendor(fixture):
    f = fixture
    tid, headers = submit(f)
    binding = ready(f, tid)
    assert (
        f["client"]
        .post(
            f["base"] + f"/tasks/{tid}/approve",
            json=binding,
            headers={**headers, "Idempotency-Key": uid()},
        )
        .status_code
        == 200
    )
    response = f["client"].post(
        f["base"] + f"/tasks/{tid}/run-approved-fixture",
        json={},
        headers={**headers, "Idempotency-Key": uid()},
    )
    assert (
        response.status_code == 409 and response.json()["error"] == "owned_fixture_receipt_required"
    )
    for data in (
        {"argv": ["sh"]},
        {"provider": "codex"},
        {"session_hash": "f" * 64},
        {"env": {"API_KEY": "synthetic"}},
        {"livegate": True},
    ):
        assert (
            f["client"]
            .post(
                f["base"] + f"/tasks/{tid}/run-approved-fixture",
                json=data,
                headers={**headers, "Idempotency-Key": uid()},
            )
            .status_code
            == 422
        )


def test_postgres_cancel_after_spawn_needs_real_termination_before_recovery(
    fixture, tmp_path, separate_pools
):
    f = fixture
    if f["db"].dialect.name != "postgresql":
        pytest.skip("separate-connection cancellation proof requires real PostgreSQL")
    tid, invocation_id, headers = reserved(f)
    runner = ApprovedFixtureRunner(separate_pools[0], tmp_path / "vendor")
    with ThreadPoolExecutor(max_workers=2) as pool:
        work = pool.submit(runner.run_once)
        deadline = time.monotonic() + 10
        while not (runner.root / invocation_id / "started.json").is_file():
            assert time.monotonic() < deadline
            time.sleep(0.01)
        response = f["client"].post(
            f["base"] + f"/tasks/{tid}/cancel",
            json={},
            headers={**headers, "Idempotency-Key": uid()},
        )
        assert response.json()["state"] == "CANCEL_REQUESTED"
        assert work.result(timeout=10) == "CANCELLED"
    detail = f["service"].task(f["alice"], f["project"], tid)
    assert detail["vendor_runs"][0]["result"]["termination_confirmed"]
    assert detail["vendor_runs"][0]["result"]["kind"] == "terminated"
    assert f["service"].recover(f["alice"], f["project"], tid, uid())["generation"] == 2


@pytest.mark.parametrize("change", ["cancel", "session", "expiry", "clock_rollback"])
def test_hashing_is_followed_by_current_authority_and_deadline_checks(
    fixture, tmp_path, monkeypatch, change
):
    f = fixture
    tid, invocation_id, _ = reserved(f)
    runner = ApprovedFixtureRunner(f["db"], tmp_path / "vendor")
    claim = runner.claim()
    with f["db"].connect() as conn:
        deadline = conn.execute(
            select(vendor_invocations.c.deadline).where(vendor_invocations.c.id == invocation_id)
        ).scalar_one()
    clock = [time.time()]
    monkeypatch.setattr(
        vendor_runner,
        "time",
        SimpleNamespace(time=lambda: clock[0], monotonic=time.monotonic, sleep=time.sleep),
    )
    original_hash = runner.file_digest

    def hashing(path):
        value = original_hash(path)
        if path == runner.vendor_source:
            if change in {"expiry", "clock_rollback"}:
                clock[0] = deadline if change == "expiry" else deadline - 301
            else:
                with f["db"].begin() as conn:
                    if change == "cancel":
                        conn.execute(
                            update(jobs).where(jobs.c.task_id == tid).values(cancel_requested=True)
                        )
                    else:
                        conn.execute(update(sessions).values(revoked=True))
        return value

    monkeypatch.setattr(runner, "file_digest", hashing)
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("post-hash stale spawn"))
    with pytest.raises(Problem):
        runner.run_claim(claim)
    assert not list(runner.root.glob("*/started.json"))


def test_real_logout_revokes_queued_execution_session(fixture, tmp_path, monkeypatch):
    f = fixture
    tid, _, headers = reserved(f)
    runner = ApprovedFixtureRunner(f["db"], tmp_path / "vendor")
    claim = runner.claim()
    assert f["client"].post("/api/logout", json={}, headers=headers).status_code == 200
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("logged-out actor spawned"))
    with pytest.raises(Problem):
        runner.run_claim(claim)
    with f["db"].connect() as conn:
        assert conn.execute(select(vendor_invocations.c.state)).scalar_one() == "TERMINATED"


def test_forged_completion_cannot_change_provenance_or_claim_live_success(fixture, tmp_path):
    f = fixture
    tid, invocation_id, _ = reserved(f)
    runner = ApprovedFixtureRunner(f["db"], tmp_path / "vendor", crash_at="receipt")
    with pytest.raises(RuntimeError):
        runner.run_once()
    path = runner.root / invocation_id / "supervisor-completed.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["live_model"] = "SUCCESS"
    path.write_text(json.dumps(report), encoding="utf-8")
    expire(f, tid)
    with pytest.raises(Problem, match="fixture_result_changed"):
        ApprovedFixtureRunner(f["db"], runner.root).reconcile(invocation_id)
    assert len(list(runner.root.glob("*/started.json"))) == 1


@pytest.mark.parametrize("same_key", [True, False])
def test_postgres_duplicate_reservation_and_claim_use_one_invocation(
    fixture, tmp_path, separate_pools, same_key
):
    f = fixture
    if f["db"].dialect.name != "postgresql":
        pytest.skip("separate-connection admission/claim proof requires real PostgreSQL")
    tid, headers = seeded_review(f)
    _, replay_headers = approve_and_reserve(f, tid, headers, reserve=False)
    with f["db"].connect() as conn:
        session_hash = conn.execute(
            select(sessions.c.token_hash).where(
                sessions.c.data["user_id"].as_string() == f["alice"]
            )
        ).scalar_one()
    keys = [
        replay_headers["Idempotency-Key"],
        replay_headers["Idempotency-Key"] if same_key else uid(),
    ]
    barrier = Barrier(2)

    def reserve(index):
        barrier.wait(timeout=10)
        try:
            return Service(separate_pools[index]).run_approved_fixture(
                f["alice"], f["project"], tid, keys[index], session_hash=session_hash
            )
        except Problem as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        admitted = list(pool.map(reserve, range(2)))
    values = [value for value in admitted if isinstance(value, dict)]
    assert len(values) == (2 if same_key else 1)
    if not same_key:
        rejected = next(value for value in admitted if isinstance(value, Problem))
        assert rejected.status == 409 and rejected.code == "invocation_already_reserved"
    invocation_id = values[0]["invocation_id"]
    assert all(value["invocation_id"] == invocation_id for value in values)
    with f["db"].connect() as conn:
        assert conn.execute(select(vendor_invocations.c.id)).all() == [(invocation_id,)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        runners = [ApprovedFixtureRunner(db, tmp_path / "vendor") for db in separate_pools]
        claims = list(pool.map(lambda runner: runner.claim(), runners))
    assert len([claim for claim in claims if claim]) == 1
    winner = next(claim for claim in claims if claim)
    assert winner.invocation_id == invocation_id
    assert runners[0].run_claim(winner) == "FIXTURE_COMPLETED"
    with pytest.raises(Problem):
        runners[1].run_claim(winner)
    assert len(list(runners[0].root.glob("*/started.json"))) == 1


def test_distinct_approver_revocation_blocks_current_operator_before_spawn(
    fixture, tmp_path, monkeypatch
):
    f = fixture
    tid, _ = seeded_review(f)
    with f["db"].begin() as conn:
        conn.execute(
            insert(members).values(project_id=f["project"], user_id=f["bob"], role="approver")
        )
    task = f["service"].task(f["alice"], f["project"], tid)
    binding = {
        name: task[name]
        for name in ("candidate_digest", "evidence_digest", "destination_id", "generation")
    } | {
        "policy_digest": f["service"].project(f["alice"], f["project"])["policy_digest"],
        "expires_at": now() + 600,
    }
    bob_headers = f["sign_in"](f["bob"])
    assert (
        f["client"]
        .post(f["base"] + f"/tasks/{tid}/approve", json=binding, headers=bob_headers)
        .status_code
        == 200
    )
    alice_headers = f["sign_in"](f["alice"])
    assert (
        f["client"]
        .post(f["base"] + f"/tasks/{tid}/run-approved-fixture", json={}, headers=alice_headers)
        .status_code
        == 200
    )
    runner = ApprovedFixtureRunner(f["db"], tmp_path / "vendor")
    claim = runner.claim()
    assert (
        f["client"]
        .put(
            f["base"] + "/members",
            json={"user_id": f["bob"], "role": "revoked"},
            headers={**alice_headers, "Idempotency-Key": uid()},
        )
        .status_code
        == 200
    )
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("revoked approver spawned"))
    with pytest.raises(Problem):
        runner.run_claim(claim)
