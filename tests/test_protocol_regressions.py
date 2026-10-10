import json
import time

import pytest
from conftest import StubScanner
from test_protocols import FakeExecutable, FakeMCPServer, prepared

from intelligenceai import protocols
from intelligenceai.contracts import Task
from intelligenceai.ledger import Ledger
from intelligenceai.protocols import TransportReply, _ProtocolSession, omnilane_command
from intelligenceai.security import SafetyError


@pytest.fixture
def ledger(tmp_path):
    value = Ledger(tmp_path / "protocol-review.sqlite")
    value.create(
        Task(
            task_id="task",
            redacted_request="owned",
            repo_identity="owned",
            base_sha="base",
            state="READY",
        )
    )
    yield value
    value.close()


class MutatingExecutable(FakeExecutable):
    def __init__(self, target, transform):
        super().__init__()
        self.target, self.transform = target, transform

    def exchange(self, invocation, operation, job_id, *, timeout):
        reply = super().exchange(invocation, operation, job_id, timeout=timeout)
        return self.transform(reply) if operation == self.target else reply


@pytest.mark.parametrize("operation", ["submit", "status", "result", "answer"])
def test_failed_cli_exit_never_parses_success_envelope(ledger, tmp_path, operation):
    fake = MutatingExecutable(operation, lambda r: r.model_copy(update={"exit_code": 1}))
    session = _ProtocolSession(ledger, fake, StubScanner(live=True))
    invocation = prepared(tmp_path)
    if operation != "submit":
        session.submit(invocation)
    with pytest.raises(SafetyError):
        if operation == "submit":
            session.submit(invocation)
        elif operation == "status":
            session.poll(invocation)
        else:
            session.collect(invocation)
    assert ledger.invocations("task")[0]["status"] != "SUCCEEDED"
    assert ledger.task("task")["state"] == "NEEDS_RECONCILIATION"


@pytest.mark.parametrize("handle", ["fixture-job", "../outside", "20261010-060000", "x" * 129])
def test_pinned_job_handle_syntax(handle, tmp_path):
    with pytest.raises(SafetyError):
        omnilane_command(prepared(tmp_path), "status", handle)


def test_fake_executable_rejects_actual_incorrect_argv(tmp_path):
    invocation = prepared(tmp_path)
    for old, new in [("cli", "native"), ("advise", "sysops"), ("--background", "--invented")]:
        changed = invocation.model_copy(
            update={"argv": [new if a == old else a for a in invocation.argv]}
        )
        assert FakeExecutable().exchange(changed, "submit", None, timeout=10).exit_code != 0
    assert omnilane_command(invocation, "answer", "20261010-060000-123-1") == [
        "omnilane",
        "jobs",
        "result",
        "20261010-060000-123-1",
    ]


def test_durable_native_handle_reconciles_status_without_new_route(ledger, tmp_path):
    fake = FakeExecutable()
    invocation = prepared(tmp_path)
    _ProtocolSession(ledger, fake, StubScanner(live=True)).submit(invocation)
    restored = _ProtocolSession(ledger, fake, StubScanner(live=True))
    assert restored.reconcile(invocation) == "READY"
    assert fake.operations == ["submit", "status"]
    assert ledger.task("task")["generation"] == 1
    assert restored.collect(invocation)["answer"] == "Owned opaque answer\n"
    assert fake.operations.count("submit") == 1


def test_metadata_is_not_answer_and_answer_is_redacted(ledger, tmp_path):
    secret = "IAI_TEST_" + "SECRET_C1D2E3F4"
    fake = MutatingExecutable(
        "answer", lambda r: r.model_copy(update={"stdout": secret + " opaque"})
    )
    session = _ProtocolSession(ledger, fake, StubScanner(live=True))
    invocation = prepared(tmp_path)
    session.submit(invocation)
    assert session.poll(invocation)["answer"] is None
    result = session.collect(invocation)
    assert result["answer"] == "[REDACTED] opaque"
    assert result["answer_verification"] == "OPAQUE_UPSTREAM_OUTPUT_ONLY"
    assert secret not in ledger.invocations("task")[0]["receipt"]


@pytest.mark.parametrize("field", ["invocation_id", "provider", "model"])
def test_mco_requested_selector_binding(ledger, tmp_path, field):
    def alter(reply):
        value = json.loads(reply.stdout)
        value["outputs"][0][field] = "different"
        return reply.model_copy(update={"stdout": json.dumps(value)})

    fake = MutatingExecutable("submit", alter)
    session = _ProtocolSession(ledger, fake, StubScanner(live=True))
    with pytest.raises(SafetyError, match="selector"):
        session.submit(prepared(tmp_path, "mco", None))
    assert fake.operations == ["submit"]
    assert ledger.task("task")["state"] == "NEEDS_RECONCILIATION"


def test_mco_exact_argv_reports_selector_but_not_model_attestation(ledger, tmp_path):
    session = _ProtocolSession(ledger, FakeExecutable(), StubScanner(live=True))
    result = session.submit(prepared(tmp_path, "mco", None))
    assert result["selector_verification"] == "MATCHED_UPSTREAM_REPORT_ONLY"
    assert result["model_verification"] == "UNVERIFIED"


@pytest.mark.parametrize("operation", ["poll", "collect", "advance", "cancel", "reconcile"])
def test_one_deadline_all_phases_expired_means_zero_new_calls(
    ledger, tmp_path, monkeypatch, operation
):
    clock = [time.time()]
    monkeypatch.setattr(protocols.time, "time", lambda: clock[0])
    invocation = prepared(tmp_path, "pal", None) if operation == "advance" else prepared(tmp_path)
    fake = FakeMCPServer() if operation == "advance" else FakeExecutable()
    session = _ProtocolSession(ledger, fake, StubScanner(live=True))
    session.submit(invocation)
    before = len(fake.calls if operation == "advance" else fake.operations)
    clock[0] = invocation.deadline + 1
    with pytest.raises(SafetyError, match="deadline"):
        getattr(session, operation)(invocation, "owned") if operation == "advance" else getattr(
            session, operation
        )(invocation)
    assert len(fake.calls if operation == "advance" else fake.operations) == before
    assert ledger.task("task")["state"] == "NEEDS_RECONCILIATION"


def test_late_reply_cannot_become_receipt_and_transport_gets_remaining_time(
    ledger, tmp_path, monkeypatch
):
    clock = [time.time()]
    monkeypatch.setattr(protocols.time, "time", lambda: clock[0])
    invocation = prepared(tmp_path)
    seen = []

    class Late:
        def exchange(self, prepared, operation, handle, *, timeout):
            seen.append(timeout)
            clock[0] = prepared.deadline + 1
            return TransportReply(exit_code=0, stdout="20261010-060000-123-1")

    with pytest.raises(SafetyError, match="deadline"):
        _ProtocolSession(ledger, Late(), StubScanner(live=True)).submit(invocation)
    assert seen == [30.0]
    assert ledger.task("task")["state"] == "NEEDS_RECONCILIATION"
    assert ledger.invocations("task")[0]["receipt"] is None


@pytest.mark.parametrize("boundary", ["pal_starting", "pal_continued", "pal_receipt"])
def test_pal_phase_durable_start_and_receipt_no_duplicate_call(ledger, tmp_path, boundary):
    invocation = prepared(tmp_path, "pal", None)
    fake = FakeMCPServer()
    first = _ProtocolSession(ledger, fake, StubScanner(live=True), boundary)
    first.submit(invocation)
    with pytest.raises(RuntimeError):
        first.advance(invocation, "owned findings")
    count = len(fake.calls)
    restored = _ProtocolSession(ledger, fake, StubScanner(live=True))
    if boundary == "pal_receipt":
        assert restored.reconcile(invocation) == "READY"
        result = restored.advance(invocation, "owned findings")
        assert restored.advance(invocation, "owned findings") == result
        assert result["analysis_scope"] == "INTERNAL_WORKFLOW_NO_EXTERNAL_EXPERT"
    else:
        assert restored.reconcile(invocation) == "NEEDS_RECONCILIATION"
        with pytest.raises(SafetyError):
            restored.advance(invocation, "owned findings")
    assert len(fake.calls) == count


def test_pal_continuation_counts_against_shared_budget(ledger, tmp_path):
    invocation = prepared(tmp_path, "pal", None)
    session = _ProtocolSession(ledger, FakeMCPServer(), StubScanner(live=True))
    session.submit(invocation)
    session.advance(invocation, "owned findings")
    fake = FakeExecutable()
    second = _ProtocolSession(ledger, fake, StubScanner(live=True))
    second.submit(prepared(tmp_path, "mco", None, "mco-second"))
    with pytest.raises(SafetyError, match="budget"):
        second.submit(prepared(tmp_path, "mco", None, "mco-third"))
    assert fake.operations == ["submit"]


def test_google_permission_modes_never_disappear(tmp_path):
    readonly = prepared(tmp_path, "gemini-cli", None)
    assert readonly.argv[-2:] == ["--approval-mode", "plan"]
    step = protocols.Step(
        step_id="write",
        role="implement",
        mode="write",
        executor="gemini-cli",
        provider="gemini",
        model="owned-model",
        effort=None,
        allowed_paths=["module.py"],
    )
    write = protocols.prepare(
        step,
        task_id="task",
        generation=1,
        invocation_id="write",
        request="owned",
        cwd=tmp_path,
        candidate_digest="a" * 64,
    )
    assert write.argv[-2:] == ["--approval-mode", "auto_edit"]
    unsupported = step.model_copy(
        update={"role": "review", "mode": "read_only", "executor": "antigravity"}
    )
    with pytest.raises(SafetyError, match="read-only"):
        protocols.prepare(
            unsupported,
            task_id="task",
            generation=1,
            invocation_id="read",
            request="owned",
            cwd=tmp_path,
            candidate_digest="a" * 64,
        )
