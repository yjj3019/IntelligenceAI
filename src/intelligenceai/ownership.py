"""Local per-task process lease. A live controller is never crash recovery input."""

import os
import stat
from pathlib import Path

from .security import SafetyError, digest


class TaskLease:
    def __init__(self, root: Path, task_id: str):
        directory = root / "owners"
        directory.mkdir(exist_ok=True)
        info = directory.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or directory.is_symlink()
            or (hasattr(directory, "is_junction") and directory.is_junction())
        ):
            raise SafetyError("linked owner directory refused")
        path = directory / (digest(task_id) + ".lock")
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise SafetyError("linked owner lock refused")
        except FileNotFoundError:
            pass
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        self.stream = os.fdopen(os.open(path, flags, 0o600), "r+b", buffering=0)
        if os.fstat(self.stream.fileno()).st_size == 0:
            self.stream.write(b"0")
        self.stream.seek(0)
        self.acquired = False

    def __enter__(self):
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.acquired = True
        except (BlockingIOError, PermissionError):
            self.acquired = False
        except OSError as exc:
            self.stream.close()
            raise SafetyError("task execution owner cannot be verified") from exc
        return self

    def __exit__(self, *args):
        try:
            if self.acquired:
                if os.name == "nt":
                    import msvcrt

                    self.stream.seek(0)
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        finally:
            self.stream.close()
