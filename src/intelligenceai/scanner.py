import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .contracts import Evidence
from .security import SafetyError, clean, redact
from .supervisor import Supervisor

PINNED_GITLEAKS = "8.30.1"
TRUSTED_CONFIG = (
    """title = "IntelligenceAI controller policy"
[extend]
useDefault = true
[[rules]]
id = "intelligenceai-test-secret"
description = "Synthetic regression token"
regex = """
    + "'''IAI_TEST_SECRET_[A-Z0-9]+'''\n"
)


def report_metadata(raw: str) -> list[dict]:
    data = json.loads(raw)
    if not isinstance(data, list):
        raise SafetyError("malformed scanner report")
    result = []
    for finding in data:
        if not isinstance(finding, dict) or not isinstance(finding.get("RuleID"), str):
            raise SafetyError("malformed scanner finding")
        # Never persist scanner Match/Secret/Line, stdout or stderr, even with --redact.
        result.append(clean({"rule": finding["RuleID"], "start_line": finding.get("StartLine")}))
    return result


class GitleaksScanner:
    def scan(self, payloads: list[bytes], candidate_id: str, profile: str) -> Evidence:
        status, code, log = "UNVERIFIED", None, "Gitleaks unavailable or OS supervision unverified"
        executable = shutil.which("gitleaks")
        if executable and os.name == "posix":
            try:
                with tempfile.TemporaryDirectory(prefix="iai-scan-") as directory:
                    root = Path(directory)
                    target = root / "payload"
                    target.mkdir()
                    for i, payload in enumerate(payloads):
                        (target / f"{i:06}.txt").write_bytes(payload)
                    config = root / "trusted.toml"
                    config.write_text(TRUSTED_CONFIG)
                    ignore = root / "empty.ignore"
                    ignore.write_text("")
                    report = root / "report.json"
                    # Pin version without executing any model/auth probes.
                    version = root / "version.txt"
                    with version.open("wb") as output:
                        proc = subprocess.run(
                            [executable, "version"],
                            stdout=output,
                            stderr=subprocess.DEVNULL,
                            timeout=5,
                            env={},
                        )
                    if proc.returncode or version.read_text().strip() != PINNED_GITLEAKS:
                        raise SafetyError("Gitleaks version mismatch")
                    supervisor = Supervisor()
                    supervisor.launch(
                        [
                            executable,
                            "dir",
                            str(target),
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
                            "20",
                            "--no-banner",
                            "--no-color",
                        ],
                        1,
                        root,
                    )
                    code, terminated = supervisor.wait(25)
                    if code is None or not terminated:
                        raise SafetyError("scanner timeout or process termination unknown")
                    metadata = report_metadata(report.read_text())
                    status = "PASS" if code == 0 and not metadata else "FAIL"
                    log = f"sanitized findings={len(metadata)}; process termination verified"
            except (SafetyError, OSError, ValueError, subprocess.SubprocessError):
                status, log = "UNVERIFIED", "scanner error; raw exception/report suppressed"
        return Evidence(
            candidate_id=candidate_id,
            command_profile=profile,
            tool_version="gitleaks-" + PINNED_GITLEAKS,
            environment="local",
            exit_code=code,
            status=status,
            redacted_log=redact(log),
            timestamp=time.time(),
            live=True,
        )
