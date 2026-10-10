import os
import sys

import pytest

from intelligenceai import supervisor as module
from intelligenceai.security import SafetyError
from intelligenceai.supervisor import (
    ProcessIdentity,
    Supervisor,
    group_members,
    supervision_supported,
)


def test_windows_supervision_disabled(tmp_path):
    if os.name == "posix":
        pytest.skip("Windows-specific fail-closed check")
    with pytest.raises(SafetyError, match="disabled on Windows"):
        Supervisor().launch([sys.executable, "--version"], 1, tmp_path)


@pytest.mark.skipif(
    not supervision_supported(),
    reason="POSIX process group verification; native Windows UNVERIFIED",
)
@pytest.mark.parametrize("operation", ["timeout", "cancel"])
def test_posix_child_tree_termination(tmp_path, operation):
    supervisor = Supervisor()
    code = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); "
        "time.sleep(30)"
    )
    identity = supervisor.launch([sys.executable, "-I", "-c", code], 5, tmp_path)
    if operation == "timeout":
        result, verified = supervisor.wait(0.3)
        assert result is None and verified
    else:
        with pytest.raises(SafetyError, match="generation"):
            supervisor.terminate(4)
        assert supervisor.terminate(5)
    assert not group_members(identity.pid)


def test_changed_birth_or_stale_generation_sends_no_signal(monkeypatch):
    from types import SimpleNamespace

    supervisor = Supervisor()
    supervisor.process = SimpleNamespace(poll=lambda: None)
    supervisor.identity = ProcessIdentity(12345, 5, "original")
    signals = []
    monkeypatch.setattr(module, "start_token", lambda pid: "changed")
    monkeypatch.setattr(module.os, "killpg", lambda *args: signals.append(args), raising=False)
    for generation in (4, 5):
        with pytest.raises(SafetyError):
            supervisor.terminate(generation)
    assert signals == []


@pytest.mark.parametrize("exited", [True, False])
def test_identity_read_failure_cleans_owned_leader_or_accepts_empty_fast_exit(
    monkeypatch, tmp_path, exited
):
    from types import SimpleNamespace

    killed = []
    process = SimpleNamespace(
        pid=12345,
        poll=lambda: 0 if exited else None,
        kill=lambda: killed.append(True),
        wait=lambda timeout: 0,
    )
    monkeypatch.setattr(module, "supervision_supported", lambda: True)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(module, "group_members", lambda pid: set())

    def unavailable(pid):
        raise SafetyError("owned identity unavailable")

    monkeypatch.setattr(module, "start_token", unavailable)
    supervisor = Supervisor()
    if exited:
        assert supervisor.launch(["owned"], 1, tmp_path).start_token == "exited-before-identity"
        assert supervisor.wait(1) == (0, True)
        assert not killed
    else:
        with pytest.raises(SafetyError, match="cleanup"):
            supervisor.launch(["owned"], 1, tmp_path)
        assert killed == [True]


def test_darwin_enumeration_failure_is_not_empty(monkeypatch):
    from types import SimpleNamespace

    class Denied(Exception):
        pass

    backend = SimpleNamespace(Error=Denied, NoSuchProcess=ProcessLookupError, pids=lambda: [1])
    monkeypatch.setattr(module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(module, "_psutil", lambda: backend)

    def denied(pid):
        raise PermissionError("owned denial")

    monkeypatch.setattr(module.os, "getpgid", denied, raising=False)
    with pytest.raises(SafetyError, match="enumeration"):
        group_members(12345)


@pytest.mark.skipif(not supervision_supported(), reason="Native POSIX ordinary group test")
def test_exited_leader_with_surviving_group_is_unverified(tmp_path):
    import signal
    import time

    supervisor = Supervisor()
    code = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); time.sleep(30)"
    )
    identity = supervisor.launch([sys.executable, "-I", "-c", code], 7, tmp_path)
    try:
        deadline = time.monotonic() + 5
        while len(group_members(identity.pid)) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(group_members(identity.pid)) >= 2
        supervisor.process.kill()  # Only this test's owned leader, leaving its owned child.
        supervisor.process.wait(timeout=3)
        assert group_members(identity.pid)
        with pytest.raises(SafetyError, match="remaining group"):
            supervisor.terminate(7)
    finally:
        # Test cleanup only; production supervisor deliberately refuses this uncertain group.
        os.killpg(identity.pid, signal.SIGKILL)
        deadline = time.monotonic() + 3
        while group_members(identity.pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not group_members(identity.pid)
