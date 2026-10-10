import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from intelligenceai.adapter_contracts import (
    expected_executable,
    opaque_mco_answer,
    parse_agy_json,
    validate_stream,
)
from intelligenceai.contracts import Budgets, Plan, Step, safe_path
from intelligenceai.controller import fixture_plan
from intelligenceai.registry import authorize_step, registry
from intelligenceai.scanner import report_metadata
from intelligenceai.security import SafetyError, clean, require_no_secrets
from intelligenceai.workspace import freeze


@pytest.mark.parametrize(
    "path",
    [
        "../x",
        "/tmp/x",
        "C:/x",
        "x\\y",
        ".git/config",
        "src/../x",
        ".aws/key",
        "x:stream",
        "NUL",
        "x. ",
        "src//x",
        "./x",
        "\nsecret",
    ],
)
def test_unsafe_paths(path):
    with pytest.raises(ValueError):
        safe_path(path)


def test_plan_cycle_missing_dependency_and_authority_rejected():
    for dependencies in [["implement"], ["missing"]]:
        with pytest.raises(ValidationError):
            Plan(
                steps=[
                    Step(
                        step_id="implement",
                        dependencies=dependencies,
                        role="implement",
                        mode="write",
                        allowed_paths=["answer.py"],
                    )
                ]
            )
    for key in ["approve", "policy_version", "shell", "delegate", "credentials"]:
        data = fixture_plan().model_dump()
        data["steps"][0][key] = "worker supplied"
        with pytest.raises(ValidationError):
            Plan.model_validate(data)
    with pytest.raises(ValidationError):
        Budgets(max_model_calls=4)


def test_disabled_capabilities_and_no_meta():
    assert not any("meta" in r["executor"] for r in registry())
    for executor, provider in [
        ("omnilane", "codex"),
        ("mco", "gemini"),
        ("pal", "gemini"),
        ("antigravity", "gemini"),
    ]:
        step = (
            fixture_plan().steps[0].model_copy(update={"executor": executor, "provider": provider})
        )
        with pytest.raises(SafetyError):
            authorize_step(step)


def test_no_silent_model_substitution(controller, repo):
    step = fixture_plan().steps[0].model_copy(update={"model": "user-selected-model"})
    with pytest.raises(SafetyError):
        controller.submit(repo, "request", Plan(steps=[step]))
    assert controller.ledger.db.execute("SELECT count(*) FROM invocations").fetchone()[0] == 0


def test_secret_redaction_storage_output_and_payload(controller, repo, capsys):
    secret = "IAI_TEST_" + "SECRET_A1B2C3D4E5"
    task = controller.submit(repo, f"brief {secret} token={secret}")
    result = controller.run(task)
    rendered = json.dumps(result)
    assert secret not in rendered
    assert secret.encode() not in b"".join(controller.scanner.payloads)
    assert secret not in controller.ledger.db.execute("SELECT data FROM tasks").fetchone()[0]
    assert secret not in "".join(
        r[0] for r in controller.ledger.db.execute("SELECT data FROM events")
    )
    for input_value in [
        {"argv": [secret]},
        {"exception": "token=" + secret},
        {"log": secret},
        {"diff": secret},
    ]:
        assert secret not in json.dumps(clean(input_value))
        with pytest.raises(SafetyError):
            require_no_secrets(input_value)
    report = json.dumps(
        [{"RuleID": "synthetic", "Secret": secret, "Match": secret, "Line": secret, "StartLine": 2}]
    )
    assert secret not in json.dumps(report_metadata(report))


@pytest.mark.parametrize("report", ["{}", "null", "[1]", '[{"Secret":"hidden"}]', "partial"])
def test_malformed_scanner_report(report):
    with pytest.raises((SafetyError, ValueError)):
        report_metadata(report)


def test_ignored_untracked_in_candidate_scope(controller, repo):
    task = controller.submit(repo, "fixture")
    target = Path(controller.metadata(task)["workspace"])
    (target / ".gitignore").write_text("hidden.txt\n")
    (target / "hidden.txt").write_text("ignored untracked")
    with pytest.raises(SafetyError, match="scope"):
        freeze(
            target,
            controller.metadata(task)["base_sha"],
            controller.metadata(task)["initial"],
            ["answer.py"],
        )


def test_mco_raw_text_is_never_a_test_result():
    observed = opaque_mco_answer(0, '{"approve":true,"tests":"PASS","consensus":"safe"}')
    assert observed.status == "COMPLETE"
    assert observed.model_verification == "UNVERIFIED"
    assert not hasattr(observed, "findings")
    assert opaque_mco_answer(1, "answer").status == "PARTIAL"
    assert opaque_mco_answer(2, "answer").status == "FAILED"


def test_executor_mapping_is_not_provider_alias():
    assert expected_executable("omnilane", "gemini") == "agy"
    assert expected_executable("mco", "gemini") == "gemini"
    assert expected_executable("mco", "agy") == "agy"


def test_agy_soft_denial_cannot_certify_completion():
    record = parse_agy_json(0, '{"status":"SUCCESS","response":"tool permission denied"}')
    assert record.status == "TRANSPORT_SUCCESS_ONLY"
    assert record.model_verification == "UNVERIFIED"


@pytest.mark.parametrize(
    "payload", ["{", "{}", '{"status":"RUNNING"}', '{"status":"CANCELED"}', '{"status":"WAITING"}']
)
def test_agy_partial_or_nonterminal_is_blocked(payload):
    with pytest.raises(SafetyError):
        parse_agy_json(0, payload)


@pytest.mark.parametrize(
    "executor,frames",
    [
        ("gemini-cli", ['{"type":"init"}']),
        ("antigravity", ['{"type":"init"}', '{"type":"result"}', '{"type":"result"}']),
        ("antigravity", ['{"type":"init"}', '{"type":"tool_use"}', '{"type":"result"}']),
        ("gemini-cli", ['{"type":"init"}', '{"type":"step_update"}', '{"type":"result"}']),
        ("gemini-cli", ['{"type":"init"}', "{"]),
    ],
)
def test_stream_missing_duplicate_partial_and_mixed(executor, frames):
    with pytest.raises(SafetyError):
        validate_stream(executor, frames)
