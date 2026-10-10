import os
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


def start_token(pid: int) -> str:
    # Linux /proc starttime protects against a recycled PID. Native Windows is fail closed.
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
        return text[text.rindex(")") + 2 :].split()[19]
    except (OSError, IndexError, ValueError) as exc:
        raise SafetyError("process ownership cannot be verified") from exc


def group_members(pgid: int) -> set[int]:
    members = set()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text()
            fields = raw[raw.rindex(")") + 2 :].split()
            if int(fields[2]) == pgid and fields[0] != "Z":
                members.add(int(entry.name))
        except (OSError, ValueError, IndexError):
            continue
    return members


class Supervisor:
    """Controller-owned fixed checker profiles only. This is not an OS sandbox."""

    def __init__(self):
        self.process = None
        self.identity = None

    def launch(
        self, argv: list[str], generation: int, cwd: Path, env: dict[str, str] | None = None
    ):
        if os.name != "posix" or not Path("/proc/self/stat").exists():
            raise SafetyError("verified Linux process supervision required; disabled on Windows")
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
        self.identity = ProcessIdentity(self.process.pid, generation, start_token(self.process.pid))
        return self.identity

    def terminate(self, generation: int) -> bool:
        if not self.process or not self.identity or generation != self.identity.generation:
            raise SafetyError("process owner generation mismatch")
        pid = self.identity.pid
        try:
            if start_token(pid) != self.identity.start_token or os.getpgid(pid) != pid:
                raise SafetyError("process ownership mismatch")
        except SafetyError:
            # If leader has already exited, only a verified empty owned group is safe.
            if self.process.poll() is None or group_members(pid):
                raise
            return True
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
        try:
            code = self.process.wait(timeout=timeout)
            return code, not group_members(self.identity.pid)
        except subprocess.TimeoutExpired:
            return None, self.terminate(self.identity.generation)
