"""Fixed synthetic executable. No credentials, network, project code or model calls."""

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from uuid import UUID


def main():
    raw = sys.stdin.read(8193)
    if len(raw) > 8192 or len(sys.argv) != 2:
        raise ValueError("invalid fixture invocation")
    request = json.loads(raw)
    identifier = str(UUID(request["invocation_id"]))
    if identifier != request["invocation_id"] or request["scope"] != "FAKE_VENDOR_TEST_ONLY":
        raise ValueError("invalid fixture scope")
    root = Path(sys.argv[1]) / identifier
    root.mkdir(exist_ok=True)
    with (root / "started.json").open("x", encoding="utf-8") as marker:
        json.dump({"invocation_id": identifier, "pid": os.getpid()}, marker)
        marker.flush()
        os.fsync(marker.fileno())
    # Bounded fixture delay makes cancellation observable; never derived from browser input.
    time.sleep(1)
    result = {
        "invocation_id": identifier,
        "input_digest": hashlib.sha256(raw.encode()).hexdigest(),
        "status": "SYNTHETIC_OUTPUT",
        "scope": "FAKE_VENDOR_TEST_ONLY",
        "message": "Fixed synthetic vendor response",
        "value": 42,
        "model_calls": 0,
        "live_model": "NOTRUN",
        "os_sandbox": "UNVERIFIED",
    }
    temp = root / "vendor-result.part"
    with temp.open("x", encoding="utf-8") as target:
        json.dump(result, target, sort_keys=True)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temp, root / "vendor-result.json")


if __name__ == "__main__":
    main()
