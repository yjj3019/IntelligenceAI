import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import StubScanner

from intelligenceai.contracts import Step, Task
from intelligenceai.ledger import Ledger
from intelligenceai.protocols import (
    LiveGateway,
    TransportReply,
    _ProtocolSession,
    omnilane_command,
    pal_continue,
    parse_google,
    parse_mco,
    prepare,
)
from intelligenceai.registry import CAPABILITIES, Capability, authorize_step
from intelligenceai.security import SafetyError


def prepared(tmp_path, executor="omnilane", effort="high", invocation_id="owned-invocation"):
    provider = {
        "omnilane": "codex",
        "mco": "codex",
        "pal": "openai",
        "gemini-cli": "gemini",
        "antigravity": "gemini",
    }[executor]
    step = Step(
        step_id="review",
        role="implement" if executor == "antigravity" else "review",
        mode="write" if executor == "antigravity" else "read_only",
        executor=executor,
        provider=provider,
        model="test-model",
        effort=effort,
        lane="hard-judgment",
        allowed_paths=["module.py"],
    )
    return prepare(
        step,
        task_id="task",
        generation=1,
        invocation_id=invocation_id,
        request="Review without executing code",
        cwd=tmp_path,
        candidate_digest="a" * 64,
    )


class FakeExecutable:
    def __init__(self):
        self.operations = []

    def exchange(self, invocation, operation, job_id, *, timeout):
        self.operations.append(operation)
        argv = (
            invocation.argv
            if operation == "submit"
            else omnilane_command(invocation, operation, job_id)
        )
        process = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "support/fake_vendor.py"), *argv],
            input=invocation.stdin if operation == "submit" else "",
            text=True,
            capture_output=True,
            check=False,
            timeout=min(10, timeout),
            env={},
            cwd=invocation.cwd,
            shell=False,
        )
        return TransportReply(exit_code=process.returncode, stdout=process.stdout)


class FakeMCPServer:
    def __init__(self):
        self.calls = []

    def exchange(self, invocation, operation, job_id, *, timeout):
        call = invocation.messages[0]
        self.calls.append(call)
        assert call.tool == "codereview" and call.arguments["use_assistant_model"] is False
        return TransportReply(
            exit_code=0,
            stdout=json.dumps(
                {
                    "status": "codereview_in_progress"
                    if operation == "submit"
                    else "code_review_complete_ready_for_implementation",
                    "continuation_id": "owned-continuation",
                    "step_number": call.arguments["step_number"],
                }
            ),
        )


@pytest.fixture
def protocol_ledger(tmp_path):
    ledger = Ledger(tmp_path / "protocol.sqlite")
    ledger.create(
        Task(
            task_id="task",
            redacted_request="protocol fixture",
            repo_identity="fixture",
            base_sha="base",
            state="READY",
        )
    )
    yield ledger
    ledger.close()


def test_omnilane_complete_fake_executable(protocol_ledger, tmp_path):
    invocation = prepared(tmp_path)
    assert invocation.argv[:4] == ["omnilane", "route", "--background", "--single-shot"]
    assert invocation.argv[-2:] == ["hard-judgment", "-"] and not invocation.env
    transport = FakeExecutable()
    session = _ProtocolSession(protocol_ledger, transport, StubScanner(live=True))
    assert session.submit(invocation)["native_job_id"] == "20261010-060000-123-1"
    assert session.poll(invocation)["state"] == "done"
    result = session.collect(invocation)
    assert (
        result["answer"] == "Owned opaque answer\n" and result["model_verification"] == "UNVERIFIED"
    )
    assert transport.operations.count("result") == transport.operations.count("answer") == 1
    assert session.collect(invocation) == result
    session.submit(invocation)
    assert transport.operations.count("submit") == 1


@pytest.mark.parametrize("crash", ["starting", "submitted"])
def test_protocol_crash_never_reexecutes(protocol_ledger, tmp_path, crash):
    transport = FakeExecutable()
    invocation = prepared(tmp_path)
    first = _ProtocolSession(protocol_ledger, transport, StubScanner(live=True), crash)
    with pytest.raises(RuntimeError):
        first.submit(invocation)
    restored = _ProtocolSession(protocol_ledger, transport, StubScanner(live=True))
    assert restored.reconcile(invocation) == "NEEDS_RECONCILIATION"
    with pytest.raises(SafetyError):
        restored.submit(invocation)
    assert transport.operations.count("submit") == (crash == "submitted")


def test_input_scan_before_any_transport(protocol_ledger, tmp_path):
    fake = FakeExecutable()
    session = _ProtocolSession(protocol_ledger, fake, StubScanner(status="UNVERIFIED"))
    with pytest.raises(SafetyError):
        session.submit(prepared(tmp_path))
    assert not fake.operations and not protocol_ledger.invocations("task")


def test_cancel_native_rc0_does_not_verify_tree(protocol_ledger, tmp_path):
    session = _ProtocolSession(protocol_ledger, FakeExecutable(), StubScanner(live=True))
    invocation = prepared(tmp_path)
    session.submit(invocation)
    result = session.cancel(invocation)
    assert result["state"] == "NEEDS_RECONCILIATION" and not result["termination_verified"]
    with pytest.raises(SafetyError):
        session._receipt(invocation, {"status": "done"}, "SUCCEEDED")


def test_mco_partial_opaque_answers_and_argv(tmp_path):
    invocation = prepared(tmp_path, "mco", None)
    assert ["--file", "-"] == invocation.argv[invocation.argv.index("--file") :][:2]
    assert "--enforcement-mode" in invocation.argv and "--format" not in invocation.argv
    outputs = [
        {"invocation_id": "a", "status": "success", "output": "untrusted opinion"},
        {"invocation_id": "b", "status": "timeout", "output": None},
    ]
    result = parse_mco(1, json.dumps({"status": "partial", "outputs": outputs}))
    assert result["status"] == "partial" and len(result["outputs"]) == 2
    assert "findings" not in result
    with pytest.raises(SafetyError):
        parse_mco(0, json.dumps({"status": "complete", "outputs": outputs}))


def test_pal_multistep_only_allowlisted_tool(protocol_ledger, tmp_path):
    invocation = prepared(tmp_path, "pal", None)
    fake = FakeMCPServer()
    session = _ProtocolSession(protocol_ledger, fake, StubScanner(live=True))
    session.submit(invocation)
    assert session.advance(invocation, "Static fixture findings")["step_number"] == 2
    assert [c.arguments["step_number"] for c in fake.calls] == [1, 2]
    for tool in ("chat", "clink"):
        with pytest.raises(ValueError):
            invocation.messages[0].model_validate({"tool": tool, "arguments": {}})
    with pytest.raises(SafetyError):
        pal_continue(invocation, {"status": "unknown", "continuation_id": "x"}, "text")


def agy_frames():
    return [
        {"event": "init", "conversation_id": "owned", "init": {"cwd": "/fixture"}},
        {
            "event": "result",
            "result": {
                "conversation_id": "owned",
                "status": "SUCCESS",
                "response": "answer",
                "usage": {},
            },
        },
    ]


def test_google_provider_structures_separate(tmp_path):
    assert (
        parse_google("gemini-cli", 0, json.dumps({"response": "gemini", "stats": {}}))["answer"]
        == "gemini"
    )
    assert (
        parse_google("antigravity", 0, "\n".join(map(json.dumps, agy_frames())))["answer"]
        == "answer"
    )
    with pytest.raises(SafetyError):
        parse_google("gemini-cli", 0, json.dumps(agy_frames()[-1]))
    assert prepared(tmp_path, "antigravity").stdin.startswith('{"event":"user"')


@pytest.mark.parametrize("kind", ["duplicate", "wrong-event", "partial-json", "conversation"])
def test_agy_negative_frames(kind):
    frames = agy_frames()
    if kind == "duplicate":
        frames.append(frames[-1])
    elif kind == "wrong-event":
        frames[0]["event"] = "type"
    elif kind == "conversation":
        frames[-1]["result"]["conversation_id"] = "another"
    payload = "\n".join(map(json.dumps, frames))
    if kind == "partial-json":
        payload = payload[:-2]
    with pytest.raises(SafetyError):
        parse_google("antigravity", 0, payload)


def test_live_gate_has_no_enable_control(tmp_path, monkeypatch):
    monkeypatch.setenv("INTELLIGENCEAI_ENABLE_LIVE", "1")
    monkeypatch.setitem(
        CAPABILITIES, "omnilane", Capability("omnilane", ("codex",), True, "claimed", "untrusted")
    )
    step = Step(
        step_id="review",
        role="review",
        mode="read_only",
        executor="omnilane",
        provider="codex",
        model="m",
        allowed_paths=["module.py"],
    )
    with pytest.raises(SafetyError):
        authorize_step(step)
    for operation in ("submit", "poll", "collect", "cancel", "reconcile"):
        with pytest.raises(SafetyError):
            getattr(LiveGateway, operation)(prepared(tmp_path))


@pytest.mark.parametrize(
    "executor,effort",
    [
        ("mco", "high"),
        ("pal", "high"),
        ("gemini-cli", "high"),
        ("antigravity", "xhigh"),
        ("omnilane", "invented"),
    ],
)
def test_unverified_effort_rejected(tmp_path, executor, effort):
    with pytest.raises(SafetyError):
        prepared(tmp_path, executor, effort)
