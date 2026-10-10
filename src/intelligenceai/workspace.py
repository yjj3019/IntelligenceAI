import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path

from .contracts import Candidate, safe_path
from .security import SafetyError, digest


def git(repo: Path, *args: str) -> bytes:
    executable = shutil.which("git")
    if not executable:
        raise SafetyError("Git unavailable")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_LFS_SKIP_SMUDGE": "1",
        }
    )
    result = subprocess.run(
        [
            executable,
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.attributesFile=" + os.devnull,
            "-C",
            str(repo),
            *args,
        ],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=30,
        shell=False,
    )
    if result.returncode:
        raise SafetyError("Git operation failed; raw stderr suppressed")
    return result.stdout


def identity(repo: Path) -> tuple[Path, str]:
    resolved = repo.resolve(strict=True)
    top = Path(git(resolved, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if top != resolved:
        raise SafetyError("repo must be its top-level checkout")
    local_config = git(resolved, "config", "--local", "--includes", "--list").decode()
    if any(
        line.lower().startswith(("filter.", "include.", "includeif."))
        for line in local_config.splitlines()
    ):
        raise SafetyError("repo checkout filters/includes require separate trusted validation")
    return resolved, git(resolved, "rev-parse", "HEAD").decode().strip()


def prepare(repo: Path, root: Path, task_id: str, base: str) -> Path:
    destination = root / "workspaces" / task_id
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if git(destination, "rev-parse", "HEAD").decode().strip() != base:
            raise SafetyError("workspace base drift")
        return destination
    # Never reset, stash, or copy the user's working tree. No worker subprocess is enabled.
    git(repo, "worktree", "add", "--detach", str(destination), base)
    return destination


def files(workspace: Path) -> dict[str, tuple[str, int]]:
    if workspace.is_symlink() or (hasattr(workspace, "is_junction") and workspace.is_junction()):
        raise SafetyError("linked workspace root refused")
    workspace = workspace.resolve(strict=True)
    names = set(git(workspace, "ls-files", "-z", "--cached", "--others").decode().split("\0"))
    names.discard("")
    result = {}
    for name in sorted(names):
        safe_path(name)
        path = workspace / name
        if not path.exists() and not path.is_symlink():
            continue
        if any(
            p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
            for p in [path, *path.parents]
            if p != workspace.parent
        ):
            raise SafetyError("linked artifact refused")
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
            raise SafetyError("non-regular or hard-linked artifact refused")
        if info.st_size > 10 * 1024 * 1024:
            raise SafetyError("artifact exceeds snapshot limit")
        result[name] = (hashlib.sha256(path.read_bytes()).hexdigest(), info.st_mode & 0o111)
    if len(result) > 10000:
        raise SafetyError("candidate file count exceeds snapshot limit")
    return result


def baseline(workspace: Path) -> dict[str, tuple[str, int]]:
    result = {}
    for entry in git(workspace, "ls-tree", "-r", "-z", "HEAD").split(b"\0"):
        if not entry:
            continue
        metadata, name = entry.split(b"\t", 1)
        mode, kind, sha = metadata.decode().split()
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise SafetyError("submodule or symlink baseline unsupported")
        value = name.decode()
        safe_path(value)
        # Hash checkout bytes for platform newline handling; baseline established before writing.
        result[value] = (
            hashlib.sha256((workspace / value).read_bytes()).hexdigest(),
            (workspace / value).stat().st_mode & 0o111,
        )
    return result


def freeze(workspace: Path, base: str, initial: dict, allowed: list[str]) -> Candidate:
    head = git(workspace, "rev-parse", "HEAD").decode().strip()
    if head != base:
        raise SafetyError("worker changed Git head")
    current = files(workspace)
    initial = {k: tuple(v) for k, v in initial.items()}
    changed = sorted(k for k in set(initial) | set(current) if initial.get(k) != current.get(k))
    if any(p not in allowed for p in changed):
        raise SafetyError("candidate escaped exact allowed scope paths")
    tree_digest = digest(current)
    cid = digest({"base": base, "head": head, "tree": tree_digest, "changed": changed})
    return Candidate(
        candidate_id=cid,
        base_sha=base,
        head_sha=head,
        tree_digest=tree_digest,
        changed_paths=changed,
        artifact_digests={k: v[0] for k, v in current.items()},
    )


def export(workspace: Path, candidate: Candidate) -> list[bytes]:
    current = files(workspace)
    if digest(current) != candidate.tree_digest:
        raise SafetyError("candidate changed before export")
    # Scan all files including ignored/untracked files. Export names prevent repo ignore/config use.
    payloads = [str(candidate.model_dump()).encode()]
    for name in sorted(current):
        data = (workspace / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != candidate.artifact_digests[name]:
            raise SafetyError("candidate changed during export")
        payloads.append(data)
    return payloads
