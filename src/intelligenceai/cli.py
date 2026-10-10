import argparse
import getpass
import json
from pathlib import Path

from pydantic import ValidationError

from .contracts import Action, Plan
from .controller import Controller, fixture_plan
from .registry import registry
from .security import SafetyError, clean


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="IntelligenceAI local fixture controller")
    p.add_argument("--state-dir", type=Path, default=Path.cwd() / ".intelligenceai")
    sub = p.add_subparsers(dest="command", required=True)
    submit = sub.add_parser("submit")
    submit.add_argument("--repo", type=Path, required=True)
    submit.add_argument("--request", required=True)
    submit.add_argument("--plan", type=Path)
    submit.add_argument("--scenario", choices=["success", "repair", "exhaust"], default="success")
    submit.add_argument("--run", action="store_true")
    sub.add_parser("preview").add_argument("--plan", type=Path)
    sub.add_parser("capabilities")
    for name in ("status", "results", "run", "recover", "reject", "cancel"):
        sub.add_parser(name).add_argument("task_id")
    for name in ("approve", "dry-run"):
        command = sub.add_parser(name)
        command.add_argument("task_id")
        command.add_argument(
            "--action", choices=["publish", "push", "merge", "deploy"], required=True
        )
        command.add_argument("--destination", required=True)
        if name == "approve":
            command.add_argument("--ttl", type=int, default=900)
    return p


def load_plan(path: Path | None) -> Plan:
    return Plan.model_validate_json(path.read_text(encoding="utf-8")) if path else fixture_plan()


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    controller = None
    try:
        if args.command == "capabilities":
            output = registry()
        elif args.command == "preview":
            output = {
                "plan": load_plan(args.plan).model_dump(),
                "capabilities": registry(),
                "external_actions_enabled": False,
                "note": "Preview does not probe accounts or launch models",
            }
        else:
            controller = Controller(args.state_dir)
            if args.command == "submit":
                tid = controller.submit(
                    args.repo, args.request, load_plan(args.plan), args.scenario
                )
                output = controller.run(tid) if args.run else {"task_id": tid, "state": "READY"}
            elif args.command in {"run", "recover"}:
                output = controller.run(args.task_id)
            elif args.command in {"status", "results"}:
                output = controller.status(args.task_id)
            elif args.command in {"reject", "cancel"}:
                controller.reject(args.task_id)
                output = controller.status(args.task_id)
            else:
                action = Action(
                    kind=args.action,
                    destination=args.destination,
                    argv=[args.action, args.destination],
                )
                output = (
                    controller.approve(args.task_id, action, getpass.getuser(), args.ttl)
                    if args.command == "approve"
                    else controller.dry_run(args.task_id, action)
                )
        print(json.dumps(clean(output), ensure_ascii=False, indent=2))
        return 0
    except (SafetyError, ValidationError, OSError, ValueError):
        # Raw model text, secret-bearing paths or exception arguments are never printed.
        print(json.dumps({"error": "request blocked or invalid; inspect sanitized task status"}))
        return 2
    finally:
        if controller:
            controller.close()


if __name__ == "__main__":
    raise SystemExit(main())
