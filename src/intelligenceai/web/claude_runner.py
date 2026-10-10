"""Trusted Linux Claude relay worker. No HTTP route can launch this module."""

import base64
import hmac
import json
import os
import platform
import secrets
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from intelligenceai.isolation import file_digest, tree_digest
from intelligenceai.security import SafetyError, canonical, digest, require_no_secrets
from intelligenceai.web import cgroup_enter, claude_bridge
from intelligenceai.web.claude_broker import MAX_REQUEST, ClaudeBroker
from intelligenceai.web.claude_contracts import ClaudeProfile, claude_argv
from intelligenceai.web.live_authority import ReceiptVerifier
from intelligenceai.web.paid_store import PaidLedger


class DelegatedCgroup:
    """Only use an already delegated v2 subtree. Never enable controllers or edit ancestors."""

    def __init__(self, root, invocation_id, profile):
        root = Path(root)
        if (
            platform.system() != "Linux"
            or not root.is_absolute()
            or any(p.is_symlink() for p in (root, *root.parents))
        ):
            raise SafetyError("delegated_cgroup_required")
        # Check the actual cgroup2 mount type; a fixture directory cannot prove enforcement.
        mounts = Path("/proc/self/mountinfo").read_text().splitlines()
        if not any(
            " - cgroup2 " in line
            and (root == Path(line.split()[4]) or Path(line.split()[4]) in root.parents)
            for line in mounts
        ):
            raise SafetyError("cgroup2_mount_required")
        if not {"cpu", "memory", "pids"} <= set(
            (root / "cgroup.subtree_control").read_text().split()
        ):
            raise SafetyError("cgroup_controllers_not_delegated")
        self.path = root / ("iai-" + invocation_id)
        self.path.mkdir(mode=0o700)
        try:
            for name, value in {
                "memory.max": str(profile.memory_bytes),
                "memory.swap.max": "0",
                "pids.max": str(profile.pids),
                "cpu.max": f"{profile.cpu_quota_us} 100000",
                "memory.oom.group": "1",
            }.items():
                (self.path / name).write_text(value)
                if (self.path / name).read_text().strip() != value:
                    raise SafetyError("cgroup_limit_not_applied")
            if not (self.path / "cgroup.kill").exists():
                raise SafetyError("cgroup_atomic_kill_required")
        except Exception:
            self.path.rmdir()
            raise

    def attach(self, pid):
        (self.path / "cgroup.procs").write_text(str(pid))
        if str(pid) not in (self.path / "cgroup.procs").read_text().split():
            raise SafetyError("cgroup_attachment_unverified")

    def kill_and_verify(self):
        (self.path / "cgroup.kill").write_text("1")
        limit = time.monotonic() + 3
        while time.monotonic() < limit:
            events = dict(
                line.split() for line in (self.path / "cgroup.events").read_text().splitlines()
            )
            if events.get("populated") == "0":
                self.path.rmdir()
                return True
            time.sleep(0.02)
        return False


class UnixRelay:
    def __init__(self, directory, broker, capability):
        self.broker, self.capability = broker, capability
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.bind(str(directory / "broker.sock"))
        os.chmod(directory / "broker.sock", 0o600)
        self.socket.listen(4)
        self.socket.settimeout(0.2)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)

    def serve(self):
        while not self.stop.is_set():
            try:
                connection, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(self.broker.profile.duration_seconds)
                try:
                    if hasattr(socket, "SO_PEERCRED"):
                        _, uid, _ = struct.unpack(
                            "3i",
                            connection.getsockopt(
                                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
                            ),
                        )
                        if uid != os.getuid():
                            raise SafetyError("relay_peer_denied")
                    size = struct.unpack("!I", claude_bridge.receive(connection, 4))[0]
                    if not 0 < size <= MAX_REQUEST * 2:
                        raise SafetyError("relay_frame_limit")
                    value = json.loads(claude_bridge.receive(connection, size))
                    if set(value) != {"capability", "body"} or not hmac.compare_digest(
                        value["capability"], self.capability
                    ):
                        raise SafetyError("relay_capability_denied")
                    body = base64.b64decode(value["body"], validate=True)
                    response = self.broker.exchange(body)
                    connection.sendall(struct.pack("!I", len(response)) + response)
                except Exception:
                    # No attacker payload, key, upstream body or error is persisted/logged.
                    continue

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        # Finish observing in-flight remote usage even if the local child was cancelled.
        self.stop.set()
        self.thread.join(timeout=self.broker.profile.duration_seconds + 16)
        self.socket.close()
        if self.thread.is_alive():
            raise SafetyError("relay_drain_unverified")


class ClaudeReviewRunner:
    def __init__(
        self,
        db,
        backend: Path,
        delegated_root: Path,
        runtime_root: Path,
        verifier: ReceiptVerifier,
        credential,
    ):
        if db.dialect.name != "postgresql":
            raise SafetyError("paid_runtime_requires_postgresql")
        self.ledger, self.backend = PaidLedger(db), backend
        self.delegated_root, self.runtime_root = delegated_root, runtime_root
        self.verifier, self.credential = verifier, credential

    def command(self, manifest, profile, relay_root):
        manifest = manifest.revalidate()
        profile = ClaudeProfile.model_validate(profile.model_dump())
        if (
            platform.system() != "Linux"
            or manifest.backend != "linux-bwrap-claude-relay-v1"
            or (
                manifest.provider != "claude"
                or manifest.mode != "read_only"
                or manifest.host_os != "Linux"
                or manifest.writable_files
                or manifest.model != profile.model
                or manifest.effort != profile.effort
                or manifest.network.provider_hosts != ("api.anthropic.com",)
                or manifest.budget.max_invocations != 1
                or manifest.budget.max_cost_microusd < profile.reservation
                or manifest.vendor_binary_digest != profile.cli_digest
                or manifest.backend_binary_digest != profile.backend_digest
                or manifest.image != profile.image
                or manifest.policy_digest != profile.policy_digest
            )
        ):
            raise SafetyError("claude_live_profile_mismatch")
        if (
            not self.backend.is_absolute()
            or self.backend.is_symlink()
            or (
                self.backend.lstat().st_mode & (stat.S_ISUID | stat.S_ISGID)
                or file_digest(self.backend) != profile.backend_digest
            )
        ):
            raise SafetyError("claude_backend_drift")
        image = Path(profile.image.path)
        if tree_digest(image) != profile.image.tree_digest or (
            file_digest(image / "claude") != profile.cli_digest
            or file_digest(image / "bridge.py") != profile.bridge_digest
            or file_digest(Path(claude_bridge.__file__)) != profile.bridge_digest
            or file_digest(Path(cgroup_enter.__file__)) != manifest.runner_digest
        ):
            raise SafetyError("claude_image_or_runner_drift")
        if any(not (image / name).is_dir() for name in ("proc", "dev", "tmp", "home", "relay")):
            raise SafetyError("claude_image_mount_points_required")
        # Candidate bytes are carried as the approved stdin prompt. No repository or
        # writable project mount is exposed to the CLI at all.
        return (
            str(self.backend),
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
            str(relay_root),
            "/relay",
            "--clearenv",
            "--setenv",
            "HOME",
            "/home",
            "--setenv",
            "PYTHONHOME",
            "/usr",
            "--chdir",
            "/home",
            "--",
            "/python",
            "/bridge.py",
        )

    def run(self, manifest, profile, intent, tokens, prompt, *, session_hash, approved_by, cancel):
        profile = ClaudeProfile.model_validate(profile.model_dump())
        if digest(prompt) != intent.prompt_digest or len(prompt.encode()) > 128 * 1024:
            raise SafetyError("paid_prompt_binding_changed")
        if prompt != self.ledger.review_prompt(intent):
            raise SafetyError("paid_candidate_prompt_changed")
        require_no_secrets(prompt)
        if intent.approval.manifest_digest != manifest.binding or (
            manifest.overlay_digest
            != digest(
                {
                    "profile": profile.binding,
                    "prompt": intent.prompt_digest,
                    "budget": intent.budget_microusd,
                    "approved_by": intent.approved_by,
                }
            )
        ):
            raise SafetyError("paid_manifest_overlay_changed")
        checked = self.verifier.verify(manifest, intent.approval, tokens, now=time.time())
        self.ledger.reserve(
            intent,
            profile,
            session_hash=session_hash,
            approved_by=approved_by,
            receipt_digest=checked.receipt_set_digest,
        )
        # Reserve before touching the runtime. A launch-intent crash never replays.
        self.ledger.claim_launch(intent)
        group = child = None
        gate_read = gate_write = None
        cleanup = completed_local = False
        try:
            if cancel.is_set():
                raise SafetyError("paid_cancelled_before_launch")
            self.runtime_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self.runtime_root.is_symlink() or self.runtime_root.stat().st_mode & 0o077:
                raise SafetyError("private_runtime_root_required")
            with tempfile.TemporaryDirectory(prefix="relay-", dir=self.runtime_root) as temporary:
                relay_root = Path(temporary)
                argv = self.command(manifest, profile, relay_root)
                group = DelegatedCgroup(self.delegated_root, intent.invocation_id, profile)
                capability = secrets.token_urlsafe(32)

                def authorize_request():
                    if cancel.is_set():
                        raise SafetyError("paid_cancelled_before_http")
                    self.verifier.verify(manifest, intent.approval, tokens, now=time.time())

                broker = ClaudeBroker(
                    self.ledger,
                    intent,
                    profile,
                    self.credential,
                    prompt,
                    check_authority=authorize_request,
                )
                with UnixRelay(relay_root, broker, capability):
                    self.verifier.verify(manifest, intent.approval, tokens, now=time.time())
                    if cancel.is_set():
                        raise SafetyError("paid_cancelled_before_launch")
                    gate_read, gate_write = os.pipe()
                    child = subprocess.Popen(
                        [
                            sys.executable,
                            "-I",
                            "-S",
                            str(Path(cgroup_enter.__file__)),
                            str(gate_read),
                            *argv,
                        ],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        env={"LANG": "C.UTF-8"},
                        pass_fds=(gate_read,),
                        start_new_session=True,
                    )
                    group.attach(child.pid)
                    os.close(gate_read)
                    gate_read = None
                    # Authorization will be checked again by ledger.admit immediately
                    # before the broker's first upstream request.
                    self.verifier.verify(manifest, intent.approval, tokens, now=time.time())
                    os.write(gate_write, b"1")
                    os.close(gate_write)
                    gate_write = None
                    descriptor = canonical(
                        {
                            "argv": claude_argv(profile),
                            "prompt": prompt,
                            "capability": capability,
                            "seconds": profile.duration_seconds,
                        }
                    ).encode()
                    exceeded = threading.Event()
                    output = bytearray()

                    def drain():
                        while chunk := child.stdout.read(4096):
                            if len(output) + len(chunk) > 65536:
                                exceeded.set()
                            output.extend(chunk[: max(0, 65536 - len(output))])

                    reader = threading.Thread(target=drain, daemon=True)
                    reader.start()

                    def feed():
                        try:
                            child.stdin.write(descriptor)
                        except (OSError, ValueError):
                            pass
                        finally:
                            child.stdin.close()

                    writer = threading.Thread(target=feed, daemon=True)
                    writer.start()
                    deadline = min(
                        time.monotonic() + profile.duration_seconds,
                        time.monotonic() + intent.approval.expires_at - time.time(),
                    )
                    next_authority_check = 0.0
                    while child.poll() is None:
                        if time.monotonic() >= next_authority_check:
                            if not self.ledger.active(intent):
                                cancel.set()
                            next_authority_check = time.monotonic() + 0.25
                        if cancel.wait(0.02) or time.monotonic() >= deadline or exceeded.is_set():
                            break
                    cleanup = group.kill_and_verify()
                    group = None
                    returncode = child.wait(timeout=3)
                    reader.join(timeout=3)
                    writer.join(timeout=3)
                    child.stdout.close()
                    if not cleanup or reader.is_alive() or writer.is_alive():
                        raise SafetyError("paid_descendant_cleanup_unverified")
                self.ledger.runtime_ended(intent, cleanup_verified=cleanup)
                completed_local = True
                if cancel.is_set() or returncode != 0 or exceeded.is_set() or broker.result is None:
                    raise SafetyError("paid_review_not_importable")
                self.ledger.import_review(intent, broker.result, cleanup_verified=cleanup)
                return {
                    "state": "IMPORTED",
                    "invocation_id": intent.invocation_id,
                    "cleanup": "VERIFIED_CGROUP_EMPTY",
                    "scope": "LIVE_PROVIDER",
                }
        finally:
            for descriptor in (gate_read, gate_write):
                if descriptor is not None:
                    os.close(descriptor)
            if group is not None:
                try:
                    cleanup = group.kill_and_verify()
                finally:
                    if child is not None and child.poll() is None:
                        child.kill()
                        child.wait(timeout=3)
            if child is not None and child.poll() is None:
                # Even an attachment failure must terminate the trusted waiting launcher.
                child.kill()
                child.wait(timeout=3)
            if child is None:
                cleanup = True  # No gated process or provider relay capability was launched.
            if cleanup and not completed_local:
                self.ledger.runtime_ended(intent, cleanup_verified=True)
            self.ledger.uncertain(intent.invocation_id)
