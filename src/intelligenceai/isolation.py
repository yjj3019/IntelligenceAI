"""Offline Linux probe executor, deliberately separate from the fixture supervisor.

This is not a live provider backend. A verified probe cannot enable paid execution.
The operator supplies an immutable root image; this module never installs a backend,
downloads an image, inherits a HOME, or accepts commands from an HTTP request.
"""

import hashlib
import os
import platform
import signal
import stat
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .isolation_contracts import LaunchManifest, reject_control_paths
from .security import SafetyError, digest, redact

MAX_TREE_BYTES = 512 * 1024 * 1024
MAX_TREE_FILES = 30_000
MAX_OUTPUT = 64 * 1024


def file_digest(path: Path) -> str:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SafetyError("non_regular_or_linked_file")
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def tree_digest(root: Path) -> str:
    """Pin bytes and permission bits; exclude special files, symlinks and hardlinks."""
    if not root.is_absolute() or not root.is_dir():
        raise SafetyError("invalid_operator_root")
    for parent in (root, *root.parents):
        if parent.is_symlink():
            raise SafetyError("linked_operator_root")
    records = [(".", stat.S_IMODE(root.lstat().st_mode), "directory")]
    total = 0
    count = 0
    for current, directories, files in os.walk(root, followlinks=False):
        for name in sorted(directories + files):
            path = Path(current) / name
            relative = path.relative_to(root).as_posix()
            reject_control_paths((relative,))
            info = path.lstat()
            count += 1
            if count > MAX_TREE_FILES:
                raise SafetyError("operator_tree_limit")
            if info.st_mode & (stat.S_ISUID | stat.S_ISGID):
                raise SafetyError("privileged_image_file")
            if stat.S_ISDIR(info.st_mode):
                records.append((relative, stat.S_IMODE(info.st_mode), "directory"))
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                total += info.st_size
                if total > MAX_TREE_BYTES:
                    raise SafetyError("operator_tree_limit")
                records.append((relative, stat.S_IMODE(info.st_mode), file_digest(path)))
            else:
                raise SafetyError("non_regular_or_linked_file")
    return digest(sorted(records))


@dataclass(frozen=True)
class ProbeResult:
    manifest_digest: str
    status: str
    returncode: int
    output: str
    output_truncated: bool
    termination: str
    # Namespace cleanup needs an independent descendant probe, not a successful wait().
    cleanup: str = "UNVERIFIED"
    scope: str = "OFFLINE_PROBE"
    live_model: str = "NOTRUN"


class LinuxOfflineExecutor:
    """Trusted operator-only fixed probe. No shell, provider dispatch, or fallback."""

    def __init__(self, backend_binary: Path):
        self.backend_binary = backend_binary

    def command(self, manifest: LaunchManifest) -> tuple[str, ...]:
        manifest.revalidate()
        if platform.system() != "Linux" or manifest.host_os != "Linux":
            raise SafetyError("isolation_backend_unsupported")
        if manifest.provider != "isolation-probe":
            raise SafetyError("live_provider_backend_unavailable")
        if manifest.network.provider_hosts or manifest.credential_refs:
            raise SafetyError("offline_probe_boundary")
        remaining = manifest.deadline - time.time()
        if not 0 < remaining <= 300:
            raise SafetyError("invalid_probe_deadline")
        backend = self.backend_binary
        if not backend.is_absolute() or backend.is_symlink():
            raise SafetyError("invalid_backend_binary")
        if backend.lstat().st_mode & (stat.S_ISUID | stat.S_ISGID):
            raise SafetyError("privileged_backend_forbidden")
        if file_digest(backend) != manifest.backend_binary_digest:
            raise SafetyError("backend_digest_drift")
        image = Path(manifest.image.path)
        workspace = Path(manifest.workspace.path)
        if image == workspace or image in workspace.parents or workspace in image.parents:
            raise SafetyError("overlapping_operator_roots")
        if tree_digest(image) != manifest.image.tree_digest:
            raise SafetyError("image_digest_drift")
        if tree_digest(workspace) != manifest.workspace.tree_digest:
            raise SafetyError("workspace_digest_drift")
        if file_digest(image / "probe") != manifest.vendor_binary_digest:
            raise SafetyError("probe_interpreter_digest_drift")
        if file_digest(image / "probe") != manifest.runner_digest:
            raise SafetyError("probe_runner_digest_drift")
        if manifest.policy_digest != digest({"backend": manifest.backend, "network": "deny"}):
            raise SafetyError("probe_policy_drift")
        argv = [
            str(backend),
            "--unshare-all",
            "--unshare-user",
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
            "--ro-bind",
            str(image),
            "/",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--tmpfs",
            "/home",
            "--ro-bind",
            str(workspace),
            "/workspace",
        ]
        for relative in manifest.writable_files:
            file_digest(workspace / relative)
            argv.extend(("--bind", str(workspace / relative), "/workspace/" + relative))
        argv.extend(
            (
                "--clearenv",
                "--setenv",
                "HOME",
                "/home",
                "--setenv",
                "LANG",
                "C.UTF-8",
                "--chdir",
                "/workspace",
                "--",
                "/probe",
            )
        )
        return tuple(argv)

    def run(self, manifest: LaunchManifest, cancel: threading.Event) -> ProbeResult:
        argv = self.command(manifest)
        output = bytearray()
        truncated = threading.Event()
        # The operator must keep the image/workspace immutable between pin and launch.
        # No durable receipt claims success; independent adversarial evidence is required.
        remaining = manifest.deadline - time.time()
        if not 0 < remaining <= 300:
            raise SafetyError("invalid_probe_deadline")
        if cancel.is_set():
            raise SafetyError("probe_cancelled_before_launch")
        limit = time.monotonic() + remaining
        child = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={"LANG": "C.UTF-8"},
            cwd=manifest.image.path,
            start_new_session=True,
        )

        def drain():
            assert child.stdout is not None
            while chunk := child.stdout.read(4096):
                capacity = MAX_OUTPUT - len(output)
                output.extend(chunk[: max(0, capacity)])
                if len(chunk) > capacity:
                    truncated.set()

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        termination = "EXITED"
        while child.poll() is None:
            if cancel.wait(0.02) or time.monotonic() >= limit or truncated.is_set():
                termination = (
                    "CANCEL_REQUESTED"
                    if cancel.is_set()
                    else "OUTPUT_LIMIT"
                    if truncated.is_set()
                    else "DEADLINE"
                )
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                break
        try:
            returncode = child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            raise SafetyError("probe_termination_unverified") from None
        reader.join(timeout=3)
        if reader.is_alive():
            raise SafetyError("probe_descendant_pipe_unverified")
        child.stdout.close()
        return ProbeResult(
            manifest_digest=manifest.binding,
            status="UNVERIFIED" if returncode == 0 else "BLOCKED",
            returncode=returncode,
            output=redact(bytes(output).decode("utf-8", errors="replace")),
            output_truncated=truncated.is_set(),
            termination=termination,
        )
