"""Test-owned executable; does not invoke the requested project command."""

import json
import sys

value = json.load(sys.stdin)
assert value["argv"] in [
    ["python", "-m", "pytest", "-q"],
    ["python", "-m", "build", "--no-isolation"],
]
assert value["enabled"] is False and value["env"] == {} and value["shell"] is False
print(json.dumps({"status": "PASS", "exit_code": 0, "source": "OWNED_FAKE_ONLY"}))
