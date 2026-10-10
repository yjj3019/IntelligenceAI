import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from conftest import StubScanner
from pydantic import ValidationError

from intelligenceai import checkers, dag
from intelligenceai.contracts import Check, Plan, Step
from intelligenceai.controller import Controller
from intelligenceai.security import SafetyError


def sample_plan(kind, wrong=False):
    name = "answer.py" if kind == "python" else "settings.json"
    profile = "answer-v1" if kind == "python" else "json-config-v1"
    primary = (
        Check(kind="python_ast", path=name, expected_literals={"ANSWER": 43 if wrong else 42})
        if kind == "python"
        else Check(
            kind="json_shape",
            path=name,
            required_keys=["enabled", "version"],
            expected_literals={"version": 43 if wrong else 42},
        )
    )
    other_path = "module.py" if kind == "python" else "manifest.json"
    other = (
        Check(kind="python_ast", path=other_path, required_symbols=["preserved"])
        if kind == "python"
        else Check(kind="json_shape", path=other_path, required_keys=["name"])
    )
    return Plan(
        steps=[
            Step(
                step_id="write",
                role="implement",
                mode="write",
                allowed_paths=[name],
                profile=profile,
            ),
            Step(
                step_id="shape",
                dependencies=["write"],
                result_refs=["write"],
                role="review",
                mode="read_only",
                executor="static",
                provider="local",
                model="static-v1",
                effort=None,
                allowed_paths=[name],
                checks=[primary],
            ),
            Step(
                step_id="independent",
                dependencies=["write"],
                result_refs=["write"],
                role="analyze",
                mode="read_only",
                executor="static",
                provider="local",
                model="static-v1",
                effort=None,
                allowed_paths=[other_path],
                checks=[other],
            ),
        ]
    )


@pytest.fixture(params=["python", "json"])
def sample(request, repo):
    kind = request.param
    if kind == "python":
        (repo / "module.py").write_text("def preserved():\n    return 'owned sample'\n")
    else:
        (repo / "manifest.json").write_text('{"name":"owned sample"}\n')
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "owned sample"], check=True, capture_output=True
    )
    return repo, kind


@pytest.mark.parametrize("scenario", ["success", "repair", "partial", "crash", "cancel"])
def test_two_project_three_step_e2e(sample, tmp_path, scenario):
    repo, kind = sample
    root = tmp_path / "dag-state"
    crash = (
        "step_committed"
        if scenario in {"crash", "cancel"}
        else "repair_committed"
        if scenario == "repair"
        else None
    )
    ctl = Controller(root, scanner=StubScanner(), crash_at=crash)
    tid = ctl.submit(
        repo,
        "Owned three step sample",
        sample_plan(kind, wrong=scenario == "partial"),
        "repair" if scenario == "repair" else "success",
    )
    if crash:
        with pytest.raises(RuntimeError):
            ctl.run(tid)
        ctl.close()
        ctl = Controller(root, scanner=StubScanner())
    try:
        if scenario == "cancel":
            ctl.reject(tid)
        result = ctl.run(tid)
        assert result["state"] == (
            "CANCELLED"
            if scenario == "cancel"
            else "BLOCKED"
            if scenario == "partial"
            else "READY_FOR_APPROVAL"
        )
        calls = result["invocations"]
        assert len(calls) == (3 if scenario == "partial" else 2 if scenario == "repair" else 1)
        if scenario != "cancel":
            current = result["result"]["steps"]
            assert len(current) == 3
            writer_id = next(r["result_id"] for r in current if r["step_id"] == "write")
            for row in current:
                if row["step_id"] != "write":
                    assert row["references"] == {"write": writer_id}
                    assert row["candidate_id"] == result["result"]["candidate"]["candidate_id"]
            if scenario == "partial":
                assert {r["status"] for r in current} == {"FAILED", "SUCCEEDED"}
            else:
                assert all(r["status"] == "SUCCEEDED" for r in current)
        assert (repo / "user.txt").read_text() == "preserve\n"
        assert not (repo / ("answer.py" if kind == "python" else "settings.json")).exists()
        assert result["repairs"] == (
            2 if scenario == "partial" else 1 if scenario == "repair" else 0
        )
    finally:
        ctl.close()


def test_parallel_readers_receive_same_fixed_candidate(controller, repo, monkeypatch):
    barrier = threading.Barrier(2, timeout=5)
    original = dag.inspect_step
    candidates = []

    def inspect(step, payloads, candidate):
        candidates.append(candidate.candidate_id)
        barrier.wait()
        return original(step, payloads, candidate)

    monkeypatch.setattr(dag, "inspect_step", inspect)
    plan = sample_plan("python")
    other = plan.steps[2].model_copy(
        update={
            "allowed_paths": ["answer.py"],
            "checks": [Check(kind="file_exists", path="answer.py")],
        }
    )
    plan = Plan(steps=[*plan.steps[:2], other])
    tid = controller.submit(repo, "parallel static review", plan)
    assert controller.run(tid)["state"] == "READY_FOR_APPROVAL"
    assert len(candidates) == 2 and len(set(candidates)) == 1


def test_failed_dependency_blocks_child_and_no_fixture_model_call(controller, repo):
    first = Step(
        step_id="check",
        role="review",
        mode="read_only",
        executor="static",
        provider="local",
        model="static-v1",
        effort=None,
        allowed_paths=["missing.json"],
        checks=[Check(kind="file_exists", path="missing.json")],
    )
    second = first.model_copy(
        update={"step_id": "child", "dependencies": ["check"], "result_refs": ["check"]}
    )
    tid = controller.submit(repo, "static failure", Plan(steps=[first, second]))
    result = controller.run(tid)
    assert result["state"] == "BLOCKED" and not result["invocations"] and result["repairs"] == 0
    assert {r["step_id"]: r["status"] for r in result["steps"]} == {
        "check": "FAILED",
        "child": "BLOCKED",
    }


def test_static_parsers_never_execute_code(tmp_path):
    marker = tmp_path / "executed"
    source = f"open({str(marker)!r}, 'w').write('bad')\ndef present(): pass\n".encode()
    evidence, _ = checkers.inspect(
        Check(kind="python_ast", path="plugin.py", required_symbols=["present"]),
        {"plugin.py": source},
        "a" * 64,
    )
    assert evidence.status == "PASS" and not marker.exists()
    evidence, _ = checkers.inspect(
        Check(kind="json_shape", path="config.json", expected_literals={"enabled": True}),
        {"config.json": b'{"enabled":1}'},
        "a" * 64,
    )
    assert evidence.status == "FAIL"


@pytest.mark.parametrize("kind", ["test_command", "build_command"])
def test_command_profile_only_fake_subprocess_contract(tmp_path, kind):
    contract = checkers.command_contract(kind, str(tmp_path), 10)
    assert not contract["enabled"] and not contract["shell"] and not contract["env"]
    fake = Path(__file__).parent / "support/fake_profile.py"
    run = subprocess.run(
        [sys.executable, str(fake)],
        input=json.dumps(contract),
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
        shell=False,
    )
    assert json.loads(run.stdout)["status"] == "PASS"
    evidence, _ = checkers.inspect(
        Check(kind=kind, path="project.py"),
        {"project.py": b"raise RuntimeError('never execute')"},
        "a" * 64,
    )
    assert evidence.status == "UNVERIFIED"
    with pytest.raises(SafetyError):
        checkers.command_contract("arbitrary-shell", str(tmp_path), 10)


def test_result_reference_and_checker_scope_validation():
    with pytest.raises(ValidationError):
        Step(
            step_id="check",
            role="review",
            mode="read_only",
            result_refs=["unrelated"],
            allowed_paths=["a.py"],
        )
    with pytest.raises(ValidationError):
        Step(
            step_id="check",
            role="review",
            mode="read_only",
            allowed_paths=["a.py"],
            checks=[Check(kind="file_exists", path="b.py")],
        )
