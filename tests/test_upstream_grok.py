"""Real pinned wrapper, fake vendor and test-only policy helper; no live evidence."""

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from intelligenceai.contracts import Step
from intelligenceai.protocols import prepare

UPSTREAM = Path(__file__).parent / "support/upstream/omnilane-0.53.0"
RUNNER_SHA = "120910ce341e9bbfebb33f64c7d6ac72e7578fcfe20642016a649f035f0b613b"


def prepared(tmp_path, mode="read_only"):
    return prepare(
        Step(
            step_id="review",
            role="review" if mode == "read_only" else "implement",
            mode=mode,
            executor="omnilane",
            provider="grok",
            model="test-model",
            effort="high",
            lane="hard-judgment",
            allowed_paths=["result.txt"],
        ),
        task_id="task",
        generation=1,
        invocation_id="synthetic-wrapper-test",
        request="Unpaid fake vendor contract only",
        cwd=tmp_path,
        candidate_digest="a" * 64,
    )


def test_retry_cap_is_fixed_contract_and_cannot_carry_authority(tmp_path, monkeypatch):
    invocation = prepared(tmp_path)
    assert invocation.env == {"OMNILANE_GROK_MAX_ATTEMPTS": "1"}
    for env in (
        {},
        {"OMNILANE_GROK_MAX_ATTEMPTS": "5"},
        {"OMNILANE_GROK_MAX_ATTEMPTS": "1", "OMNILANE_AA_OPERATOR_ASSERTED_HUMAN": "1"},
        {"OMNILANE_GROK_MAX_ATTEMPTS": "1", "OMNILANE_GROK_MACOS_WORK_UNCONFINED": "1"},
    ):
        with pytest.raises(ValidationError):
            type(invocation).model_validate(invocation.model_dump() | {"env": env})
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    with pytest.raises(ValidationError, match="unconfined"):
        prepared(tmp_path, "write")


def test_pinned_wrapper_bytes():
    assert hashlib.sha256((UPSTREAM / "run-grok.sh").read_bytes()).hexdigest() == RUNNER_SHA


@pytest.mark.parametrize("cap,expected_calls", [(None, 5), ("1", 1)])
def test_actual_upstream_empty_output_retry_count(tmp_path, cap, expected_calls):
    if os.name != "posix" or not shutil.which("bash"):
        pytest.skip("POSIX-only fake wrapper contract; no OS isolation evidence")
    scripts = tmp_path / "scripts"
    (scripts / "runners").mkdir(parents=True)
    (scripts / "lib").mkdir()
    runner = scripts / "runners/run-grok.sh"
    runner.write_bytes((UPSTREAM / "run-grok.sh").read_bytes())
    # Mock policy decisions only here: no human assertion, credential or context is
    # manufactured. This harness tests runner argv/retry, not upstream authorization.
    (scripts / "lib/common.sh").write_text(
        "strip_caller_claude_env() { :; }\n"
        "truncate_payload() { :; }\n"
        "aa_policy_gate() { :; }\n"
        'private_job_files() { for p in "$@"; do : > "$p"; done; }\n'
        'run_with_timeout() { shift; "$@"; }\n',
        encoding="utf-8",
    )
    fake = tmp_path / "fake-grok"
    calls = tmp_path / "calls.jsonl"
    fake.write_text(
        f"#!{sys.executable}\nimport json,sys\n"
        f"with open({str(calls)!r}, 'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n",
        encoding="utf-8",
    )
    fake.chmod(0o700)
    home = tmp_path / "home"
    home.mkdir()
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Synthetic prompt. No model request.")
    env = {"HOME": str(home), "TMPDIR": str(tmp_path), "PATH": os.defpath, "GROK_BIN": str(fake)}
    if cap is not None:
        env["OMNILANE_GROK_MAX_ATTEMPTS"] = cap
    result = subprocess.run(
        [
            shutil.which("bash"),
            str(runner),
            "advise",
            str(tmp_path),
            "test-model",
            "high",
            str(prompt),
            str(tmp_path / "answer"),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 1, result.stderr  # rc=0 empty vendor output stays failure.
    captured = [json.loads(line) for line in calls.read_text().splitlines()]
    assert len(captured) == expected_calls
    for argv in captured:
        assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
        assert argv[argv.index("--reasoning-effort") + 1] == "high"
        assert argv[argv.index("--prompt-file") + 1] == str(prompt)
        assert "--no-subagents" in argv and "--no-memory" in argv
        assert "--always-approve" not in argv and "--sandbox" not in argv
