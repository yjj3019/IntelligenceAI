"""Bounded static parsers over immutable candidate bytes. Never import target code."""

import ast
import json
import time

from .contracts import Check, Evidence, Finding
from .security import SafetyError, digest


def inspect(
    check: Check, payloads: dict[str, bytes], candidate_id: str
) -> tuple[Evidence, list[Finding]]:
    check = Check.model_validate(check.model_dump())
    if check.kind in {"test_command", "build_command"}:
        return Evidence(
            candidate_id=candidate_id,
            command_profile=check.kind,
            tool_version="disabled-os-contract",
            environment="static-only",
            exit_code=None,
            status="UNVERIFIED",
            redacted_log="Project code execution disabled until OS containment is verified",
            timestamp=time.time(),
        ), []
    data = payloads.get(check.path)
    passed = data is not None
    if data is not None and len(data) > 1024 * 1024:
        raise SafetyError("static checker input exceeds 1 MiB limit")
    try:
        if passed and check.kind == "json_shape":
            value = json.loads(data)
            passed = isinstance(value, dict) and set(check.required_keys) <= value.keys()
            passed = passed and all(
                k in value and type(value[k]) is type(v) and value[k] == v
                for k, v in check.expected_literals.items()
            )
        elif passed and check.kind == "python_ast":
            tree = ast.parse(data.decode("utf-8"))
            if sum(1 for _ in ast.walk(tree)) > 100000:
                raise SafetyError("AST node limit exceeded")
            symbols = {
                n.name
                for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            }
            literals = {}
            for node in tree.body:
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            literals[target.id] = node.value.value
                            symbols.add(target.id)
            passed = set(check.required_symbols) <= symbols and all(
                k in literals and type(literals[k]) is type(v) and literals[k] == v
                for k, v in check.expected_literals.items()
            )
    except (ValueError, SyntaxError, UnicodeError, RecursionError):
        passed = False
    status = "PASS" if passed else "FAIL"
    evidence = Evidence(
        candidate_id=candidate_id,
        command_profile="static-" + check.kind + "-v1",
        tool_version="intelligenceai-static-v1",
        environment="immutable-bytes",
        exit_code=0 if passed else 1,
        status=status,
        redacted_log="Static profile " + status,
        timestamp=time.time(),
    )
    findings = (
        []
        if passed
        else [
            Finding(
                finding_id=digest(check.model_dump()),
                candidate_id=candidate_id,
                source_invocation="local-static-checker",
                evidence="Reproduced static profile failure",
                reproduced=True,
                blocking=True,
            )
        ]
    )
    return evidence, findings


def command_contract(kind: str, cwd: str, timeout: int) -> dict:
    """Preparation only. Production inspect() never executes this contract."""
    commands = {
        "test_command": ["python", "-m", "pytest", "-q"],
        "build_command": ["python", "-m", "build", "--no-isolation"],
    }
    if kind not in commands or not 1 <= timeout <= 300:
        raise SafetyError("unregistered command profile")
    return {
        "argv": commands[kind],
        "cwd": cwd,
        "env": {},
        "timeout": timeout,
        "enabled": False,
        "shell": False,
    }
