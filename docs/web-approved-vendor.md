# Approved synthetic vendor flow

The private console exercises review approval through a real fixed fake executable
and private result storage. Results are `FAKE_VENDOR_TEST_ONLY`, zero model calls,
`live_model: NOTRUN` and `os_sandbox: UNVERIFIED`. This path cannot consume signed
live-authority statements or enable a live vendor/provider.

## Authority and one-time reservation

After the core fixture produces a verified static candidate, a current approver
records its exact private-review binding. An operator/owner explicitly posts `{}`
to `.../tasks/TASK_UUID/run-approved-fixture`. The API checks the current server
session, requester and approver roles, candidate/evidence bytes, policy,
destination, generation, expiry and operator-owned fixture grant. Legacy arbitrary
PASS evidence is insufficient. Browser fields cannot select argv, environment,
executable, path, credential, provider or paid operation. The API never spawns.

`web_vendor_invocations` is unique on task/generation. Admission atomically records
RESERVED, a server-only session hash, approval actor and frozen binding, then
VENDOR_QUEUED task/job state. Same-key retries return the original receipt;
different keys cannot reserve another invocation. GET/Refresh/SSE cannot execute.

The separate runner locks project, task, job and invocation, fences ownership,
and commits STARTING before launch. Immediately before Popen it holds project
and session locks and rechecks all current authority, cancellation, generation,
lease, executable/source pins and remaining deadline in `(0, 300]` seconds.
A monotonic deadline also limits clock rollback. Approval, session, grant and
300-second bounds all apply. It never replays a consumed STARTING intent.

The trusted fake module receives bounded data on stdin and returns a fixed value.
It never evaluates candidate bytes, opens a user repository or uses the network.
The child environment excludes DB/OIDC/provider secrets; stdout/stderr are
discarded and persisted input/results are bounded and scanned. The runner checks
authority/cancellation repeatedly, terminates its owned child when needed, waits
for actual exit, writes an atomic supervisor completion, validates the exact
synthetic result and imports a project-authorized plain-text artifact. Task
`vendor_runs` expose no session hash or lease. This is not hostile-code isolation.

## Cancellation and recovery

| Boundary | Behavior |
| --- | --- |
| RESERVED, unclaimed | Confirm never started; explicit recovery makes a new generation |
| CLAIMED, before STARTING | Fence expired owner and resume the same reservation |
| STARTING/EXECUTING without supervisor completion | NEEDS_RECONCILIATION; no replay or lease clearing |
| Child output file alone | Does not prove the supervisor observed exit |
| Durable supervisor completion | Fence and import once without Popen |
| Active cancellation | CANCEL_REQUESTED until actual wait/never-started proof |

Old-generation receipts cannot authorize new work. Confirmed cancellation allows
explicit recovery, another core fixture and a new approval. History remains.
A crash between durable start intent and Popen can remain uncertain even if no
child was created. No external exactly-once guarantee or force-clear route exists.

## Operation and validation

Back up and test the additive migration on a disposable database copy, then use
the existing `python -m intelligenceai.web.manage init-db` command. Existing tables
are not altered. Use existing operator-owned `IAI_RUNNER_DATABASE_URL` and
`IAI_RUNNER_STATE_DIR`. Run `python -m intelligenceai.web.vendor_runner --once`
or `--reconcile INVOCATION_UUID`. State is private on the runner host, without an
API mount. In addition to [core supervisor privileges](web-runner.md), this runner
needs SELECT on sessions/approvals and SELECT/INSERT/UPDATE on vendor invocations,
with no permission to create sessions, approvals, memberships or grants.

`tests/test_approved_vendor.py` covers both actual core profiles, HTTP approval,
one fake process, private artifacts, requester/approver/session revocation, logout,
binding drift, cancellation, deadline and crash/replay cases. Seeded unit fixtures
are explicitly synthetic. PostgreSQL-only tests use separate pools for reservation
and claim races and active cancellation/recovery; SQLite skips those cases.
`tests/test_web_fullstack.py` covers signed synthetic OIDC, real HTTP/CSRF/session,
core, approval, fake process, private result and logout denial on loopback.
Frontend tests check explicit-only dispatch, authority blockers, old-generation
history and provenance. Browser automation, production OIDC/HTTPS and actual
provider/credential/egress/resource/cost controls remain unverified.

## 한국어 안내

private 콘솔에서 정적 검사가 끝난 후보의 승인을 기록한 뒤 **승인된 합성 vendor 실행**을
명시적으로 요청합니다. DB는 작업과 generation마다 예약을 한 번만 허용합니다.
runner는 실행 직전에 세션, 요청자와 승인자의 현재 권한, 승인 내용, 후보 바이트,
취소와 남은 시간을 다시 검사합니다. 브라우저가 명령·경로·환경·provider를 지정하거나
API가 프로세스를 실행할 수 없습니다.

실제 종료 확인 전에는 취소 요청 상태를 유지합니다. 시작 여부가 불명확하면
`NEEDS_RECONCILIATION`으로 두고 만료된 lease만으로 재실행하지 않습니다.
결과는 private artifact로 저장하며 `FAKE_VENDOR_TEST_ONLY`, 모델 호출 0회,
`NOTRUN`, OS 격리 `UNVERIFIED`로 표시합니다. 서명이나 fake 결과는 실제 유료 모델
권한·운영 격리 증거가 아닙니다. PostgreSQL 경쟁 테스트와 SQLite 테스트는 구분하며,
브라우저 QA 및 운영 OIDC·HTTPS 배포는 별도로 검증해야 합니다.
