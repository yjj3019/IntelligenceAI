"""Repo-local retrieval from the official pinned release; no vendor installation."""

import hashlib
import io
import os
import platform
import tarfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "8.30.1"
ROOT = Path(__file__).resolve().parents[1] / ".tools"
URL = f"https://github.com/gitleaks/gitleaks/releases/download/v{VERSION}/"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def main():
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("This helper supports official x64 assets only")
    name = f"gitleaks_{VERSION}_" + ("windows_x64.zip" if os.name == "nt" else "linux_x64.tar.gz")
    checksums = fetch(URL + f"gitleaks_{VERSION}_checksums.txt").decode()
    expected = next(line.split()[0] for line in checksums.splitlines() if line.split()[-1] == name)
    archive = fetch(URL + name)
    if hashlib.sha256(archive).hexdigest() != expected:
        raise SystemExit("Official release checksum mismatch")
    binary = "gitleaks.exe" if os.name == "nt" else "gitleaks"
    if os.name == "nt":
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            payload = zipped.read(binary)
    else:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            item = tar.getmember(binary)
            if not item.isfile():
                raise SystemExit("Binary member is not regular")
            payload = tar.extractfile(item).read()
    ROOT.mkdir(exist_ok=True)
    destination = ROOT / binary
    destination.write_bytes(payload)
    if os.name != "nt":
        destination.chmod(0o755)
    (ROOT / "gitleaks.sha256").write_text(expected + "  " + name + "\n")
    print(f"Official Gitleaks {VERSION} verified and installed in project .tools")


if __name__ == "__main__":
    main()
