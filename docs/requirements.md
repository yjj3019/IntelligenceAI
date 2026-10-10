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
| 6 인터페이스 | submit/preview/status/results/approve/reject/cancel/run/recover/dry-run/capabilities CLI | 로컬 stdio MCP 여섯 tool 구현, 상태 화면 미구현 |
| 7 승인·근거 | exact candidate/action/argv/destination/policy/proof/scope/expiry digest, mutation gate 테스트 | 실제 외부 action 항상 disabled |
| 7 시크릿 | known-pattern redaction, mandatory pinned Gitleaks contract, sanitized report metadata | native Windows scanner supervision·모든 secret 탐지 UNVERIFIED |
| 7 격리 | live worker disabled, 링크·위험경로·필터 거부, worktree 한계 명시 | 실제 OS sandbox/credential isolation UNVERIFIED |
| 7 실패 | reserve/start/effect/receipt/verify crash injection, duplicate/stale 거부, unknown writer 보존 | vendor reconnect·수동 안전 reconciliation 미구현 |
| 7 timeout/cancel | Linux/Darwin birth identity·generation·group 검증과 ordinary child 테스트 | Windows Job Object·hostile escaped process containment UNVERIFIED |
| 8 환경 | Windows/Linux·macOS arm64/x64 CI, repo-local venv/lock, 설치 wheel smoke | WSL2/auth 동작 UNVERIFIED, 설정 변경 없음 |
| 9 단계 P0 | 존재/버전만 확인, official 계약 기록 | paid auth/model probe 생략, live P0 차단 |
| 9 단계 P1–P3 | fixture 수직 흐름, 제한 수리, 승인·복구 회귀 | 실제 vendor/OS 검증 별도 필요 |
| 9 단계 P4–P5 | API/외부 executor capability 미노출 | stdio MCP 구현, UI/publish/merge/deploy 미구현 |
| 10 수용 기준 | fixture PASS·실제 미검증 분리, 비용/속도/품질/exactly-once 과장 없음 | 전체 제품 acceptance는 미충족 |
| 11 대안 | 현재 구조 유지 | scale 필요 시 별도 평가 |
| 12 산출물 상태 | 코드·문서·lock·테스트·CI | live E2E·API·성능·비용은 UNVERIFIED |

## 실제 P0 관찰

MCP 추가 구현: 같은 Controller의 로컬 stdio service, operator repository grant, durable 중복 admission 및 여섯 tool을 구현했습니다. 실제 SDK client 왕복과 권한 주입·재접속·취소 경합은 `tests/test_mcp_stdio.py`에 있습니다. 모델 tool의 approval/publish/merge/deploy, HTTP 포트, 앱 등록 및 UI는 구현하지 않습니다.

다단계 추가 구현: steps[0]와 단일 파일에 의존하던 controller 실행을 typed DAG로 교체했습니다. step receipt·result reference·직렬 writer·고정 후보의 병렬 정적 검토·실패 dependency 차단·기존 repair decision을 연결했습니다. 정적 parser와 두 소유 샘플의 3-step E2E는 `tests/test_dag.py`에서 확인합니다. 임의 프로젝트 test/build 실행은 계속 UNVERIFIED입니다.

추가 구현: 버전별 PreparedInvocation, Omnilane jobs argv, MCO partial 결과, PAL codereview 다단계 메시지, Gemini/agy 별도 parser와 테스트 전용 lifecycle harness를 저장했습니다. 공개 live 실행은 불변 차단합니다. [현재 계약](protocols.md)과 `tests/test_protocols.py`를 대조합니다.

2026-10-10에 프로젝트 안에서 명령 존재와 버전을 확인했습니다. Git 2.54.0.windows.1, Python 3.14.4, uv 0.11.11, Claude Code 2.1.296, Codex CLI 0.162.0, Grok 1.0.50입니다. Omnilane/MCO/PAL/Gitleaks는 PATH에서 발견하지 못했습니다. 광범위 홈/다른 앱 스캔, 인증 변경, 실제 모델 호출, doctor/detect, OS 보안 설정 변경은 하지 않았습니다.

`gh auth status`는 기존 인증이 유효하지 않음을 보고했습니다. 연결된 GitHub 도구는 대상 저장소 읽기/쓰기 권한을 확인했습니다. 원격은 commit/ref가 없는 empty repo였으므로 최소 README main bootstrap 후 구현 브랜치·draft PR 전략을 사용했습니다. 기존 사용자 파일은 없었으며 다른 프로젝트를 수정하지 않았습니다.

## 회귀 증거

MCP runner와 CLI가 같은 작업을 실행하는 경합은 `tests/test_service_ownership.py`에서 실제 service submit 경로와 barrier로 재현합니다. task lease 충돌은 별도 TaskOwnershipConflict로 반환하며 상태·호출 원장을 변경하지 않습니다. 예상하지 못한 실행 실패의 후보 무효화는 Controller가 lease를 보유한 동안에만 수행합니다.

추가 검토 반영: 승인 gate는 plan의 모든 step/check와 authoritative receipt를 대조합니다. Python·JSON fixture와 정적 검사 전용 DAG를 승인할 수 있고, 누락·추가·중복·stale proof는 기존 승인을 폐기합니다. writer의 선언 검사도 실행하며 임의 test/build는 UNVERIFIED로 차단합니다. admission 중 cancel이 generation을 바꾸면 READY로 덮어쓰지 않습니다. MCP startup recovery는 granted repository에 한정하며 실행 중인 controller의 task lease를 획득할 수 없으면 건드리지 않습니다. `tests/test_dag_gate_regressions.py`와 `tests/test_protocol_regressions.py`가 해당 경계의 증거입니다.

`tests/test_flow.py`: fixture 수직 흐름·사용자 변경 보존·수리 한도·필수 검사 누락·CLI E2E·SQLite interrupt 재시작.
`tests/test_recovery.py`: 5개 crash 경계·중복 receipt·stale generation·unknown cancel·single writer.
`tests/test_approvals.py`: bytes/untracked/base/policy/evidence/scope/expiry/destination/argv/reject 변경과 복원 후 승인 재사용 차단.
`tests/test_contracts_security.py`: 경로/DAG/권한 입력·provider 대체·시크릿·scanner report·Gemini/agy/MCO 계약.
`tests/test_supervisor.py`: Linux/macOS ordinary child timeout/cancel, stale identity·실패 열거·빠른 종료·surviving group, Windows disabled.

