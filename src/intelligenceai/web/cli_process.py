"""Bounded local process tree; preserves native auth without exporting credentials."""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from intelligenceai.web import cli_gate

MAX_OUTPUT = 65536
STANDARD_ENV = frozenset(
    "PATH PATHEXT SYSTEMROOT WINDIR COMSPEC TEMP TMP USERPROFILE HOMEDRIVE HOMEPATH "
    "HOME APPDATA LOCALAPPDATA PROGRAMDATA PROGRAMFILES PROGRAMFILES(X86) LANG LC_ALL".split()
)


def native_environment():
    # Do not even fetch discarded API key/helper/endpoint values. Preserve native HOME.
    return {name: os.environ[name] for name in STANDARD_ENV if name in os.environ}


class LocalProcess:
    def __init__(self, argv, cwd, prompt, *, before_start=lambda: None, mode="prompt"):
        self.buffers = [bytearray(), bytearray()]
        self.overflow = threading.Event()
        self.job = None
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            [sys.executable, "-I", "-S", str(Path(cli_gate.__file__).resolve())],
            cwd=cwd,
            env=native_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=flags,
            start_new_session=os.name != "nt",
        )
        self.threads = []
        try:
            if os.name == "nt":
                import win32api
                import win32con
                import win32job

                self.job = win32job.CreateJobObject(None, "")
                limits = win32job.QueryInformationJobObject(
                    self.job, win32job.JobObjectExtendedLimitInformation
                )
                limits["BasicLimitInformation"]["LimitFlags"] = (
                    win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                )
                win32job.SetInformationJobObject(
                    self.job, win32job.JobObjectExtendedLimitInformation, limits
                )
                handle = win32api.OpenProcess(
                    win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE,
                    False,
                    self.process.pid,
                )
                try:
                    win32job.AssignProcessToJobObject(self.job, handle)
                finally:
                    handle.Close()
            for index, stream in enumerate((self.process.stdout, self.process.stderr)):
                thread = threading.Thread(target=self._drain, args=(index, stream), daemon=True)
                thread.start()
                self.threads.append(thread)
            before_start()
            envelope = json.dumps(
                {"argv": argv, "cwd": str(cwd), "prompt": prompt, "mode": mode},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            if len(envelope) > 16383:
                raise ValueError("local_cli_input_too_large")
            self.process.stdin.write(envelope + b"\n")
            self.process.stdin.close()
        except BaseException:
            self.close()
            raise

    def _drain(self, index, stream):
        while chunk := stream.read(4096):
            remaining = MAX_OUTPUT - len(self.buffers[index])
            self.buffers[index].extend(chunk[:remaining])
            if len(chunk) > remaining:
                self.overflow.set()
        stream.close()

    def close(self):
        """Returns proof of local tree exit, never proof of remote model cancellation."""
        confirmed = False
        try:
            if self.job is not None:
                import win32job

                win32job.TerminateJobObject(self.job, 125)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    info = win32job.QueryInformationJobObject(
                        self.job, win32job.JobObjectBasicAccountingInformation
                    )
                    if info["ActiveProcesses"] == 0:
                        confirmed = True
                        break
                    time.sleep(0.02)
            elif os.name != "nt":
                # Owned, non-hostile process group. This is not an OS sandbox.
                from intelligenceai.supervisor import group_members

                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait(timeout=3)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if not group_members(self.process.pid):
                        confirmed = True
                        break
                    time.sleep(0.02)
            else:
                self.process.kill()
            self.process.wait(timeout=3)
            for thread in self.threads:
                thread.join(timeout=3)
            return confirmed and all(not thread.is_alive() for thread in self.threads)
        except (OSError, subprocess.TimeoutExpired):
            return False
        finally:
            if self.job is not None:
                self.job.Close()
                self.job = None

    def output(self):
        return tuple(bytes(value) for value in self.buffers)
