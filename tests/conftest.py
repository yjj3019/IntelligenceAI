import subprocess
import time

import pytest

from intelligenceai.contracts import Evidence
from intelligenceai.controller import Controller


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "target"
    path.mkdir()
    commands = [
        ["init", "-b", "main"],
        ["config", "user.name", "Fixture"],
        ["config", "user.email", "fixture@example.invalid"],
    ]
    for args in commands:
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)
    (path / "user.txt").write_text("preserve\n")
    subprocess.run(["git", "-C", str(path), "add", "user.txt"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "fixture"], check=True, capture_output=True
    )
    return path


class StubScanner:
    """Test injection only; CLI cannot select it. Never claimed as live Gitleaks."""

    def __init__(self, status="PASS", live=False):
        self.status, self.live = status, live
        self.payloads = []

    def scan(self, payloads, candidate_id, profile):
        self.payloads.extend(payloads)
        return Evidence(
            candidate_id=candidate_id,
            command_profile=profile,
            tool_version="gitleaks-8.30.1" if self.live else "TEST_STUB",
            environment="test",
            status=self.status,
            exit_code=0 if self.status == "PASS" else None,
            redacted_log="test injection",
            timestamp=time.time(),
            live=self.live,
        )


@pytest.fixture
def controller(tmp_path):
    ctl = Controller(tmp_path / "state", scanner=StubScanner())
    yield ctl
    ctl.close()


@pytest.fixture
def approval_controller(tmp_path):
    # Exercise gates with injected PASS evidence. This does not certify a live scanner.
    ctl = Controller(tmp_path / "state", scanner=StubScanner(live=True))
    yield ctl
    ctl.close()
