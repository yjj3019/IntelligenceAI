#!/python
"""CLI-shaped offline process. Never a Claude model success or paid authentication probe."""

import json
import os
import socket
import sys
import urllib.request


def main():
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=0.2):
            raise RuntimeError("external route escaped namespace")
    except OSError:
        pass
    try:
        with open("/claude", "a") as stream:
            stream.write("unexpected mutable image")
        raise RuntimeError("immutable image escaped")
    except OSError:
        pass
    assert os.environ["ANTHROPIC_API_KEY"] == "fixture-relay-only"
    assert "fixture-broker-only" not in json.dumps(dict(os.environ))
    assert not os.path.exists("/host-marker")
    assert "--dangerously-skip-permissions" not in sys.argv
    prompt = sys.stdin.read()
    model = sys.argv[sys.argv.index("--model") + 1]
    effort = sys.argv[sys.argv.index("--effort") + 1]
    request = urllib.request.Request(
        os.environ["ANTHROPIC_BASE_URL"] + "/v1/messages?beta=true",
        data=json.dumps(
            {
                "model": model,
                "stream": True,
                "max_tokens": 100,
                "messages": [{"role": "user", "content": prompt}],
                "output_config": {"effort": effort},
            }
        ).encode(),
        headers={"Content-Type": "application/json", "x-api-key": "fixture-relay-only"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert b"FAKE_PROVIDER_TEST_ONLY" in response.read()
    print(json.dumps({"result": "FAKE_CLI_TEST_ONLY", "is_error": False}))


if __name__ == "__main__":
    main()
