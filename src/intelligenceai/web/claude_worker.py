"""Operator-only worker entrypoint. No credential file discovery or live enable flag."""

import argparse
import json
import os
import signal
import stat
import time
from pathlib import Path
from threading import Event

from intelligenceai.isolation_contracts import LaunchManifest
from intelligenceai.security import SafetyError, canonical
from intelligenceai.web.claude_contracts import ClaudeProfile, PaidReviewIntent
from intelligenceai.web.claude_runner import ClaudeReviewRunner
from intelligenceai.web.live_authority import ReceiptVerifier, unique_object
from intelligenceai.web.paid_dispatch import run_descriptor, worker_descriptor
from intelligenceai.web.store import engine


def read_operator_json(path, limit, *, private):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        forbidden = 0o077 if private else 0o022
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or (info.st_mode & forbidden or info.st_uid != os.getuid() or info.st_size > limit)
        ):
            raise SafetyError("operator_file_permissions_invalid")
        raw = os.read(descriptor, limit + 1)
        if len(raw) > limit:
            raise SafetyError("operator_file_limit")
        return json.loads(raw, object_pairs_hook=unique_object)
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description="Run one approved tool-free Claude review")
    delivery = parser.add_mutually_exclusive_group(required=True)
    delivery.add_argument("--descriptor", type=Path)
    delivery.add_argument(
        "--request-id", help="private durable dispatch; never replay a started call"
    )
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--delegated-cgroup", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument(
        "--trust-keys",
        type=Path,
        required=True,
        help="independent operator public-key/control map, never a job field",
    )
    parser.add_argument(
        "--credential-fd",
        type=int,
        required=True,
        help="already supplied broker-only API key fd; no token file or login",
    )
    args = parser.parse_args()
    db = None
    try:
        if os.name != "posix" or args.credential_fd < 3:
            raise SafetyError("trusted_linux_worker_required")
        db = engine(os.environ["IAI_DATABASE_URL"])
        descriptor = (
            worker_descriptor(db, args.request_id)
            if args.request_id
            else read_operator_json(args.descriptor, 128 * 1024, private=True)
        )
        if set(descriptor) != {
            "manifest",
            "profile",
            "intent",
            "tokens",
            "session_hash",
        }:
            raise SafetyError("invalid_operator_descriptor")
        manifest = LaunchManifest.model_validate_json(canonical(descriptor["manifest"]))
        ClaudeProfile.model_validate_json(canonical(descriptor["profile"]))
        intent = PaidReviewIntent.model_validate_json(canonical(descriptor["intent"]))
        public_keys = read_operator_json(args.trust_keys, 64 * 1024, private=False)
        signers = {
            name: (entry["control"], entry["public_key"]) for name, entry in public_keys.items()
        }
        verifier = ReceiptVerifier(signers)
        verifier.verify(manifest, intent.approval, tuple(descriptor["tokens"]), now=time.time())
        # Operator process supplies a sealed/one-use pipe fd. The worker does not
        # discover, generate, copy, save or print any user's existing credential.
        value = os.read(args.credential_fd, 4097)
        os.close(args.credential_fd)
        if not 0 < len(value) <= 4096:
            raise SafetyError("broker_credential_fd_limit")
        credential = value.decode("ascii").strip()
        runner = ClaudeReviewRunner(
            db, args.backend, args.delegated_cgroup, args.runtime_root, verifier, lambda: credential
        )
        cancel = Event()
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: cancel.set())
        outcome = run_descriptor(runner, descriptor, cancel, reserved=bool(args.request_id))
        print(canonical(outcome))
    except Exception:
        # Model/transport/cleanup uncertainty is not CANCELLED or a synthetic success.
        raise SystemExit(
            "Claude review not confirmed; inspect private durable accounting."
        ) from None
    finally:
        if db is not None:
            db.dispose()


if __name__ == "__main__":
    main()
