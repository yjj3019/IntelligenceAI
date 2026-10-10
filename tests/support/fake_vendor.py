"""Owned fake that parses the real CLI argv and stdin; it never launches a provider."""

import argparse
import json
import re
import sys
from pathlib import Path

JOB = "20261010-060000-123-1"
args = sys.argv[1:]
parser = argparse.ArgumentParser(allow_abbrev=False)
if args[:2] == ["omnilane", "route"]:
    parser.add_argument("--background", action="store_true", required=True)
    parser.add_argument("--single-shot", action="store_true", required=True)
    parser.add_argument("--executor", choices=["cli"], required=True)
    parser.add_argument("--mode", choices=["advise", "work"], required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--vendor", choices=["claude", "codex", "grok", "gemini"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=int, required=True)
    parser.add_argument("--job-timeout", type=int, required=True)
    parser.add_argument("--effort")
    parser.add_argument("lane", choices=["hard-judgment"])
    parser.add_argument("stdin_source", choices=["-"])
    value = parser.parse_args(args[2:])
    assert Path(value.workdir).resolve() == Path.cwd().resolve()
    assert re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}", value.model)
    assert 1 <= value.timeout == value.job_timeout <= 300
    efforts = {
        "claude": {"low", "medium", "high", "xhigh", "max"},
        "codex": {"low", "medium", "high", "xhigh", "max"},
        "grok": {None, "low", "high"},
        "gemini": {"low", "medium", "high"},
    }
    assert value.effort in efforts[value.vendor]
    assert sys.stdin.read() == "Review without executing code"
    print(JOB)
elif args[:2] == ["omnilane", "jobs"]:
    json_mode = args[2:3] == ["--json"]
    rest = args[3:] if json_mode else args[2:]
    assert len(rest) == 2
    operation, job_id = rest
    assert re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9]+-[0-9]+", job_id) and job_id == JOB
    assert operation in {"status", "result", "cancel"}
    assert not sys.stdin.read()
    if operation == "cancel":
        assert not json_mode
        print("cancel requested")
    elif json_mode:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "command": operation,
                    "ok": True,
                    "job": {
                        "id": JOB,
                        "state": "done",
                        "exit_code": 0,
                        "output_available": True,
                        "stderr_available": False,
                    },
                }
            )
        )
    else:
        assert operation == "result"
        print("Owned opaque answer")
elif args[:2] == ["mco", "review"]:
    for name in [
        "repo",
        "execution-mode",
        "enforcement-mode",
        "agent",
        "task-id",
        "file",
        "result-mode",
        "target-paths",
        "allow-paths",
    ]:
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--json", action="store_true", required=True)
    parser.add_argument("--invocation-hard-timeout", type=int, required=True)
    parser.add_argument("--review-hard-timeout", type=int, required=True)
    value = parser.parse_args(args[2:])
    assert Path(value.repo).resolve() == Path.cwd().resolve()
    assert value.execution_mode == "read_only" and value.enforcement_mode == "strict"
    assert value.file == "-" and value.result_mode == "both"
    assert value.target_paths == value.allow_paths == "module.py"
    assert value.invocation_hard_timeout == value.review_hard_timeout == 30
    alias, selector = value.agent.split("=", 1)
    provider, model = selector.split(":", 1)
    assert alias == "review" and provider in {"codex", "claude", "grok", "gemini", "agy"}
    assert re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}", model)
    assert sys.stdin.read() == "Review without executing code"
    print(
        json.dumps(
            {
                "status": "complete",
                "outputs": [
                    {
                        "invocation_id": alias,
                        "provider": provider,
                        "model": model,
                        "status": "success",
                        "output": "Owned opaque opinion",
                        "exit_code": 0,
                    }
                ],
            }
        )
    )
else:
    raise SystemExit("No owned argv contract for this command")
