"""Real fixed-fixture subprocess and durable queue tests; live model/sandbox NOTRUN."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import insert, select, update
from test_web import INPUT
from test_web import fixture as shared_web_fixture

from intelligenceai.web.runner import Runner, child_environment
from intelligenceai.web.service import Problem
from intelligenceai.web.store import (
    artifacts,
    attempts,
    execution_grants,
    jobs,
    members,
    now,
    projects,
    tasks,
    uid,
)

fixture = shared_web_fixture


@pytest.fixture
def tmp_path():
    # Short, repository-owned paths avoid Windows Git's worktree GIT_DIR length ceiling.
    root = Path(__file__).resolve().parents[1] / ".tools" / "rt" / uid().replace("-", "")[:12]
    root.mkdir(parents=True)
    return root


def queued(f, profile="json-review"):
    headers = f["sign_in"](f["alice"])
    response = f["client"].post(
        f["base"] + "/tasks", json={**INPUT, "profile": profile}, headers=headers
    )
    assert response.status_code == 201
    tid = response.json()["id"]
    with f["db"].begin() as conn:
        policy = conn.execute(
            select(projects.c.policy_digest).where(projects.c.id == f["project"])
        ).scalar_one()
        conn.execute(
            insert(execution_grants).values(
                project_id=f["project"],
                mode="fixed-fixture",
                policy_digest=policy,
                expires_at=now() + 3600,
            )
        )
    response = f["client"].post(
        f["base"] + f"/tasks/{tid}/run-fixture",
        json={},
        headers={**headers, "Idempotency-Key": uid()},
    )
    assert response.status_code == 200, response.text
    return tid, headers


def expire(f, tid):
    with f["db"].begin() as conn:
        conn.execute(update(jobs).where(jobs.c.task_id == tid).values(lease_expires_at=now() - 1))


@pytest.mark.parametrize("profile", ["python-review", "json-review"])
def test_real_core_subprocess_and_private_results(fixture, tmp_path, profile):
    f = fixture
    tid, headers = queued(f, profile)
    runner = Runner(f["db"], tmp_path / "runner")
    assert runner.run_once() == "READY_FOR_APPROVAL"
    task = f["service"].task(f["alice"], f["project"], tid)
    assert task["evidence_verified"] and task["model_calls"] == 0
    assert len(task["runs"]) == 1
    receipt = task["runs"][0]["receipt"]
    assert receipt["live_model"] == "NOTRUN" and receipt["os_sandbox"] == "UNVERIFIED"
    assert len(receipt["invocations"]) == 1 and receipt["invocations"][0]["status"] == "SUCCEEDED"
    assert len(receipt["steps"]) == 3
    assert len(task["artifacts"]) == 1
    binding = {
        "candidate_digest": task["candidate_digest"],
        "evidence_digest": task["evidence_digest"],
        "policy_digest": f["service"].project(f["alice"], f["project"])["policy_digest"],
        "destination_id": "private-review",
        "generation": 1,
        "expires_at": now() + 600,
    }
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
    with f["db"].begin() as conn:
        conn.execute(update(artifacts).where(artifacts.c.task_id == tid).values(content="drift"))
    response = f["client"].post(
        f["base"] + f"/tasks/{tid}/approve",
        json=binding,
        headers={**headers, "Idempotency-Key": uid()},
    )
    assert response.status_code == 409 and response.json()["error"] == "approval_binding_changed"
    assert runner.run_once() is None
    with pytest.raises(Problem) as error:
        f["service"].task(f["bob"], f["project"], tid)
    assert error.value.status == 404


@pytest.mark.parametrize(
    "boundary, expected",
    [
        ("claimed", "NEEDS_RECONCILIATION"),
        ("reserved", "READY_FOR_APPROVAL"),
        ("starting", "NEEDS_RECONCILIATION"),
        ("receipt", "READY_FOR_APPROVAL"),
    ],
)
def test_crash_mapping_and_no_provider_replay(fixture, tmp_path, boundary, expected):
    f = fixture
    tid, _ = queued(f)
    runner = Runner(f["db"], tmp_path / "runner", crash_at=boundary)
    with pytest.raises(RuntimeError, match="injected"):
        runner.run_once()
    with f["db"].connect() as conn:
        mapping = conn.execute(select(attempts).where(attempts.c.task_id == tid)).mappings().one()
    completed = runner.root / mapping["core_task_id"] / "completed.json"
    before = completed.read_bytes() if completed.exists() else None
    expire(f, tid)
    runner.crash_at = None
    assert runner.reconcile(mapping["core_task_id"]) == expected
    if boundary == "receipt":
        assert completed.read_bytes() == before
        receipt = f["service"].task(f["alice"], f["project"], tid)["runs"][0]["receipt"]
        assert len(receipt["invocations"]) == 1
        assert runner.reconcile(mapping["core_task_id"]) == expected
    if expected == "NEEDS_RECONCILIATION":
        assert runner.run_once() is None
        with pytest.raises(Problem) as error:
            f["service"].recover(f["alice"], f["project"], tid, uid())
        assert error.value.code == "termination_receipt_required"


def test_expired_and_old_generation_cannot_import(fixture, tmp_path):
    f = fixture
    tid, _ = queued(f)
    runner = Runner(f["db"], tmp_path / "runner")
    claim = runner.claim()
    descriptor = runner.descriptor(claim)
    runner.child("prepare", claim, descriptor)
    runner.phase(claim, "RESERVED")
    runner.phase(claim, "STARTING")
    runner.child("execute", claim, descriptor)
    expire(f, tid)
    with pytest.raises(Problem) as error:
        runner.finish(claim, descriptor)
    assert error.value.code == "runner_fence_lost"
    with f["db"].connect() as conn:
        assert not conn.execute(select(artifacts).where(artifacts.c.task_id == tid)).first()
    with f["db"].begin() as conn:
        conn.execute(update(tasks).where(tasks.c.id == tid).values(generation=2))
    with pytest.raises(Problem) as error:
        runner.reconcile(claim.core_task_id)
    assert error.value.code == "runner_fence_lost"


def test_cancel_is_requested_until_child_finished_and_recovery_new_mapping(fixture, tmp_path):
    f = fixture
    tid, _ = queued(f)
    runner = Runner(f["db"], tmp_path / "runner")
    claim = runner.claim()
    descriptor = runner.descriptor(claim)
    runner.child("prepare", claim, descriptor)
    runner.phase(claim, "RESERVED")
    runner.phase(claim, "STARTING")
    assert f["service"].cancel(f["alice"], f["project"], tid, uid())["state"] == "CANCEL_REQUESTED"
    runner.child("execute", claim, descriptor)
    assert runner.finish(claim, descriptor) == "CANCELLED"
    assert f["service"].recover(f["alice"], f["project"], tid, uid())["generation"] == 2
    f["service"].run_fixture(f["alice"], f["project"], tid, uid())
    assert runner.run_once() == "READY_FOR_APPROVAL"
    task = f["service"].task(f["alice"], f["project"], tid)
    assert len(task["runs"]) == 2 and len({r["core_task_id"] for r in task["runs"]}) == 2


def test_secrets_not_inherited_and_candidate_verified_from_bytes(fixture, tmp_path, monkeypatch):
    for key in ["IAI_RUNNER_DATABASE_URL", "DATABASE_URL", "OPENAI_API_KEY", "IAI_OIDC_SECRET"]:
        monkeypatch.setenv(key, "sensitive-test-value")
    assert not any("sensitive-test-value" in v for v in child_environment(tmp_path).values())
    f = fixture
    tid, _ = queued(f)
    runner = Runner(f["db"], tmp_path / "runner", crash_at="receipt")
    with pytest.raises(RuntimeError):
        runner.run_once()
    with f["db"].connect() as conn:
        row = conn.execute(select(attempts).where(attempts.c.task_id == tid)).mappings().one()
    path = runner.root / row["core_task_id"] / "completed.json"
    report = json.loads(path.read_text())
    report["contents"]["settings.json"] = '{"enabled":false,"version":0}\n'
    path.write_text(json.dumps(report))
    expire(f, tid)
    with pytest.raises(Problem) as error:
        runner.reconcile(row["core_task_id"])
    assert error.value.code == "candidate_bytes_changed"


def test_fixture_admission_has_no_browser_authority_or_review_shortcut(fixture):
    f = fixture
    headers = f["sign_in"](f["alice"])
    response = f["client"].post(f["base"] + "/tasks", json=INPUT, headers=headers)
    tid = response.json()["id"]
    path = f["base"] + f"/tasks/{tid}/run-fixture"
    assert (
        f["client"].post(path, json={}, headers={**headers, "Idempotency-Key": uid()}).status_code
        == 409
    )
    for body in [
        {"actor": f["alice"]},
        {"command": "touch marker"},
        {"env": {}},
        {"livegate": True},
        {"profile": "vendor"},
        {"root": "/server"},
    ]:
        assert (
            f["client"]
            .post(path, json=body, headers={**headers, "Idempotency-Key": uid()})
            .status_code
            == 422
        )
    with f["db"].begin() as conn:
        policy = conn.execute(
            select(projects.c.policy_digest).where(projects.c.id == f["project"])
        ).scalar_one()
        conn.execute(
            insert(execution_grants).values(
                project_id=f["project"],
                mode="fixed-fixture",
                policy_digest=policy,
                expires_at=now() + 60,
            )
        )
    key = uid()
    headers = {**headers, "Idempotency-Key": key}
    assert f["client"].post(path, json={}, headers=headers).json()["state"] == "QUEUED"
    assert f["client"].post(path, json={}, headers=headers).json()["state"] == "QUEUED"
    assert (
        f["client"].post(path, json={}, headers={**headers, "Idempotency-Key": uid()}).status_code
        == 409
    )
    viewer = f["sign_in"](f["viewer"])
    assert f["client"].post(path, json={}, headers=viewer).status_code == 403
    f["sign_in"](f["bob"])
    assert f["client"].get(f["base"] + f"/tasks/{tid}").status_code == 404


def test_actual_candidate_drift_blocks_valid_looking_receipt(fixture, tmp_path):
    f = fixture
    tid, _ = queued(f)
    runner = Runner(f["db"], tmp_path / "runner", crash_at="receipt")
    with pytest.raises(RuntimeError):
        runner.run_once()
    with f["db"].connect() as conn:
        row = conn.execute(select(attempts).where(attempts.c.task_id == tid)).mappings().one()
    target = (
        runner.root
        / row["core_task_id"]
        / "core"
        / "workspaces"
        / row["core_task_id"]
        / "settings.json"
    )
    target.write_bytes(b'{"enabled":false,"version":0}\n')
    expire(f, tid)
    with pytest.raises(Problem) as error:
        runner.reconcile(row["core_task_id"])
    assert error.value.code == "candidate_bytes_changed"


@pytest.mark.parametrize("race", ["claim", "cancel", "revoke"])
def test_postgres_separate_connection_races(fixture, tmp_path, race):
    f = fixture
    if f["db"].dialect.name != "postgresql":
        pytest.skip("requires actual PostgreSQL row locks and separate connections")
    tid, _ = queued(f)
    barrier = Barrier(2)
    from intelligenceai.web.service import Service
    from intelligenceai.web.store import engine

    # Independent pools guarantee physical connection separation in the actual operations.
    url = f["db"].url.render_as_string(hide_password=False)
    first = Runner(engine(url, testing=True), tmp_path / "first")
    second = Runner(engine(url, testing=True), tmp_path / "second")
    connections = set()

    def claim():
        with first.db.connect() as conn:
            connections.add(conn.exec_driver_sql("select pg_backend_pid()").scalar_one())
            barrier.wait(timeout=10)
        return first.claim()

    def competing():
        with second.db.connect() as conn:
            connections.add(conn.exec_driver_sql("select pg_backend_pid()").scalar_one())
            barrier.wait(timeout=10)
        if race == "claim":
            return second.claim()
        if race == "cancel":
            return Service(second.db).cancel(f["alice"], f["project"], tid, uid())
        with second.db.begin() as conn:
            conn.execute(
                select(projects).where(projects.c.id == f["project"]).with_for_update()
            ).one()
            conn.execute(
                update(members)
                .where(members.c.project_id == f["project"], members.c.user_id == f["alice"])
                .values(role="revoked")
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=15) for future in [pool.submit(claim), pool.submit(competing)]
        ]
    first.db.dispose()
    second.db.dispose()
    assert len(connections) == 2
    if race == "claim":
        assert sum(result is not None for result in results) == 1
    elif results[0]:
        if race == "cancel":
            assert results[1]["state"] == "CANCEL_REQUESTED"
        else:
            with pytest.raises(Problem):
                first.descriptor(results[0])
    else:
        with f["db"].connect() as conn:
            assert not conn.execute(select(attempts).where(attempts.c.task_id == tid)).first()
