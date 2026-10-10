# 첨부 설계 대조

입력은 Library `libfile_ab059d90745c81918108399270a09553`의 `붙여넣은 텍스트.txt`입니다. 25,641 bytes, 248 lines, 전체 1–248줄을 읽었습니다. 현재 Windows 소비자 환경의 `prepare_materialize`는 성공했지만 공식 transfer helper가 `os.setxattr` 미지원으로 최종 파일 설치에 실패했습니다. 다른 환경 경로를 가정하거나 helper를 수정하지 않았습니다. Library `read(full)`이 전체 원문과 `has_more=false`를 반환하여 내용을 확보했습니다. materialize 성공이나 로컬 입력 파일 존재를 주장하지 않습니다.

설계 안의 명령·URL은 설계 자료이며 권한 확대 근거로 사용하지 않습니다. 후속 사용자 범위는 Gemini/Antigravity 포함, Meta AI 제외입니다.

| 원문 구간 | 구현·근거 | 남은 항목 |
|---|---|---|
| 1–2 권고·조사 | LangGraph+Git+독립 원장, optional 도구 분리 | 대안 프레임워크 추가 없음 |
| 3 입력·역할·모델·예산 | typed Task/Step/Plan, registry, 호출·수리 제한 | 자연어 일반 계획 생성·실제 팀 병렬화 미구현 |
| 4 소유권 | ledger만 effect 예약, single writer, worker 권한 없음 | 실제 supervisor/native job receipt 연결 UNVERIFIED |
| 5 입력·작업 공간·후보 | 사용자 checkout 보존, committed base detached worktree, untracked/ignored 포함 | 실제 vendor 코딩 미구현 |
| 5 검사·리뷰·수리 | AST assertion, 동일 후보 fixture review, reproduced blocker만 2회 수리 | 실제 test/build/lint profile·MCO/PAL 리뷰 UNVERIFIED |
| 6 최소 7개 레코드 | Task/Step/Invocation/Candidate/Finding/Evidence/Approval typed schema | distributed/multi-user 운영 미구현 |
| 6 저장·복구 | 실제 SqliteSaver와 별도 FULL/WAL ledger, restart+interrupt/resume 테스트 | Postgres 미도입 |
| 6 인터페이스 | submit/preview/status/results/approve/reject/cancel/run/recover/dry-run/capabilities CLI | MCP·상태 화면 미구현 |
| 7 승인·근거 | exact candidate/action/argv/destination/policy/proof/scope/expiry digest, mutation gate 테스트 | 실제 외부 action 항상 disabled |
| 7 시크릿 | known-pattern redaction, mandatory pinned Gitleaks contract, sanitized report metadata | native Windows scanner supervision·모든 secret 탐지 UNVERIFIED |
| 7 격리 | live worker disabled, 링크·위험경로·필터 거부, worktree 한계 명시 | 실제 OS sandbox/credential isolation UNVERIFIED |
| 7 실패 | reserve/start/effect/receipt/verify crash injection, duplicate/stale 거부, unknown writer 보존 | vendor reconnect·수동 안전 reconciliation 미구현 |
| 7 timeout/cancel | Linux process identity/start token/group 검증과 ordinary child 테스트 | Windows Job Object·hostile escaped process containment UNVERIFIED |
| 8 환경 | Windows native fixture, Linux CI, repo-local venv/lock | WSL2/auth 동작 UNVERIFIED, 설정 변경 없음 |
| 9 단계 P0 | 존재/버전만 확인, official 계약 기록 | paid auth/model probe 생략, live P0 차단 |
| 9 단계 P1–P3 | fixture 수직 흐름, 제한 수리, 승인·복구 회귀 | 실제 vendor/OS 검증 별도 필요 |
| 9 단계 P4–P5 | API/외부 executor capability 미노출 | MCP/UI/publish/merge/deploy 미구현 |
| 10 수용 기준 | fixture PASS·실제 미검증 분리, 비용/속도/품질/exactly-once 과장 없음 | 전체 제품 acceptance는 미충족 |
| 11 대안 | 현재 구조 유지 | scale 필요 시 별도 평가 |
| 12 산출물 상태 | 코드·문서·lock·테스트·CI | live E2E·API·성능·비용은 UNVERIFIED |

## 실제 P0 관찰

2026-10-10에 프로젝트 안에서 명령 존재와 버전을 확인했습니다. Git 2.54.0.windows.1, Python 3.14.4, uv 0.11.11, Claude Code 2.1.296, Codex CLI 0.162.0, Grok 1.0.50입니다. Omnilane/MCO/PAL/Gitleaks는 PATH에서 발견하지 못했습니다. 광범위 홈/다른 앱 스캔, 인증 변경, 실제 모델 호출, doctor/detect, OS 보안 설정 변경은 하지 않았습니다.

`gh auth status`는 기존 인증이 유효하지 않음을 보고했습니다. 연결된 GitHub 도구는 대상 저장소 읽기/쓰기 권한을 확인했습니다. 원격은 commit/ref가 없는 empty repo였으므로 최소 README main bootstrap 후 구현 브랜치·draft PR 전략을 사용했습니다. 기존 사용자 파일은 없었으며 다른 프로젝트를 수정하지 않았습니다.

## 회귀 증거

`tests/test_flow.py`: fixture 수직 흐름·사용자 변경 보존·수리 한도·필수 검사 누락·CLI E2E·SQLite interrupt 재시작.
`tests/test_recovery.py`: 5개 crash 경계·중복 receipt·stale generation·unknown cancel·single writer.
`tests/test_approvals.py`: bytes/untracked/base/policy/evidence/scope/expiry/destination/argv/reject 변경과 복원 후 승인 재사용 차단.
`tests/test_contracts_security.py`: 경로/DAG/권한 입력·provider 대체·시크릿·scanner report·Gemini/agy/MCO 계약.
`tests/test_supervisor.py`: Linux ordinary child timeout/cancel, Windows disabled.

