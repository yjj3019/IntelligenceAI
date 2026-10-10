"""Retrieve a pinned official scanner into this repository, never a global installation."""

import hashlib
import io
import os
import platform
import stat
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "8.30.1"
ROOT = Path(__file__).resolve().parents[1] / ".tools"
URL = f"https://github.com/gitleaks/gitleaks/releases/download/v{VERSION}/"
DARWIN_HASHES = {
    "arm64": "b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5",
    "x64": "dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709",
}


def asset(system: str, machine: str) -> tuple[str, str]:
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(
        machine.lower()
    )
    if system == "Darwin" and arch in DARWIN_HASHES:
        return f"gitleaks_{VERSION}_darwin_{arch}.tar.gz", "gitleaks"
    if system in {"Linux", "Windows"} and arch == "x64":
        suffix = "windows_x64.zip" if system == "Windows" else "linux_x64.tar.gz"
        return f"gitleaks_{VERSION}_{suffix}", "gitleaks.exe" if system == "Windows" else "gitleaks"
    raise SystemExit("No verified asset mapping for this operating system/architecture")


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def linked(info):
    return stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400


def atomic_install(root: Path, name: str, payload: bytes, executable: bool = False):
    root.mkdir(exist_ok=True)
    info = root.lstat()
    if linked(info) or not stat.S_ISDIR(info.st_mode):
        raise ValueError("linked/non-directory scanner root refused")
    destination = root / name
    try:
        info = destination.lstat()
    except FileNotFoundError:
        pass
    else:
        if linked(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("linked/nonregular scanner destination refused")
    fd, temporary = tempfile.mkstemp(prefix=".install-", dir=root)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            if executable and os.name == "posix":
                os.fchmod(stream.fileno(), 0o755)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    system, machine = platform.system(), platform.machine()
    name, binary = asset(system, machine)
    checksums = fetch(URL + f"gitleaks_{VERSION}_checksums.txt").decode()
    expected = next(line.split()[0] for line in checksums.splitlines() if line.split()[-1] == name)
    if system == "Darwin":
        arch = "arm64" if machine.lower() in {"arm64", "aarch64"} else "x64"
        if expected != DARWIN_HASHES[arch]:
            raise SystemExit("Pinned Darwin checksum differs from official release manifest")
    archive = fetch(URL + name)
    if hashlib.sha256(archive).hexdigest() != expected:
        raise SystemExit("Official release checksum mismatch")
    if system == "Windows":
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            payload = zipped.read(binary)
    else:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            item = tar.getmember(binary)
            if not item.isfile():
                raise SystemExit("Binary member is not regular")
            payload = tar.extractfile(item).read()
    atomic_install(ROOT, binary, payload, executable=True)
    atomic_install(ROOT, "gitleaks.sha256", (expected + "  " + name + "\n").encode())
    print(f"Official Gitleaks {VERSION} verified: {system}/{machine} {name}")


if __name__ == "__main__":
    main()
