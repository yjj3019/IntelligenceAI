import os
import sys
from pathlib import Path

import pytest

from intelligenceai.security import SafetyError
from intelligenceai.supervisor import Supervisor, group_members


def test_windows_supervision_disabled(tmp_path):
    if os.name == "posix":
        pytest.skip("Windows-specific fail-closed check")
    with pytest.raises(SafetyError, match="disabled on Windows"):
        Supervisor().launch([sys.executable, "--version"], 1, tmp_path)


@pytest.mark.skipif(
    os.name != "posix" or not Path("/proc").exists(),
    reason="Linux process tree verification; native Windows UNVERIFIED",
)
@pytest.mark.parametrize("operation", ["timeout", "cancel"])
def test_linux_child_tree_termination(tmp_path, operation):
    supervisor = Supervisor()
    code = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); "
        "time.sleep(30)"
    )
    identity = supervisor.launch([sys.executable, "-I", "-c", code], 5, tmp_path)
    if operation == "timeout":
        result, verified = supervisor.wait(0.3)
        assert result is None and verified
    else:
        with pytest.raises(SafetyError, match="generation"):
            supervisor.terminate(4)
        assert supervisor.terminate(5)
    assert not group_members(identity.pid)
