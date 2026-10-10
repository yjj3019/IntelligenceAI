# Security model

This is a single-user local controller prototype. Do not expose its CLI or SQLite files to untrusted users. Live workers, arbitrary shell, model text as commands, recursive delegation, provider substitution and external publishing are disabled.

## Enforced application checks

- Typed plans reject unknown authority fields, unsafe paths, DAG cycles, missing dependencies and multiple writer steps.
- Capability checks precede effect reservation. Only a fixed local fixture can run.
- Start intent is recorded before an effect; unknown starts require reconciliation. Checkpoints and ledger transactions remain separate.
- Uncertain cancellation preserves writer ownership. Stale generations and conflicting receipts are rejected.
- Candidate fingerprints include tracked, untracked and ignored files, bytes and executable modes. Linked files, submodules, checkout filters and included repo config are refused.
- Approvals bind candidate/base, repo identity, scope, policy, generation, destination, argv and evidence. Candidate drift removes approval and blocks the task.
- Gitleaks is required. Missing/version mismatch/error/timeout/malformed report is UNVERIFIED; all nonzero scans block. Controller-owned config extends defaults. Export filenames prevent repo ignore/config use; inline allow comments are ignored. Raw scanner report/stdout/stderr are not persisted.
- CLI output and errors are sanitized. Regex redaction is defense in depth, not comprehensive detection. Candidate workspaces retain source bytes; do not place real secrets there.
- The local CLI owns approval; no worker endpoint exists. Publish/merge/deploy execution is unimplemented and always disabled.

## Unverified boundaries

Worktrees share Git metadata and are not OS sandboxes. Future workers must not receive credentials, controller state access, inherited environment or metadata/approval write access. This release launches no worker and cannot demonstrate enforced vendor permissions. Filesystem checks do not contain hostile concurrent mutation under the same OS identity.

Linux `/proc` start tokens and a new process session support fixed trusted checker supervision. Tests cover ordinary child termination. A hostile program can escape a process group; the supervisor is not hostile containment. Native Windows Job Object enforcement is unimplemented, so that path is disabled. No WSL configuration is changed.

Git uses fixed local argv with hooks/fsmonitor disabled and global/system config suppressed. Local checkout filters/includes are rejected. This does not sandbox Git against vulnerabilities in a malicious repository. Use trusted disposable fixture repositories only.

SQLite is not encrypted or a multi-user authorization system. Unknown operations must be reconciled from real receipts and verified descendants before unlocking. No external exactly-once guarantee is offered.

Use GitHub's available private reporting channel to report issues to the owner. The project does not automatically send messages or publish security reports.

