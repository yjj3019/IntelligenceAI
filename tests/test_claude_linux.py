"""Actual unpaid namespace/relay probe. No live credential or model compatibility claim."""

import json
import os
import re
import select
import shutil
import subprocess
import sys
import sysconfig
import time
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("httpx")

import httpx
from test_claude_transport import fixture as shared_fixture
from test_claude_transport import profile_for, reservation, stored, stream

from intelligenceai.isolation import file_digest, tree_digest
from intelligenceai.isolation_contracts import (
    InvocationBudget,
    LaunchManifest,
    NetworkPolicy,
    PinnedRoot,
)
from intelligenceai.security import SafetyError, canonical
from intelligenceai.web import cgroup_enter, claude_bridge
from intelligenceai.web.claude_broker import ClaudeBroker
from intelligenceai.web.claude_contracts import claude_argv
from intelligenceai.web.claude_runner import ClaudeReviewRunner, DelegatedCgroup, UnixRelay
from intelligenceai.web.store import uid

fixture = shared_fixture


def python_image(image):
    """Ephemeral CI only: copy the official system/runtime Python, never user configuration."""
    image.mkdir()
    for directory in ("proc", "dev", "tmp", "home", "relay"):
        (image / directory).mkdir()
    python = Path(sys.executable).resolve()
    shutil.copyfile(python, image / "python")
    (image / "python").chmod(0o755)
    stdlib = Path(sysconfig.get_path("stdlib"))
    shutil.copytree(
        stdlib,
        image / "usr" / "lib" / stdlib.name,
        ignore=shutil.ignore_patterns("site-packages", "__pycache__", "test", "tests", "idlelib"),
    )
    libraries = [python, *stdlib.glob("lib-dynload/*.so")]
    dependencies = "\n".join(
        subprocess.run(
            ["ldd", str(library)], capture_output=True, text=True, timeout=5, check=True
        ).stdout
        for library in libraries
    )
    for name in set(re.findall(r"(/[A-Za-z0-9_./+-]+)", dependencies)):
        source = Path(name)
        if source.is_file():
            target = image / source.relative_to("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source.resolve(), target)
            target.chmod(0o755)
            if source.name.startswith("libpython"):
                (image / "lib").mkdir(exist_ok=True)
                shutil.copyfile(source.resolve(), image / "lib" / source.name)
    shutil.copyfile(Path(claude_bridge.__file__), image / "bridge.py")
    shutil.copyfile(Path(__file__).parent / "support" / "fake_claude_relay.py", image / "claude")
    (image / "claude").chmod(0o755)


@pytest.mark.skipif(sys.platform != "linux", reason="actual Linux namespace probe only")
def test_actual_linux_namespace_bridge_fixed_provider_and_no_external_route(fixture, tmp_path):
    backend = shutil.which("bwrap")
    if backend is None:
        pytest.skip("BLOCKED: pinned bubblewrap unavailable; live provider NOTRUN")
    profile = profile_for(fixture)
    image, relay = tmp_path / "image", tmp_path / "relay"
    python_image(image)
    relay.mkdir(mode=0o700)
    profile = profile.model_copy(
        update={
            "image": PinnedRoot(path=str(image), tree_digest=tree_digest(image)),
            "backend_digest": file_digest(Path(backend)),
            "cli_digest": file_digest(image / "claude"),
            "bridge_digest": file_digest(image / "bridge.py"),
        }
    )
    ledger, intent, profile, prompt = reservation(fixture, profile_override=profile)
    # This test exercises actual namespaces and the relay wire separately from the
    # production paid runner, which additionally requires cgroups/PG/signed receipts.
    manifest = LaunchManifest(
        invocation_id=intent.invocation_id,
        task_id=intent.approval.task_id,
        project_id=intent.approval.project_id,
        actor_id=intent.approval.actor_id,
        generation=1,
        provider="claude",
        model=profile.model,
        effort=profile.effort,
        mode="read_only",
        host_os="Linux",
        backend="linux-bwrap-claude-relay-v1",
        backend_binary_digest=profile.backend_digest,
        vendor_binary_digest=profile.cli_digest,
        runner_digest=file_digest(Path(cgroup_enter.__file__)),
        policy_digest=profile.policy_digest,
        image=profile.image,
        workspace=profile.image,
        network=NetworkPolicy(provider_hosts=("api.anthropic.com",)),
        overlay_digest="f" * 64,
        caller_context_digest="f" * 64,
        deadline=float(__import__("time").time() + 30),
        budget=InvocationBudget(max_invocations=1, max_cost_microusd=240),
    )
    # Existing synthetic reservation retains its original pricing profile, equal rates.
    ledger.claim_launch(intent)
    calls = []

    def upstream(req):
        calls.append(req)
        assert req.headers["x-api-key"] == "fixture-broker-only"
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=stream(profile)
        )

    broker = ClaudeBroker(
        ledger,
        intent,
        profile,
        lambda: "fixture-broker-only",
        prompt,
        transport=httpx.MockTransport(upstream),
    )
    executor = ClaudeReviewRunner.__new__(ClaudeReviewRunner)
    executor.backend = Path(backend)
    command = executor.command(manifest, profile, relay)
    descriptor = canonical(
        {
            "capability": "fixture-relay-only",
            "prompt": prompt,
            "argv": claude_argv(profile),
            "seconds": 10,
        }
    ).encode()
    with UnixRelay(relay, broker, "fixture-relay-only"):
        result = subprocess.run(
            command, input=descriptor, capture_output=True, timeout=20, env={"LANG": "C.UTF-8"}
        )
    if result.returncode != 0 and b"Operation not permitted" in result.stderr:
        pytest.fail("BLOCKED: kernel namespace unavailable; no security setting changes permitted")
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert json.loads(result.stdout)["result"] == "FAKE_CLI_TEST_ONLY"
    assert len(calls) == 1 and stored(fixture, intent)[0]["state"] == "SETTLED"
    assert broker.result == "FAKE_PROVIDER_TEST_ONLY"


@pytest.mark.skipif(sys.platform != "linux", reason="actual delegated Linux cgroup only")
def test_actual_delegated_cgroup_atomic_descendant_cleanup(fixture):
    root = os.environ.get("IAI_TEST_DELEGATED_CGROUP")
    if not root:
        pytest.skip(
            "BLOCKED: no existing delegated cgroup subtree; resource enforcement UNVERIFIED"
        )
    _, _, profile, _ = reservation(fixture)
    group = DelegatedCgroup(Path(root), uid(), profile)
    read_fd, write_fd = os.pipe()
    child = None
    try:
        child = subprocess.Popen(
            [
                sys.executable,
                str(Path(cgroup_enter.__file__)),
                str(read_fd),
                sys.executable,
                "-c",
                "import os,time; child=os.fork(); "
                "role='child' if child==0 else 'parent'; "
                "os.write(1,(role+':'+str(os.getpid())+'\\n').encode()); time.sleep(60)",
            ],
            pass_fds=(read_fd,),
            env={},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
        )
        group.attach(child.pid)
        os.write(write_fd, b"1")
        ready = {}
        buffer = bytearray()
        deadline = time.monotonic() + 5
        while len(ready) < 2:
            remaining = deadline - time.monotonic()
            assert remaining > 0, "parent and forked child did not execute"
            assert select.select([child.stdout], [], [], remaining)[0]
            chunk = os.read(child.stdout.fileno(), 128)
            assert chunk, "child process exited before heartbeat"
            buffer.extend(chunk)
            assert len(buffer) <= 128
            while b"\n" in buffer:
                line, _, rest = buffer.partition(b"\n")
                buffer = bytearray(rest)
                role, _, process_id = line.decode("ascii").partition(":")
                assert role in {"parent", "child"} and role not in ready
                ready[role] = int(process_id)
        assert ready["parent"] == child.pid and ready["child"] != child.pid
        members = set(map(int, (group.path / "cgroup.procs").read_text().split()))
        assert set(ready.values()) <= members
        assert group.kill_and_verify()
        assert child.wait(timeout=3) != 0
        for process_id in ready.values():
            status = Path(f"/proc/{process_id}/stat")
            if status.exists():
                assert status.read_text().rsplit(") ", 1)[1].split()[0] == "Z"
        assert child.stdout.read() == b""
    finally:
        os.close(read_fd)
        os.close(write_fd)
        if group.path.exists():
            group.kill_and_verify()
        if child is not None and child.poll() is None:
            child.kill()
            child.wait(timeout=3)
        if child is not None and child.stdout is not None:
            child.stdout.close()


def test_resource_scope_is_blocked_without_delegation(fixture, tmp_path):
    _, _, profile, _ = reservation(fixture)
    with pytest.raises(SafetyError):
        DelegatedCgroup(tmp_path, uid(), profile)
