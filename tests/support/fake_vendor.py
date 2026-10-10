"""Owned contract executable, never registered in application configuration."""

import json
import sys

request = json.load(sys.stdin)
operation = sys.argv[1]
assert request["env"] == {}
if operation == "submit":
    print("fixture-job")
elif operation == "cancel":
    print("cancel requested")
else:
    print(
        json.dumps(
            {
                "schema_version": 1,
                "command": operation,
                "ok": True,
                "job": {
                    "id": "fixture-job",
                    "state": "done",
                    "exit_code": 0,
                    "output_available": True,
                    "stderr_available": False,
                },
            }
        )
    )
