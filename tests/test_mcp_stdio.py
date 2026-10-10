import asyncio
import json
import os
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import StubScanner
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import ValidationError

from intelligenceai.contracts import Check, Plan, Step
from intelligenceai.controller import Controller
from intelligenceai.security import SafetyError
from intelligenceai.service import ControllerService


def static_plan():
    first = Step(
        step_id="present",
        role="review",
        mode="read_only",
        executor="static",
        provider="local",
        model="static-v1",
        effort=None,
        allowed_paths=["user.txt"],
        checks=[Check(kind="file_exists", path="user.txt")],
    )
    return Plan(
        steps=[
            first,
            first.model_copy(
                update={
                    "step_id": "review",
                    "dependencies": ["present"],
                    "result_refs": ["present"],
                }
            ),
            first.model_copy(
                update={"step_id": "verify", "dependencies": ["review"], "result_refs": ["review"]}
            ),
        ]
    )


def parameters(root, repo):
    import sys

    env = {"PYTHONPATH": str(Path(__file__).parents[1] / "src"), "PATH": os.environ["PATH"]}
    if "SYSTEMROOT" in os.environ:
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "intelligenceai.mcp_stdio",
            "--state-dir",
            str(root),
            "--repo",
            "sample=" + str(repo),
        ],
        env=env,
    )


def decoded(result):
    assert not result.isError
    return result.structuredContent or json.loads(result.content[0].text)


def test_sdk_handshake_submit_status_result_reconnect_duplicate(repo, tmp_path):
    root = tmp_path / "mcp-state"
    args = {
        "repository": "sample",
        "request": "Three static steps",
        "plan": static_plan().model_dump(),
        "idempotency_key": "stable-admission",
    }

    async def run():
        async with stdio_client(parameters(root, repo)) as (read, write):
            async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=180)
            ) as client:
                initialization = await client.initialize()
                assert initialization.serverInfo.name == "IntelligenceAI-local"
                listing = await client.list_tools()
                assert {t.name for t in listing.tools} == {
                    "capabilities",
                    "preview",
                    "submit",
                    "status",
                    "results",
                    "cancel",
                }
                cap = decoded(await client.call_tool("capabilities", {}))
                assert not cap["live_dispatch_enabled"]
                for tool in ("approve", "reject", "publish", "merge", "deploy"):
                    assert (await client.call_tool(tool, {})).isError
                for injection in (
                    {"transport": "fake"},
                    {"principal": "operator"},
                    {"env": {"LIVE": "1"}},
                    {"state_dir": str(tmp_path)},
                    {"approval": True},
                ):
                    assert (await client.call_tool("submit", args | injection)).isError
                assert (
                    await client.call_tool("submit", args | {"repository": "ungranted"})
                ).isError
                admission = decoded(await client.call_tool("submit", args))
                tid = admission["task_id"]
                duplicate = decoded(await client.call_tool("submit", args))
                assert duplicate["task_id"] == tid and duplicate["duplicate"]
                assert (
                    await client.call_tool("submit", args | {"request": "conflicting duplicate"})
                ).isError
                deadline = time.monotonic() + 180
                while True:
                    status = decoded(await client.call_tool("status", {"task_id": tid}))
                    if status["state"] in {"READY_FOR_APPROVAL", "UNVERIFIED"}:
                        break
                    assert status["state"] not in {"FAILED", "BLOCKED", "NEEDS_RECONCILIATION"}
                    assert time.monotonic() < deadline
                    await asyncio.sleep(0.1)
                result = decoded(await client.call_tool("results", {"task_id": tid}))
                assert len(result["result"]["steps"]) == 3 and not result["invocations"]
        async with stdio_client(parameters(root, repo)) as (read, write):
            async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=180)
            ) as client:
                await client.initialize()
                again = decoded(await client.call_tool("submit", args))
                assert again["task_id"] == tid and again["duplicate"]
                restored = decoded(await client.call_tool("results", {"task_id": tid}))
                assert restored["result"] == result["result"]
                cancelled = decoded(await client.call_tool("cancel", {"task_id": tid}))
                assert cancelled["state"] == "CANCELLED" and cancelled["generation"] == 2
                repeated = decoded(await client.call_tool("cancel", {"task_id": tid}))
                assert repeated["generation"] == 2
        return tid

    tid = asyncio.run(run())
    ctl = Controller(root)
    try:
        assert ctl.ledger.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
        assert len(ctl.ledger.steps(tid)) == 3
    finally:
        ctl.close()


def test_service_cancel_race_and_grants(repo, tmp_path, monkeypatch):
    service = ControllerService(tmp_path / "service-state", {"sample": repo})
    # Pause only the trusted controller work function; no public fake transport switch exists.
    original = Controller.run
    entered, release = threading.Event(), threading.Event()

    def held(controller, tid):
        entered.set()
        assert release.wait(10)
        controller.scanner = StubScanner()
        return original(controller, tid)

    monkeypatch.setattr(Controller, "run", held)
    try:
        args = {
            "repository": "sample",
            "request": "Cancellation race",
            "idempotency_key": "race-key",
        }
        tid = service.call("submit", args)["task_id"]
        assert entered.wait(10)
        assert service.call("cancel", {"task_id": tid})["state"] == "CANCELLED"
        release.set()
        service.close()
        ctl = Controller(service.root)
        try:
            assert not ctl.status(tid)["invocations"] and ctl.status(tid)["state"] == "CANCELLED"
        finally:
            ctl.close()
        for tool in ("approve", "publish"):
            with pytest.raises(SafetyError):
                service.call(tool, {})
        with pytest.raises(ValidationError):
            service.call("status", {"task_id": tid, "credentials": "injected"})
    finally:
        release.set()
        service.close()


def test_actual_sdk_fake_pal_multistep(tmp_path):
    import sys

    from intelligenceai.protocols import pal_continue, prepare

    step = Step(
        step_id="review",
        role="review",
        mode="read_only",
        executor="pal",
        provider="openai",
        model="owned-test-model",
        effort=None,
        allowed_paths=["module.py"],
    )
    prepared = prepare(
        step,
        task_id="owned",
        generation=1,
        invocation_id="owned-review",
        request="Static review",
        cwd=tmp_path,
        candidate_digest="a" * 64,
    )

    async def run():
        parameters = StdioServerParameters(
            command=sys.executable, args=[str(Path(__file__).parent / "support/fake_pal_mcp.py")]
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                assert [t.name for t in (await client.list_tools()).tools] == ["codereview"]
                first = await client.call_tool("codereview", prepared.messages[0].arguments)
                second = pal_continue(
                    prepared, json.loads(first.content[0].text), "Owned static evidence"
                )
                result = await client.call_tool("codereview", second.messages[0].arguments)
                assert json.loads(result.content[0].text)["step_number"] == 2

    asyncio.run(run())
