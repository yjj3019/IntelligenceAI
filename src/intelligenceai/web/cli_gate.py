"""Fixed stdin gate. Native child starts only after its parent assigns containment.

This file is invoked with Python -I -S; it deliberately imports no application code.
"""

import json
import subprocess
import sys


def rate_limits(argv, cwd):
    """Only official read methods; no thread/turn, login or credential transport."""
    child = subprocess.Popen(
        argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, shell=False
    )

    def send(value):
        child.stdin.write((json.dumps(value) + "\n").encode())
        child.stdin.flush()

    def receive(identifier):
        for _ in range(100):
            line = child.stdout.readline(65537)
            if not line or len(line) > 65536:
                raise ValueError("status_protocol_invalid")
            value = json.loads(line)
            if value.get("id") == identifier:
                if "error" in value:
                    raise ValueError("status_query_unavailable")
                return value["result"]
        raise ValueError("status_protocol_invalid")

    try:
        send(
            {
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "intelligenceai", "version": "0.1.0"}},
            }
        )
        receive(1)
        send({"method": "initialized", "params": {}})
        send({"id": 2, "method": "account/rateLimits/read", "params": {}})
        value = receive(2)
        buckets = value.get("rateLimitsByLimitId")
        if not isinstance(buckets, dict):
            buckets = {"default": value.get("rateLimits")}
        safe = []
        for identifier, bucket in list(buckets.items())[:20]:
            if not isinstance(bucket, dict):
                continue
            windows = {}
            for name in ("primary", "secondary"):
                source = bucket.get(name)
                if not isinstance(source, dict):
                    continue
                window = {}
                for field in ("usedPercent", "windowDurationMins", "resetsAt"):
                    number = source.get(field)
                    window[field] = number if type(number) in (int, float) else None
                windows[name] = window
            if windows:
                # Identifiers are source metadata, never free-form config or auth values.
                limit_id = bucket.get("limitId", identifier)
                if not isinstance(limit_id, str) or len(limit_id) > 80:
                    limit_id = None
                safe.append({"limit_id": limit_id, "windows": windows})
        print(json.dumps({"status": "PROVIDED" if safe else "NOT_PROVIDED", "limits": safe}))
        return 0
    except (ValueError, KeyError, TypeError):
        print(json.dumps({"status": "UNAVAILABLE", "limits": []}))
        return 1
    finally:
        child.terminate()


def main():
    # Operator-generated envelope only. The HTTP API never accepts argv or paths.
    raw = sys.stdin.buffer.readline(16385)
    if len(raw) > 16384 or not raw.endswith(b"\n"):
        return 125
    value = json.loads(raw)
    if value.get("mode") == "codex-rate-limits":
        return rate_limits(value["argv"], value["cwd"])
    child = subprocess.Popen(value["argv"], cwd=value["cwd"], stdin=subprocess.PIPE, shell=False)
    child.communicate(value["prompt"].encode("utf-8"))
    return child.returncode


if __name__ == "__main__":
    raise SystemExit(main())
