"""Fixed synthetic CLI. This executable never accesses a provider/account/network."""

import json
import subprocess
import sys
import time
from pathlib import Path

provider, mode = sys.argv[1:3]
payload = sys.stdin.read()
Path("input-capture.json").write_text(
    json.dumps({"argv": sys.argv[1:], "stdin": payload}, ensure_ascii=False), encoding="utf-8"
)
if mode == "descendant":
    subprocess.Popen([sys.executable, "-I", "-S", "-c", "import time;time.sleep(90)"])
    time.sleep(90)
if mode == "overflow":
    print("x" * 100000, flush=True)
    time.sleep(90)
if mode == "auth":
    print("authentication required", file=sys.stderr)
    raise SystemExit(1)
if mode == "limited":
    print("usage limit", file=sys.stderr)
    raise SystemExit(1)
answer = "FAKE_CLI_TEST_ONLY review. api_key=IAI_TEST_" + "SECRET_OUTPUT"
tokens = {"input_tokens": 12, "cached_input_tokens": 0, "output_tokens": 4}
if provider == "claude":
    print(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": answer,
                "usage": tokens,
            }
        )
    )
elif provider == "codex":
    print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": answer}}))
    print(json.dumps({"type": "turn.completed", "usage": tokens}))
else:
    print(json.dumps({"text": answer, "stopReason": "end_turn", "usage": tokens}))
