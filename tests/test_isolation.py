import json
import os
import platform
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from intelligenceai.isolation import LinuxOfflineExecutor, file_digest, tree_digest
from intelligenceai.isolation_contracts import (
    CapabilityEvidence,
    InvocationBudget,
    LaunchManifest,
    NetworkPolicy,
    PinnedRoot,
    live_readiness,
    reject_control_paths,
)
from intelligenceai.security import SafetyError, digest, redact


def manifest_for(tmp_path):
    image = tmp_path / "image"
    workspace = tmp_path / "workspace"
    image.mkdir()
    workspace.mkdir()
    (image / "probe").write_bytes(b"unpaid synthetic probe, not executable")
    (workspace / "readonly.txt").write_text("readonly")
    (workspace / "heartbeat").write_text("0")
    backend = tmp_path / "bwrap"
    backend.write_bytes(b"synthetic backend for argv tests only")
    return backend, LaunchManifest(
        invocation_id=str(uuid4()),
        task_id=str(uuid4()),
        project_id=str(uuid4()),
        actor_id=str(uuid4()),
        generation=1,
        provider="isolation-probe",
        model="offline-probe",
        effort=None,
        mode="write",
        host_os="Linux",
        backend="linux-bwrap-offline-v1",
        backend_binary_digest=file_digest(backend),
        vendor_binary_digest=file_digest(image / "probe"),
        runner_digest=file_digest(image / "probe"),
        policy_digest=digest({"backend": "linux-bwrap-offline-v1", "network": "deny"}),
        image=PinnedRoot(path=str(image), tree_digest=tree_digest(image)),
        workspace=PinnedRoot(path=str(workspace), tree_digest=tree_digest(workspace)),
        writable_files=("heartbeat",),
        network=NetworkPolicy(),
        deadline=time.time() + 5,
        budget=InvocationBudget(max_invocations=1, max_cost_microusd=1),
    )


@pytest.mark.parametrize("provider", ["claude", "codex", "grok", "gemini-cli", "antigravity"])
@pytest.mark.parametrize("host", ["Linux", "Darwin", "Windows"])
@pytest.mark.parametrize("mode", ["read_only", "write"])
def test_no_readiness_report_can_authorize_live(provider, host, mode, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: "/synthetic/bwrap")
    report = live_readiness(provider, mode, host_os=host)
    assert report["status"] == "BLOCKED"
    assert report["live_model"] == "NOTRUN"
    assert report["os_isolation"] == "UNVERIFIED"
    assert report["wrapper_attempts"] == 1
    assert report["native_retries"] == "UNVERIFIED"
    if (provider, host, mode) == ("grok", "Darwin", "write"):
        assert "grok_macos_write_unsupported" in report["reasons"]


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "foo/.mcp.json",
        r"foo\.claude\settings.json",
        "AGENTS.md",
        ".gemini/settings.json",
    ],
)
def test_project_control_files_are_rejected(path):
    with pytest.raises(SafetyError):
        reject_control_paths((path,))


def test_manifest_authority_binding_and_scope(tmp_path):
    _, manifest = manifest_for(tmp_path)
    for key, value in {
        "generation": 2,
        "policy_digest": "a" * 64,
        "model": "changed",
        "deadline": manifest.deadline + 1,
        "actor_id": str(uuid4()),
    }.items():
        assert manifest.model_copy(update={key: value}).binding != manifest.binding
    proof = CapabilityEvidence(
        manifest_digest=manifest.binding,
        host_os="Linux",
        provider="isolation-probe",
        mode="write",
        expires_at=manifest.deadline,
        scope="OFFLINE_PROBE",
        evidence_digest="f" * 64,
    )
    assert proof.matches(manifest, now=time.time())
    assert not proof.matches(manifest, now=manifest.deadline)
    assert not proof.model_copy(update={"scope": "LIVE_PROVIDER"}).matches(
        manifest, now=time.time()
    )
    with pytest.raises(ValidationError):
        manifest.model_copy(update={"fallback_allowed": True}).revalidate()
    with pytest.raises(ValidationError):
        manifest.model_copy(update={"deadline": float("nan")}).revalidate()
    with pytest.raises(ValidationError):
        manifest.model_copy(update={"invocation_id": "-" * 36}).revalidate()
    with pytest.raises(ValidationError):
        InvocationBudget(max_invocations=1, max_cost_microusd=1, wrapper_attempts=5)


def test_fixed_offline_command_cannot_become_vendor_launch(tmp_path, monkeypatch):
    backend, manifest = manifest_for(tmp_path)
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    command = LinuxOfflineExecutor(backend).command(manifest)
    assert "--unshare-all" in command and "--clearenv" in command
    assert command[-2:] == ("--", "/probe")
    assert "--bind" in command and "--ro-bind" in command
    assert "--cap-drop" in command
    with pytest.raises(SafetyError, match="live_provider"):
        LinuxOfflineExecutor(backend).command(
            manifest.model_copy(
                update={
                    "provider": "codex",
                    "overlay_digest": "a" * 64,
                    "caller_context_digest": "b" * 64,
                }
            )
        )
    # A Pydantic model_copy can insert an ignored unknown Python attribute; the
    # trusted compiler still emits its fixed command. JSON construction rejects it.
    assert (
        LinuxOfflineExecutor(backend).command(manifest.model_copy(update={"argv": ("sh",)}))
        == command
    )
    with pytest.raises(ValidationError):
        LaunchManifest.model_validate(manifest.model_dump() | {"argv": ("sh",)})
    (Path(manifest.image.path) / "probe").write_bytes(b"drift")
    with pytest.raises(SafetyError, match="image_digest_drift"):
        LinuxOfflineExecutor(backend).command(manifest)


def test_hook_pollution_rejected_before_spawn(tmp_path, monkeypatch):
    backend, manifest = manifest_for(tmp_path)
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    (Path(manifest.workspace.path) / ".mcp.json").write_text("{}")
    with pytest.raises(SafetyError, match="configuration"):
        LinuxOfflineExecutor(backend).command(manifest)


def test_linked_tree_cannot_enter_image(tmp_path):
    target = tmp_path / "original"
    target.write_text("not a credential")
    root = tmp_path / "root"
    root.mkdir()
    try:
        os.link(target, root / "linked")
    except OSError:
        pytest.skip("test filesystem has no hardlinks")
    with pytest.raises(SafetyError, match="linked"):
        tree_digest(root)


@pytest.mark.parametrize("termination", ["deadline", "cancel"])
def test_actual_linux_namespace_malicious_probe(
    tmp_path, monkeypatch, termination, record_property
):
    # No installation, privilege change or fallback. Every skip is explicitly BLOCKED.
    if platform.system() != "Linux":
        pytest.skip("BLOCKED: Linux namespace backend unsupported on this OS; live NOTRUN")
    bwrap, compiler = shutil.which("bwrap"), shutil.which("gcc")
    if not bwrap or not compiler:
        pytest.skip("BLOCKED: preinstalled bwrap/static compiler unavailable; live NOTRUN")
    backend, manifest = manifest_for(tmp_path)
    host = tmp_path / "host-ledger-sentinel"
    host.write_text("test-owned ledger and credential sentinel")
    image = Path(manifest.image.path)
    for directory in ("proc", "dev", "tmp", "home", "workspace"):
        (image / directory).mkdir()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        compiled = subprocess.run(
            [
                compiler,
                "-static",
                "-O2",
                "-Wall",
                "-Werror",
                "-DHOST_SENTINEL=" + json.dumps(str(host)),
                "-DHOST_PORT=" + str(listener.getsockname()[1]),
                str(Path(__file__).parent / "support/isolation_probe.c"),
                "-o",
                str(image / "probe"),
            ],
            capture_output=True,
            timeout=20,
            check=False,
        )
        if compiled.returncode:
            errors = compiled.stderr.decode("utf-8", errors="replace")
            if any(
                message in errors
                for message in ("cannot find -lc", "cannot find crt1.o", "cannot find -lgcc")
            ):
                pytest.skip("BLOCKED: preinstalled compiler lacks static runtime dependencies")
            pytest.fail("static probe compile FAILED: " + redact(errors[:1024]))
        (image / "probe").chmod(0o755)
        monkeypatch.setenv("IAI_PROBE_HOST_MARKER", "test-owned environment sentinel")
        backend = Path(bwrap)
        manifest = manifest.model_copy(
            update={
                "backend_binary_digest": file_digest(backend),
                "vendor_binary_digest": file_digest(image / "probe"),
                "runner_digest": file_digest(image / "probe"),
                "image": PinnedRoot(path=str(image), tree_digest=tree_digest(image)),
                "deadline": time.time() + (2 if termination == "deadline" else 5),
            }
        )
        cancel = threading.Event()
        timer = threading.Timer(1.5, cancel.set) if termination == "cancel" else None
        if timer:
            timer.start()
        try:
            result = LinuxOfflineExecutor(backend).run(manifest, cancel)
        finally:
            if timer:
                timer.cancel()
                timer.join()
        for name, value in {
            "manifest_digest": manifest.binding,
            "policy_digest": manifest.policy_digest,
            "backend_binary_digest": manifest.backend_binary_digest,
            "runner_digest": manifest.runner_digest,
            "image_digest": manifest.image.tree_digest,
            "host_os": manifest.host_os,
            "provider": manifest.provider,
            "mode": manifest.mode,
        }.items():
            record_property(name, value)
        if "bwrap:" in result.output and any(
            x in result.output
            for x in (
                "Operation not permitted",
                "Permission denied",
                "No permissions to create",
                "not supported",
            )
        ):
            pytest.skip("BLOCKED: kernel/user namespace policy denies existing backend")
        assert result.termination == (
            "DEADLINE" if termination == "deadline" else "CANCEL_REQUESTED"
        )
        assert result.scope == "OFFLINE_PROBE" and result.live_model == "NOTRUN"
        checks = json.loads(result.output.strip())
        assert all(checks.values()), checks
        heartbeat = Path(manifest.workspace.path) / "heartbeat"
        final = heartbeat.read_text()
        assert final != "0", "setsid descendant must actually run"
        time.sleep(0.15)
        assert heartbeat.read_text() == final, "setsid descendant survived namespace termination"
        assert (Path(manifest.workspace.path) / "readonly.txt").read_text() == "readonly"
    finally:
        listener.close()
