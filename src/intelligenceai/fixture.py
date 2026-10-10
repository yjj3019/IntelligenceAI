import ast
import os
import stat
import tempfile
import time
from pathlib import Path

from .contracts import Evidence, Finding
from .ledger import Ledger
from .security import SafetyError

FIXTURE_FILE = "answer.py"


def profile_path(profile: str) -> str:
    paths = {"answer-v1": FIXTURE_FILE, "json-config-v1": "settings.json"}
    if profile not in paths:
        raise SafetyError("unregistered fixture profile")
    return paths[profile]


def implement(
    workspace: Path,
    round_number: int,
    scenario: str,
    *,
    ledger: Ledger,
    invocation_id: str,
    generation: int,
    profile: str = "answer-v1",
) -> dict:
    # Only trusted constant bytes. Requests and worker text are never commands or code.
    if workspace.is_symlink() or (hasattr(workspace, "is_junction") and workspace.is_junction()):
        raise SafetyError("fixture workspace is linked")
    # The writer lease stores canonical roots, including macOS /var -> /private/var.
    workspace = workspace.resolve(strict=True)
    name = profile_path(profile)
    path = workspace / name
    value = (
        41
        if scenario in {"repair", "exhaust"} and (round_number == 0 or scenario == "exhaust")
        else 42
    )
    with ledger.write_guard(invocation_id, generation, str(workspace)):
        try:
            existing = path.lstat()
        except FileNotFoundError:
            existing = None
        if existing and (not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1):
            raise SafetyError("linked or nonregular fixture target refused before writing")
        descriptor, temporary = tempfile.mkstemp(prefix=".iai-write-", dir=workspace)
        try:
            with os.fdopen(descriptor, "wb") as output:
                payload = (
                    f"ANSWER = {value}\n"
                    if profile == "answer-v1"
                    else '{"enabled":true,"version":' + str(value) + "}\n"
                )
                output.write(payload.encode())
                output.flush()
                os.fsync(output.fileno())
            # Replace the directory entry with a fresh inode; never follow/open its target.
            # Concurrent entry replacement cannot redirect writes to an external inode.
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return {
        "status": "SUCCEEDED",
        "native_job_id": None,
        "provider": "fixture",
        "model": "deterministic-v1",
        "model_verification": "FIXTURE_ONLY",
        "artifact": name,
    }


def evaluate(workspace: Path, profile: str = "answer-v1") -> bool:
    """Real deterministic fixture assertion. Never import/execute target code."""
    try:
        if profile == "json-config-v1":
            import json

            value = json.loads((workspace / profile_path(profile)).read_text())
            return (
                type(value) is dict
                and set(value) == {"enabled", "version"}
                and value["enabled"] is True
                and type(value["version"]) is int
                and value["version"] == 42
            )
        node = ast.parse((workspace / FIXTURE_FILE).read_text())
        return (
            len(node.body) == 1
            and isinstance(node.body[0], ast.Assign)
            and len(node.body[0].targets) == 1
            and isinstance(node.body[0].targets[0], ast.Name)
            and node.body[0].targets[0].id == "ANSWER"
            and isinstance(node.body[0].value, ast.Constant)
            and node.body[0].value.value == 42
        )
    except (OSError, SyntaxError, ValueError):
        return False


def verify(workspace: Path, candidate_id: str, profile: str = "answer-v1") -> Evidence:
    passed = evaluate(workspace, profile)
    return Evidence(
        candidate_id=candidate_id,
        command_profile="fixture-assertion-v1"
        if profile == "answer-v1"
        else "fixture-json-config-v1",
        tool_version="intelligenceai-fixture-v1",
        environment="local",
        exit_code=0 if passed else 1,
        status="PASS" if passed else "FAIL",
        redacted_log=("AST ANSWER == 42 " if profile == "answer-v1" else "JSON config schema ")
        + ("passed" if passed else "failed"),
        timestamp=time.time(),
    )


def review(workspace: Path, candidate_id: str, profile: str = "answer-v1") -> list[Finding]:
    # Independent fixture review consumes candidate bytes, not the implementer's conclusion.
    if evaluate(workspace, profile):
        return []
    return [
        Finding(
            finding_id="fixture-answer-value" if profile == "answer-v1" else "fixture-json-value",
            candidate_id=candidate_id,
            source_invocation="fixture-review-v1",
            evidence="ANSWER assertion reproduced",
            reproduced=True,
            blocking=True,
        )
    ]
