"""Installed native CLI metadata; no account/config/token file access."""

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from intelligenceai.security import digest
from intelligenceai.web.cli_process import LocalProcess, native_environment
from intelligenceai.web.store import now

TECHNICAL_BLOCKERS = {
    "grok": (
        "--tools filters built-ins only; invocation-only exclusion of MCP and hooks is unverified."
    ),
}
SUPPORTED_VERSIONS = {"claude": "2.1.296", "codex": "0.162.1"}


class NativeRuntime:
    """Normal restricted native invocation; unsupported controls fail closed.

    The local consent queue does not itself authorize overriding managed policy,
    moving credentials to a container, or relaxing these controls.
    """

    scope = "LOCAL_NATIVE_CLI"

    def __init__(self, provider, executable, version):
        if provider not in {"claude", "codex", "grok"}:
            raise ValueError("unsupported_cli_provider")
        self.provider = provider
        self.executable = Path(executable).resolve(strict=True)
        if not self.executable.is_file():
            raise ValueError("cli_not_installed")
        self.version = version
        self.binary_digest = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        from intelligenceai.web import cli_gate, cli_process, cli_results

        self.code_digest = digest(
            {
                "python": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
                "runtime": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "gate": hashlib.sha256(Path(cli_gate.__file__).read_bytes()).hexdigest(),
                "process": hashlib.sha256(Path(cli_process.__file__).read_bytes()).hexdigest(),
                "parser": hashlib.sha256(Path(cli_results.__file__).read_bytes()).hexdigest(),
            }
        )

    def manifest(self):
        return {
            "provider": self.provider,
            "version": self.version,
            "binary_digest": self.binary_digest,
            "scope": self.scope,
            "can_execute": SUPPORTED_VERSIONS.get(self.provider) == self.version,
            "installation": "INSTALLED",
            "availability": "UNVERIFIED",
            "restriction": TECHNICAL_BLOCKERS.get(self.provider),
            "quota": {"status": "NOT_PROVIDED", "limits": [], "measured_at": None},
        }

    def probe(self, cwd):
        """User-requested local status only; no model turn or raw account output."""
        metadata = self.manifest()

        def read(arguments):
            process = LocalProcess([str(self.executable), *arguments], cwd, "")
            try:
                process.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                pass
            finally:
                closed = process.close()
            stdout, stderr = process.output()
            if not closed or process.overflow.is_set() or process.process.returncode != 0:
                return None
            return stdout.decode("utf-8", errors="replace"), stderr.decode(
                "utf-8", errors="replace"
            )

        version = read(["--version"])
        if not version or not re.search(
            r"(?<!\d)" + re.escape(self.version) + r"(?!\d)", version[0]
        ):
            return metadata | {"can_execute": False, "availability": "VERSION_UNVERIFIED"}
        authentication = "NOT_PROVIDED"
        if self.provider == "claude":
            value = read(["--safe-mode", "auth", "status", "--json"])
            try:
                status = json.loads(value[0]) if value else {}
                authentication = (
                    "AUTHENTICATED"
                    if status.get("loggedIn") is True
                    else "AUTHENTICATION_REQUIRED"
                    if status.get("loggedIn") is False
                    else "UNAVAILABLE"
                )
            except (ValueError, TypeError):
                authentication = "UNAVAILABLE"
        elif self.provider == "codex":
            value = read(["--no-daemon", "login", "status"])
            if value:
                authentication = (
                    "AUTHENTICATED"
                    if "Logged in using ChatGPT" in "\n".join(value)
                    else "UNAVAILABLE"
                )
        return metadata | {
            "authentication": authentication,
            "status_checked_at": now(),
            "status_source": self.provider + ":official-native-status",
        }

    @property
    def runtime_digest(self):
        # Mutable usage snapshots must never change execution identity.
        return digest(
            {
                "provider": self.provider,
                "version": self.version,
                "binary_digest": self.binary_digest,
                "code_digest": self.code_digest,
                "scope": self.scope,
                "restriction_contract": "native-read-only-v1",
            }
        )

    def start(self, cwd, prompt, before_start, *, on_spawn=None):
        if not self.manifest()["can_execute"]:
            raise RuntimeError("native_cli_restrictions_unverified")
        if hashlib.sha256(self.executable.read_bytes()).hexdigest() != self.binary_digest:
            raise RuntimeError("native_cli_binary_changed")
        if self.provider == "claude":
            argv = [
                str(self.executable),
                "--safe-mode",
                "--restricted",
                "--tools",
                "",
                "--strict-mcp-config",
                "--mcp-config",
                '{"mcpServers":{}}',
                "--settings",
                '{"disableAllHooks":true}',
                "--no-session-persistence",
                "--permission-mode",
                "dontAsk",
                "--max-turns",
                "1",
                "--output-format",
                "json",
                "--print",
            ]
        else:
            git = shutil.which("git")
            if not git:
                raise RuntimeError("local_git_unavailable")
            subprocess.run(
                [git, "init", "--template=", "--quiet", str(cwd)],
                check=True,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=native_environment(),
                timeout=5,
            )
            argv = [str(self.executable), "--no-daemon", "--ask-for-approval", "never"]
            for feature in (
                "hooks",
                "plugins",
                "apps",
                "shell_tool",
                "unified_exec",
                "browser_use",
                "computer_use",
                "image_generation",
                "multi_agent",
                "code_mode_host",
                "view_image",
                "skill_search",
                "skill_mcp_dependency_install",
            ):
                argv.extend(["-c", f"features.{feature}=false"])
            argv.extend(
                [
                    "-c",
                    'web_search="disabled"',
                    "exec",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "--ephemeral",
                    "--sandbox",
                    "read-only",
                    "--json",
                    "--cd",
                    str(cwd),
                    "-",
                ]
            )
        return LocalProcess(argv, cwd, prompt, before_start=before_start, on_spawn=on_spawn)

    def quota(self, cwd):
        value = {
            "status": "NOT_PROVIDED",
            "limits": [],
            "measured_at": now(),
            "source": self.provider + ":official-cli-status",
            "unit": "percent",
        }
        if self.provider != "codex" or self.version != "0.162.1":
            return value
        process = LocalProcess(
            [
                str(self.executable),
                "--no-daemon",
                "-c",
                "features.hooks=false",
                "-c",
                "features.plugins=false",
                "-c",
                "features.apps=false",
                "app-server",
                "--stdio",
            ],
            cwd,
            "",
            mode="codex-rate-limits",
        )
        try:
            process.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass
        finally:
            closed = process.close()
        try:
            response = json.loads(process.output()[0])
            if closed and response.get("status") in {"PROVIDED", "NOT_PROVIDED", "UNAVAILABLE"}:
                return value | response | {"source": "codex:account/rateLimits/read"}
        except (ValueError, TypeError, AttributeError):
            pass
        return value | {"status": "UNAVAILABLE"}
