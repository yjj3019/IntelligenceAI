"""Report the actual runner architecture; labels alone are not support evidence."""

import argparse
import json
import platform

parser = argparse.ArgumentParser()
parser.add_argument("--expected", choices=["arm64", "x64"], required=True)
args = parser.parse_args()
machine = platform.machine().lower()
actual = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
print(
    json.dumps(
        {
            "system": platform.system(),
            "machine": machine,
            "mac_version": platform.mac_ver()[0],
            "python": platform.python_version(),
        }
    )
)
if platform.system() == "Darwin":
    import psutil

    assert psutil.__version__ == "7.2.2"
    print("Darwin process backend psutil=" + psutil.__version__)
if actual != args.expected:
    raise SystemExit("Runner architecture differs from declared CI contract")
