import json
import os
import threading
from pathlib import Path

import pytest
from conftest import StubScanner
from pydantic import ValidationError

from intelligenceai import fixture
from intelligenceai.adapter_contracts import validate_stream
from intelligenceai.contracts import Step, Task
from intelligenceai.controller import Controller, fixture_plan
from intelligenceai.ledger import Ledger
from intelligenceai.security import SafetyError, canonical


def test_antigravity_official_event_positive():
    frames = [
        json.dumps(frame)
        for frame in [
            {
                "event": "init",
                "conversation_id": "fixture-id",
                "init": {"cwd": "/fixture", "tools": [], "permission_mode": "request-review"},
            },
            {
                "event": "step_update",
                "step_update": {
                    "conversation_id": "fixture-id",
                    "step_index": 0,
                    "state": "DONE",
                    "step_type": "user_input",
                },
            },
            {
                "event": "result",
                "result": {
                    "conversation_id": "fixture-id",
                    "status": "SUCCESS",
                    "response": "fixture answer",
                    "usage": {"total_tokens": 0},
                },
            },
        ]
    ]
    assert validate_stream("antigravity", frames).status == "TERMINAL_FRAME_ONLY"


def test_gemini_official_type_positive():
    frames = [json.dumps({"type": event}) for event in ["init", "message", "result"]]
    assert validate_stream("gemini-cli", frames).status == "TERMINAL_FRAME_ONLY"


@pytest.mark.parametrize(
    "executor,frames",
    [
        ("antigravity", [{"type": "init"}, {"type": "result"}]),
        ("gemini-cli", [{"event": "init"}, {"event": "result"}]),
        ("antigravity", [{"event": "init"}, {"type": "result"}]),
        ("gemini-cli", [{"type": "init"}, {"event": "result"}]),
        ("antigravity", [{"event": "init", "type": "init"}, {"event": "result"}]),
    ],
)
def test_stream_discriminator_mixing_refused(executor, frames):
    with pytest.raises(SafetyError):
        validate_stream(executor, [json.dumps(frame) for frame in frames])


def test_implement_read_only_rejected_at_schema():
    with pytest.raises(ValidationError):
        Step(step_id="implement", role="implement", mode="read_only", allowed_paths=["answer.py"])


def test_unvalidated_model_copy_rejected_before_submit_effect(controller, tmp_path):
    step = fixture_plan().steps[0].model_copy(update={"mode": "read_only"})
    plan = fixture_plan().model_copy(update={"steps": [step]})
    with pytest.raises((ValidationError, SafetyError)):
        controller.submit(tmp_path / "nonexistent-repo", "fixture", plan)
    assert controller.ledger.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


def test_real_write_boundary_requires_active_writer_lease(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite")
    target = tmp_path / "workspace"
    target.mkdir()
    ledger.create(
        Task(task_id="task", redacted_request="fixture", repo_identity="fixture", base_sha="base")
    )
    read_only = Step(step_id="review", role="review", mode="read_only", allowed_paths=["answer.py"])
    record = ledger.reserve("task", read_only, 0, str(target))
    ledger.start(record["id"])
    try:
        with pytest.raises(SafetyError):
            fixture.implement(
                target, 0, "success", ledger=ledger, invocation_id=record["id"], generation=1
            )
        assert not (target / "answer.py").exists()
    finally:
        ledger.close()


def test_repair_commit_before_checkpoint_crash_replay(repo, tmp_path):
    root = tmp_path / "repair-state"
    controller = Controller(root, scanner=StubScanner(), crash_at="repair_committed")
    task = controller.submit(repo, "repair", scenario="repair")
    try:
        with pytest.raises(RuntimeError, match="repair_committed"):
            controller.run(task)
        assert controller.ledger.task(task)["repairs"] == 1
    finally:
        controller.close()
    fresh = Controller(root, scanner=StubScanner())
    try:
        result = fresh.run(task)
        assert result["state"] == "READY_FOR_APPROVAL"
        assert result["repairs"] == 1
        assert len(result["invocations"]) == 2
        assert fresh.ledger.db.execute("SELECT count(*) FROM repair_decisions").fetchone()[0] == 1
        assert fresh.ledger.db.execute("SELECT count FROM failures").fetchone()[0] == 1
        assert (
            Path(fresh.metadata(task)["workspace"]) / "answer.py"
        ).read_text() == "ANSWER = 42\n"
    finally:
        fresh.close()


def test_corrupted_persisted_read_only_implementation_never_writes(controller, repo):
    task = controller.submit(repo, "fixture")
    data = controller.metadata(task)
    data["plan"]["steps"][0]["mode"] = "read_only"
    controller.ledger.db.execute("UPDATE tasks SET data=? WHERE id=?", (canonical(data), task))
    with pytest.raises(ValidationError):
        controller._execute({"task_id": task, "round_number": 0, "owner_generation": 1})
    assert not (Path(data["workspace"]) / "answer.py").exists()
    assert not controller.ledger.invocations(task)


def test_atomic_state_cancel_two_connections_barrier(tmp_path):
    path = tmp_path / "barrier.sqlite"
    seed = Ledger(path)
    seed.create(
        Task(
            task_id="task",
            redacted_request="fixture",
            repo_identity="fixture",
            base_sha="base",
            state="READY",
        )
    )
    seed.close()
    selected, release, cancelled = threading.Event(), threading.Event(), threading.Event()
    errors = []

    def transition():
        ledger = Ledger(path)
        original = ledger.task
        paused = False

        def task_read(task_id):
            nonlocal paused
            task = original(task_id)
            if not paused:
                paused = True
                selected.set()
                assert release.wait(5)
            return task

        ledger.task = task_read
        try:
            ledger.state("task", "RUNNING", expected_generation=1)
        except BaseException as exc:
            errors.append(exc)
        finally:
            ledger.close()

    def cancel():
        ledger = Ledger(path)
        try:
            ledger.cancel("task")
            cancelled.set()
        except BaseException as exc:
            errors.append(exc)
        finally:
            ledger.close()

    first = threading.Thread(target=transition)
    first.start()
    assert selected.wait(5)
    second = threading.Thread(target=cancel)
    second.start()
    # Before the fix cancellation commits in this gap and state() overwrites it.
    # With BEGIN IMMEDIATE it waits until the transition commits, then wins.
    cancelled.wait(0.3)
    release.set()
    first.join(5)
    second.join(5)
    assert not first.is_alive() and not second.is_alive() and not errors
    ledger = Ledger(path)
    try:
        assert ledger.task("task")["state"] == "CANCELLED"
        assert ledger.task("task")["generation"] == 2
        with pytest.raises(SafetyError, match="generation"):
            ledger.state("task", "RUNNING", expected_generation=1)
        with pytest.raises(SafetyError):
            ledger.reserve("task", fixture_plan().steps[0], 0, "workspace", expected_generation=1)
        assert not ledger.invocations("task")
    finally:
        ledger.close()


def test_candidate_value_error_permanently_revokes_approval(approval_controller, repo, monkeypatch):
    from intelligenceai.contracts import Action

    controller = approval_controller
    task = controller.submit(repo, "fixture")
    controller.run(task)
    action = Action(kind="push", destination="example.invalid", argv=["push", "fixture"])
    controller.approve(task, action, "operator")
    original = controller.candidate

    def invalid_candidate(task_id):
        raise ValueError("unsafe artifact path")

    monkeypatch.setattr(controller, "candidate", invalid_candidate)
    with pytest.raises(SafetyError):
        controller.dry_run(task, action)
    monkeypatch.setattr(controller, "candidate", original)
    assert controller.status(task)["state"] == "BLOCKED"
    assert controller.ledger.db.execute("SELECT count(*) FROM approvals").fetchone()[0] == 0
    with pytest.raises(SafetyError):
        controller.dry_run(task, action)


@pytest.mark.skipif(
    os.name == "nt", reason="NUL is an OS device on Windows; Linux artifact fixture"
)
def test_linux_nul_artifact_removal_never_revives_approval(approval_controller, repo):
    from intelligenceai.contracts import Action

    controller = approval_controller
    task = controller.submit(repo, "fixture")
    controller.run(task)
    action = Action(kind="push", destination="example.invalid", argv=["push", "fixture"])
    controller.approve(task, action, "operator")
    path = Path(controller.metadata(task)["workspace"]) / "NUL"
    path.write_text("invalid candidate path")
    with pytest.raises(SafetyError):
        controller.dry_run(task, action)
    path.unlink()
    with pytest.raises(SafetyError):
        controller.dry_run(task, action)
    assert controller.ledger.db.execute("SELECT count(*) FROM approvals").fetchone()[0] == 0


@pytest.mark.parametrize("link_kind", ["dangling", "hardlink", "replacement-race"])
def test_fixture_links_never_create_or_change_external_file(tmp_path, link_kind, monkeypatch):
    ledger = Ledger(tmp_path / "link-ledger.sqlite")
    target = tmp_path / "workspace"
    target.mkdir()
    outside = tmp_path / "external.txt"
    path = target / "answer.py"
    if link_kind == "hardlink":
        outside.write_bytes(b"original external bytes")
        os.link(outside, path)
    elif link_kind == "dangling":
        try:
            path.symlink_to(outside)
        except OSError:
            ledger.close()
            pytest.skip("native symlink privilege unavailable; Linux CI covers fixture")
    else:
        original_replace = os.replace

        def swapped(temporary, destination):
            try:
                path.symlink_to(outside)
            except OSError:
                pytest.skip("native symlink privilege unavailable; Linux CI covers fixture")
            original_replace(temporary, destination)

        monkeypatch.setattr(os, "replace", swapped)
    ledger.create(
        Task(
            task_id="task",
            redacted_request="fixture",
            repo_identity="fixture",
            base_sha="base",
            state="RUNNING",
        )
    )
    record = ledger.reserve("task", fixture_plan().steps[0], 0, str(target))
    ledger.start(record["id"])
    try:
        if link_kind == "replacement-race":
            fixture.implement(
                target, 0, "success", ledger=ledger, invocation_id=record["id"], generation=1
            )
            assert path.read_text() == "ANSWER = 42\n" and not path.is_symlink()
        else:
            with pytest.raises(SafetyError, match="linked"):
                fixture.implement(
                    target, 0, "success", ledger=ledger, invocation_id=record["id"], generation=1
                )
        if link_kind == "hardlink":
            assert outside.read_bytes() == b"original external bytes"
        else:
            assert not outside.exists()
    finally:
        ledger.close()


def test_repair_decision_replay_and_conflicting_identity(tmp_path):
    ledger = Ledger(tmp_path / "repairs.sqlite")
    ledger.create(
        Task(task_id="task", redacted_request="fixture", repo_identity="fixture", base_sha="base")
    )
    try:
        assert ledger.repair(
            "task", "signature", operation_id="logical-repair", expected_generation=1
        )
        assert ledger.repair(
            "task", "signature", operation_id="logical-repair", expected_generation=1
        )
        assert ledger.task("task")["repairs"] == 1
        assert ledger.db.execute("SELECT count FROM failures").fetchone()[0] == 1
        with pytest.raises(SafetyError, match="identity"):
            ledger.repair("task", "changed", operation_id="logical-repair", expected_generation=1)
    finally:
        ledger.close()
