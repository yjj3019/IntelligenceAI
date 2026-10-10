import errno
import os
import platform
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .security import SafetyError


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    generation: int
    start_token: str


def supervision_supported() -> bool:
    return os.name == "posix" and (
        platform.system() == "Darwin" or Path("/proc/self/stat").exists()
    )


def _psutil():
    try:
        import psutil

        return psutil
    except ImportError as exc:
        raise SafetyError("pinned Darwin process backend unavailable") from exc


def start_token(pid: int) -> str:
    """Fresh birth identity; no cached Process or PID-only authority."""
    if platform.system() == "Darwin":
        psutil = _psutil()
        try:
            process = psutil.Process(pid)
            birth = process.create_time()
            if not process.is_running():
                raise SafetyError("process identity no longer running")
            return f"darwin:{birth!r}"
        except (OSError, psutil.Error) as exc:
            raise SafetyError("process ownership cannot be verified") from exc
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
        return "linux:" + text[text.rindex(")") + 2 :].split()[19]
    except (OSError, IndexError, ValueError) as exc:
        raise SafetyError("process ownership cannot be verified") from exc


def group_members(pgid: int) -> set[int]:
    """Non-zombie members. Enumeration errors never prove an empty group."""
    if platform.system() == "Darwin":
        psutil = _psutil()
        try:
            members = set()
            for pid in psutil.pids():
                try:
                    if os.getpgid(pid) != pgid:
                        continue
                    process = psutil.Process(pid)
                    if process.status() not in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
                        members.add(pid)
                except (ProcessLookupError, psutil.NoSuchProcess):
                    continue
            return members
        except (OSError, psutil.Error) as exc:
            raise SafetyError("process group enumeration unverified") from exc
    members = set()
    try:
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                raw = (entry / "stat").read_text()
                fields = raw[raw.rindex(")") + 2 :].split()
                if int(fields[2]) == pgid and fields[0] != "Z":
                    members.add(int(entry.name))
            except OSError as exc:
                if exc.errno not in {errno.ENOENT, errno.ESRCH}:
                    raise
    except (OSError, ValueError, IndexError) as exc:
        raise SafetyError("process group enumeration unverified") from exc
    return members


class Supervisor:
    """Own fixed checker processes; ordinary process groups are not OS sandboxes."""

    def __init__(self):
        self.process = None
        self.identity = None

    def launch(
        self, argv: list[str], generation: int, cwd: Path, env: dict[str, str] | None = None
    ):
        if not supervision_supported():
            raise SafetyError("verified POSIX supervision required; disabled on Windows")
        if self.process:
            raise SafetyError("supervisor already owns a process")
        self.process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env or {},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            shell=False,
        )
        try:
            token = start_token(self.process.pid)
        except SafetyError:
            # Fast exit can precede identity reading. Clean up only our Popen child;
            # never signal a group without a birth identity.
            if self.process.poll() is not None and not group_members(self.process.pid):
                token = "exited-before-identity"
            else:
                if self.process.poll() is None:
                    self.process.kill()
                    self.process.wait(timeout=3)
                raise SafetyError("launch identity unverified; owned leader cleanup attempted")
        self.identity = ProcessIdentity(self.process.pid, generation, token)
        return self.identity

    def terminate(self, generation: int) -> bool:
        if not self.process or not self.identity or generation != self.identity.generation:
            raise SafetyError("process owner generation mismatch")
        pid = self.identity.pid
        try:
            if start_token(pid) != self.identity.start_token or os.getpgid(pid) != pid:
                raise SafetyError("process ownership mismatch")
        except (SafetyError, ProcessLookupError) as exc:
            # An exited leader with surviving members is uncertain; no recycled PID signals.
            if self.process.poll() is None or group_members(pid):
                raise SafetyError("process ownership or remaining group unverified") from exc
            return True
        except OSError as exc:
            raise SafetyError("process ownership unverified") from exc
        os.killpg(pid, signal.SIGKILL)
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            return False
        deadline = time.monotonic() + 3
        while group_members(pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        return not group_members(pid)

    def wait(self, timeout: float) -> tuple[int | None, bool]:
        if not self.process or not self.identity:
            raise SafetyError("no owned process identity")
        try:
            code = self.process.wait(timeout=timeout)
            return code, not group_members(self.identity.pid)
        except subprocess.TimeoutExpired:
            return None, self.terminate(self.identity.generation)
