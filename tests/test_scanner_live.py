import os
import shutil

import pytest

from intelligenceai.contracts import Action
from intelligenceai.controller import Controller
from intelligenceai.scanner import GitleaksScanner


@pytest.mark.skipif(
    os.name != "posix" or not shutil.which("gitleaks"),
    reason="Pinned Linux Gitleaks not installed; runtime gate stays UNVERIFIED",
)
def test_actual_gitleaks_clean_secret_and_ignore_directives():
    scanner = GitleaksScanner()
    assert scanner.scan([b"ANSWER = 42\n"], "candidate", "test").status == "PASS"
    secret = ("IAI_TEST_" + "SECRET_A1B2C3D4E5").encode()
    # Even inline suppressions and would-be ignored files cannot waive controller policy.
    evidence = scanner.scan(
        [secret + b" # gitleaks:allow\n", b".gitleaksignore", b"[allowlist]\npaths=['.*']"],
        "candidate",
        "test",
    )
    assert evidence.status == "FAIL"
    assert evidence.exit_code == 10
    assert secret.decode() not in evidence.model_dump_json()


def test_windows_scanner_remains_unverified():
    if os.name == "posix":
        pytest.skip("Windows runtime boundary")
    assert GitleaksScanner().scan([b"clean"], "candidate", "test").status == "UNVERIFIED"


@pytest.mark.skipif(
    os.name != "posix" or not shutil.which("gitleaks"),
    reason="Pinned Linux scanner required; no paid vendor calls",
)
def test_live_scanner_fixture_approval_still_dry_run(repo, tmp_path):
    controller = Controller(tmp_path / "live-scan-state")
    try:
        task = controller.submit(repo, "trusted local fixture")
        assert controller.run(task)["state"] == "READY_FOR_APPROVAL"
        action = Action(kind="push", destination="example.invalid/repo", argv=["push", "fixture"])
        controller.approve(task, action, "local-operator")
        assert controller.status(task)["state"] == "COMPLETED"
        assert controller.dry_run(task, action)["external_action_count"] == 0
    finally:
        controller.close()
