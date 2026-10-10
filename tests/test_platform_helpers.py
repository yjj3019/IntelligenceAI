import importlib.util
import os
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "fetch_scanner", Path(__file__).parents[1] / "scripts/fetch_gitleaks.py"
)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


@pytest.mark.parametrize(
    "system,machine,suffix",
    [
        ("Darwin", "arm64", "darwin_arm64.tar.gz"),
        ("Darwin", "x86_64", "darwin_x64.tar.gz"),
        ("Windows", "AMD64", "windows_x64.zip"),
        ("Linux", "x86_64", "linux_x64.tar.gz"),
    ],
)
def test_strict_official_platform_asset(system, machine, suffix):
    assert helper.asset(system, machine)[0] == "gitleaks_8.30.1_" + suffix


def test_unknown_platform_never_falls_back_to_linux():
    for pair in [("Darwin", "mips"), ("Windows", "arm64"), ("Unknown", "x86_64")]:
        with pytest.raises(SystemExit):
            helper.asset(*pair)


@pytest.mark.parametrize("kind", ["hardlink", "symlink", "root_link"])
def test_scanner_install_refuses_links(tmp_path, kind):
    root = tmp_path / "tools"
    outside = tmp_path / "outside"
    if kind == "root_link":
        outside.mkdir()
        try:
            root.symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip("Native symlink privilege unavailable")
    else:
        root.mkdir()
        outside.write_bytes(b"preserved")
        target = root / "gitleaks"
        if kind == "hardlink":
            os.link(outside, target)
        else:
            try:
                target.symlink_to(outside)
            except OSError:
                pytest.skip("Native symlink privilege unavailable")
    with pytest.raises(ValueError):
        helper.atomic_install(root, "gitleaks", b"replacement")
    if kind == "root_link":
        assert not (outside / "gitleaks").exists()
    else:
        assert outside.read_bytes() == b"preserved"


def test_scanner_install_replaces_regular_inode(tmp_path):
    root = tmp_path / "tools"
    helper.atomic_install(root, "gitleaks", b"first")
    before = (root / "gitleaks").stat().st_ino
    helper.atomic_install(root, "gitleaks", b"second", executable=True)
    assert (root / "gitleaks").read_bytes() == b"second"
    assert (root / "gitleaks").stat().st_ino != before


@pytest.mark.parametrize("swap_after_reservation", [False, True])
def test_canonical_ancestor_alias_and_writer_lease(tmp_path, swap_after_reservation):
    from intelligenceai import fixture
    from intelligenceai.contracts import Task
    from intelligenceai.controller import fixture_plan
    from intelligenceai.ledger import Ledger
    from intelligenceai.security import SafetyError

    first, second = tmp_path / "real", tmp_path / "other"
    for path in (first, second):
        (path / "workspace").mkdir(parents=True)
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(first, target_is_directory=True)
    except OSError:
        pytest.skip("Native symlink privilege unavailable")
    target = alias / "workspace"
    ledger = Ledger(tmp_path / "lease.sqlite")
    try:
        ledger.create(
            Task(
                task_id="owned",
                redacted_request="owned",
                repo_identity="owned",
                base_sha="base",
                state="RUNNING",
            )
        )
        record = ledger.reserve("owned", fixture_plan().steps[0], 0, str(target))
        assert ledger.db.execute("SELECT workspace FROM writers").fetchone()[0] == str(
            target.resolve()
        )
        ledger.start(record["id"])
        if swap_after_reservation:
            alias.unlink()
            alias.symlink_to(second, target_is_directory=True)
            with pytest.raises(SafetyError, match="writer lease"):
                fixture.implement(
                    target, 0, "success", ledger=ledger, invocation_id=record["id"], generation=1
                )
            assert not (second / "workspace/answer.py").exists()
        else:
            fixture.implement(
                target, 0, "success", ledger=ledger, invocation_id=record["id"], generation=1
            )
            assert (first / "workspace/answer.py").read_text() == "ANSWER = 42\n"
    finally:
        ledger.close()
