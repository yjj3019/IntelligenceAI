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


def implement(
    workspace: Path,
    round_number: int,
    scenario: str,
    *,
    ledger: Ledger,
    invocation_id: str,
    generation: int,
) -> dict:
    # Only trusted constant bytes. Requests and worker text are never commands or code.
    path = workspace / FIXTURE_FILE
    value = (
        41
        if scenario in {"repair", "exhaust"} and (round_number == 0 or scenario == "exhaust")
        else 42
    )
    with ledger.write_guard(invocation_id, generation, str(workspace)):
        if workspace.resolve(strict=True) != workspace.absolute():
            raise SafetyError("fixture workspace is linked")
        try:
            existing = path.lstat()
        except FileNotFoundError:
            existing = None
        if existing and (not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1):
            raise SafetyError("linked or nonregular fixture target refused before writing")
        descriptor, temporary = tempfile.mkstemp(prefix=".iai-write-", dir=workspace)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(f"ANSWER = {value}\n".encode())
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
        "artifact": FIXTURE_FILE,
    }


def evaluate(workspace: Path) -> bool:
    """Real deterministic fixture assertion. Never import/execute target code."""
    try:
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
    except (OSError, SyntaxError):
        return False


def verify(workspace: Path, candidate_id: str) -> Evidence:
    passed = evaluate(workspace)
    return Evidence(
        candidate_id=candidate_id,
        command_profile="fixture-assertion-v1",
        tool_version="intelligenceai-fixture-v1",
        environment="local",
        exit_code=0 if passed else 1,
        status="PASS" if passed else "FAIL",
        redacted_log="AST assertion ANSWER == 42 " + ("passed" if passed else "failed"),
        timestamp=time.time(),
    )


def review(workspace: Path, candidate_id: str) -> list[Finding]:
    # Independent fixture review consumes candidate bytes, not the implementer's conclusion.
    if evaluate(workspace):
        return []
    return [
        Finding(
            finding_id="fixture-answer-value",
            candidate_id=candidate_id,
            source_invocation="fixture-review-v1",
            evidence="ANSWER assertion reproduced",
            reproduced=True,
            blocking=True,
        )
    ]
