"""Scan only tracked release files; never persist raw scanner reports."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from intelligenceai.scanner import TRUSTED_CONFIG, report_metadata

ROOT = Path(__file__).resolve().parents[1]


def main():
    binary = ROOT / ".tools" / ("gitleaks.exe" if os.name == "nt" else "gitleaks")
    proc = subprocess.run([str(binary), "version"], capture_output=True, check=True, timeout=5)
    if proc.stdout.decode().strip() != "8.30.1":
        raise SystemExit("Scanner version mismatch")
    tracked = (
        subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True, timeout=10
        )
        .stdout.decode()
        .split("\0")
    )
    names = [n for n in tracked if n]
    with tempfile.TemporaryDirectory(dir=ROOT / ".tools", prefix="release-scan-") as temp:
        directory = Path(temp)
        payload = directory / "payload"
        payload.mkdir()
        references = "".join(":" + name + "\n" for name in names).encode()
        blobs = subprocess.run(
            ["git", "-C", str(ROOT), "cat-file", "--batch"],
            input=references,
            capture_output=True,
            check=True,
            timeout=20,
        ).stdout
        cursor = 0
        for i, name in enumerate(names):
            boundary = blobs.index(b"\n", cursor)
            header = blobs[cursor:boundary].decode().split()
            if len(header) != 3 or header[1] != "blob":
                raise SystemExit("Release index blob missing")
            size = int(header[2])
            cursor = boundary + 1
            (payload / f"{i:06}.txt").write_bytes(blobs[cursor : cursor + size])
            cursor += size + 1
        config = directory / "trusted.toml"
        config.write_text(TRUSTED_CONFIG)
        ignore = directory / "empty.ignore"
        ignore.write_text("")
        report = directory / "report.json"
        result = subprocess.run(
            [
                str(binary),
                "dir",
                str(payload),
                "--config",
                str(config),
                "--gitleaks-ignore-path",
                str(ignore),
                "--ignore-gitleaks-allow",
                "--redact=100",
                "--report-format",
                "json",
                "--report-path",
                str(report),
                "--exit-code",
                "10",
                "--timeout",
                "30",
                "--no-banner",
                "--no-color",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=40,
            shell=False,
        )
        metadata = report_metadata(report.read_text())
        print(
            json.dumps(
                {
                    "scanner": "gitleaks-8.30.1",
                    "files": len(names),
                    "sanitized_finding_count": len(metadata),
                    "exit_code": result.returncode,
                }
            )
        )
        if result.returncode or metadata:
            raise SystemExit("Release scan blocked")


if __name__ == "__main__":
    main()
