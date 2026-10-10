"""Trusted fixed-fixture subprocess. No DB, vendor, shell or user repository access."""

import argparse
import json
import os
import subprocess
from pathlib import Path
from uuid import UUID

from intelligenceai.contracts import Budgets, Check, Evidence, Plan, Step
from intelligenceai.controller import Controller
from intelligenceai.security import canonical, clean, digest


def fixed_plan(profile):
    if profile not in {"python-review", "json-review"}:
        raise ValueError("unregistered fixture")
    name = "answer.py" if profile == "python-review" else "settings.json"
    fixture = "answer-v1" if profile == "python-review" else "json-config-v1"
    return Plan(
        budgets=Budgets(max_model_calls=1, max_repairs=0),
        steps=[
            Step(
                step_id="inspect",
                role="analyze",
                mode="read_only",
                executor="static",
                provider="local",
                model="static-v1",
                effort=None,
                allowed_paths=["baseline.json"],
                checks=[Check(kind="json_shape", path="baseline.json", required_keys=["fixture"])],
            ),
            Step(
                step_id="candidate",
                dependencies=["inspect"],
                result_refs=["inspect"],
                role="implement",
                mode="write",
                allowed_paths=[name],
                profile=fixture,
            ),
            Step(
                step_id="verify",
                dependencies=["candidate"],
                result_refs=["candidate"],
                role="review",
                mode="read_only",
                executor="static",
                provider="local",
                model="static-v1",
                effort=None,
                allowed_paths=[name],
                checks=[
                    Check(kind="python_ast", path=name, expected_literals={"ANSWER": 42})
                    if profile == "python-review"
                    else Check(
                        kind="json_shape",
                        path=name,
                        required_keys=["enabled", "version"],
                        expected_literals={"enabled": True, "version": 42},
                    )
                ],
            ),
        ],
    )


class StaticScopeScanner:
    def scan(self, payloads, candidate_id, profile):
        return Evidence(
            candidate_id=candidate_id,
            command_profile=profile,
            tool_version="web-static-scope-v1",
            environment="fixture-only",
            exit_code=None,
            status="UNVERIFIED",
            timestamp=0.0,
            redacted_log="Live scanner and OS containment NOTRUN",
        )


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(canonical(clean(value)))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def prepare(root, descriptor):
    root.mkdir(parents=True, exist_ok=True)
    source = root / "source"
    source.mkdir()
    (source / "baseline.json").write_bytes(b'{"fixture":true}\n')
    for arguments in [
        ["init", "--quiet"],
        ["add", "baseline.json"],
        [
            "-c",
            "user.name=IntelligenceAI fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "Owned synthetic baseline",
        ],
    ]:
        subprocess.run(
            ["git", "-C", str(source), *arguments],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
    ctl = Controller(root / "core", scanner=StaticScopeScanner())
    try:
        ctl.submit(
            source,
            descriptor["request"],
            fixed_plan(descriptor["profile"]),
            _task_id=descriptor["core_task_id"],
        )
        atomic_json(
            root / "prepared.json",
            {
                "mapping": descriptor,
                "plan_digest": digest(fixed_plan(descriptor["profile"]).model_dump()),
            },
        )
    finally:
        ctl.close()


def execute(root, descriptor):
    prepared = json.loads((root / "prepared.json").read_text(encoding="utf-8"))
    if prepared["mapping"] != descriptor:
        raise ValueError("mapping changed")
    ctl = Controller(root / "core", scanner=StaticScopeScanner())
    try:
        if (
            ctl.metadata(descriptor["core_task_id"])["plan"]
            != fixed_plan(descriptor["profile"]).model_dump()
        ):
            raise ValueError("plan changed")
        result = ctl.run(descriptor["core_task_id"])
        candidate = ctl.candidate(descriptor["core_task_id"])
        contents = {
            name: (Path(ctl.metadata(descriptor["core_task_id"])["workspace"]) / name)
            .read_bytes()
            .decode("utf-8")
            for name in candidate.changed_paths
        }
        atomic_json(
            root / "completed.json",
            {
                "mapping": descriptor,
                "result": result,
                "candidate": candidate.model_dump(),
                "contents": contents,
            },
        )
    finally:
        ctl.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["prepare", "execute"])
    parser.add_argument("root", type=Path)
    parser.add_argument("core_task_id")
    args = parser.parse_args()
    core_id = str(UUID(args.core_task_id))
    root = args.root.resolve(strict=True) / core_id
    descriptor = json.loads(input())
    if descriptor["core_task_id"] != core_id:
        raise ValueError("mapping mismatch")
    (prepare if args.phase == "prepare" else execute)(root, descriptor)


if __name__ == "__main__":
    main()
