"""Repeat only owned fixture races; no provider or external action is enabled."""

import argparse
import json
import os
import platform
import random
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from intelligenceai.security import redact

ROOT = Path(__file__).resolve().parents[1]
SEEDS = (17, 41, 83)
TESTS = (
    "tests/test_service_ownership.py",
    "tests/test_dag_gate_regressions.py::test_cancel_during_admission_duplicate_never_resurrects_writer",
    "tests/test_dag_gate_regressions.py::test_two_hosts_grants_and_active_controller_owner",
    "tests/test_dag.py::test_parallel_readers_receive_same_fixed_candidate",
    "tests/test_mcp_stdio.py::test_service_cancel_race_and_grants",
    "tests/test_recovery.py::test_single_writer_across_tasks",
    "tests/test_supervisor.py::test_posix_child_tree_termination",
    "tests/test_supervisor.py::test_exited_leader_with_surviving_group_is_unverified",
    "tests/test_supervisor.py::test_changed_birth_or_stale_generation_sends_no_signal",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", nargs="+", type=int, choices=SEEDS, default=list(SEEDS))
    args = parser.parse_args()
    if len(args.seeds) != len(set(args.seeds)):
        parser.error("duplicate seed refused")
    directory = ROOT / ".test-runs"
    directory.mkdir(exist_ok=True)
    if directory.is_symlink() or (hasattr(directory, "is_junction") and directory.is_junction()):
        raise SystemExit("linked simulation directory refused")
    directory = directory.resolve(strict=True)
    if not directory.is_relative_to(ROOT):
        raise SystemExit("simulation directory outside repository")
    report = {
        "schema": "owned-race-simulation-v1",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stdin=subprocess.DEVNULL
        ).strip(),
        "system": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "seed_controls": "test order and PYTHONHASHSEED; not OS scheduling",
        "live_provider_calls": 0,
        "external_actions": 0,
        "attempts": [],
    }
    for seed in args.seeds:
        selected = list(TESTS)
        random.Random(seed).shuffle(selected)
        attempt_dir = Path(tempfile.mkdtemp(prefix=f"simulation-{seed}-", dir=directory))
        junit = attempt_dir / "results.xml"
        base = attempt_dir / "pytest"
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-rs",
            *selected,
            f"--basetemp={base}",
            f"--junitxml={junit}",
        ]
        print(json.dumps({"simulation_seed": seed, "status": "STARTING"}), flush=True)
        start = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                env=os.environ | {"PYTHONHASHSEED": str(seed)},
                stdin=subprocess.DEVNULL,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=900,
                check=False,
                shell=False,
            )
            output = redact(completed.stdout + completed.stderr)
            exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            output, exit_code = "owned simulation driver timed out; attempt failed", 124
        suites = ET.parse(junit).getroot().findall("testsuite") if junit.exists() else []
        counts = {
            key: sum(int(s.get(key, "0")) for s in suites)
            for key in ("tests", "failures", "errors", "skipped")
        }
        skipped = [
            {"test": case.get("name"), "reason": redact(item.get("message", ""))}
            for suite in suites
            for case in suite.findall("testcase")
            for item in case.findall("skipped")
        ]
        passed = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
        valid = bool(suites) and exit_code == 0 and not counts["failures"] and not counts["errors"]
        attempt = {
            "seed": seed,
            "selected_tests_in_order": selected,
            "elapsed_seconds": round(time.monotonic() - start, 3),
            "exit_code": exit_code,
            "passed": passed,
            **counts,
            "skipped_reasons": skipped,
            "status": "PASS" if valid else "FAIL",
        }
        report["attempts"].append(attempt)
        print(output[-3000:], flush=True)
        print(json.dumps(attempt), flush=True)
        if not valid:
            break
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["status"] = (
        "PASS"
        if len(report["attempts"]) == len(args.seeds)
        and all(a["status"] == "PASS" for a in report["attempts"])
        else "FAIL"
    )
    report_path = directory / "simulation-report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"simulation_report": str(report_path), "status": report["status"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
