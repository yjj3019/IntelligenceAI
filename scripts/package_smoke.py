"""Install the built wheel into the owned CI venv and check isolated entry points."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
wheels = list((root / "dist").glob("intelligenceai-*.whl"))
if len(wheels) != 1:
    raise SystemExit("Exactly one built wheel required")
uv = shutil.which("uv")
if not uv or sys.prefix == sys.base_prefix:
    raise SystemExit("Repo-local venv and installed uv required")
subprocess.run(
    [uv, "pip", "install", "--no-deps", "--reinstall", "--python", sys.executable, str(wheels[0])],
    check=True,
    stdin=subprocess.DEVNULL,
)
code = (
    "import intelligenceai,pathlib; p=pathlib.Path(intelligenceai.__file__).resolve(); "
    "print(p); assert 'site-packages' in p.parts"
)
subprocess.run([sys.executable, "-I", "-c", code], check=True, stdin=subprocess.DEVNULL)
scripts = Path(sys.executable).parent
suffix = ".exe" if os.name == "nt" else ""
result = subprocess.run(
    [str(scripts / ("intelligenceai" + suffix)), "capabilities"],
    check=True,
    capture_output=True,
    stdin=subprocess.DEVNULL,
)
capabilities = json.loads(result.stdout)
assert all(
    not entry["enabled"] for entry in capabilities if entry["executor"] not in {"static", "fixture"}
)
subprocess.run(
    [str(scripts / ("intelligenceai-mcp" + suffix)), "--help"], check=True, stdin=subprocess.DEVNULL
)
print("Built wheel, isolated import, CLI and MCP entry points verified")
