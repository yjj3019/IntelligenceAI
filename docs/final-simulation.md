# 병합 전 시뮬레이션 기록

2026-10-10 UTC, IntelligenceAI PR #1의 오프라인 기반을 검증합니다. 최초 원격·로컬 후보는 `e4aca8aace93a58fa466a2146fdc6b93f47a9a44`였고 작업 폴더는 clean이었습니다. 이번 변경은 검증 driver·CI·이 보고서뿐이며 제품 코드의 최적화나 새 기능은 없습니다. 최종 검증 commit SHA와 CI run은 [PR 본문과 checks](https://github.com/yjj3019/IntelligenceAI/pull/1)에 기록합니다. CI checkout은 PR의 정확한 head SHA를 사용하며 main에서는 push SHA를 사용합니다.

## 범위

| 시뮬레이션 | 프로젝트 소유 fixture와 회귀 |
|---|---|
| 정상 Python/JSON·정적 전용 다중-step | `test_dag.py`, `test_dag_gate_regressions.py`의 submit/run/approve/dry-run |
| 검사 실패·필수 proof 누락 | `test_flow.py`, plan/check/authoritative receipt 변조 |
| 승인 거절·만료·후보 변경 | `test_approvals.py`의 bytes/base/untracked/scope/policy/expiry/reject와 복원 후 폐기 |
| 취소·중복·writer 경쟁·MCP/CLI 소유권 | `test_recovery.py`, `test_mcp_stdio.py`, `test_service_ownership.py` |
| crash와 재시작 | reserve/start/effect/receipt/verified 및 step receipt·durable admission |
| native handle·불명 시작·PAL replay | `test_protocols.py`, `test_protocol_regressions.py`의 STARTING/handle query/phase-two reservation/receipt |
| timeout·자식 생존·stale identity | `test_supervisor.py`의 실제 소유 POSIX child group와 fail-closed 계약 |
| 악성 경로·링크·시크릿 | `test_contracts_security.py`, `test_review_regressions.py`, 실제 `test_scanner_live.py` |
| live gate 차단·MCP 재접속·권한 주입 | 공개 LiveGateway 차단 및 실제 pinned SDK stdio client의 grant/admission/tool schema 검사 |

실제 vendor·유료 모델·로그인·OS 보안 변경은 실행하지 않습니다. Meta는 제외합니다. PAL internal review를 외부 API expert 호출로 표시하지 않으며 MCO selector 보고 일치를 모델 identity attestation으로 표시하지 않습니다.

## 재현

고정 lock의 repo-local 가상환경에서 실행합니다.

```sh
uv sync --frozen --extra dev
uv run --frozen pytest -q -rs --durations=10 --junitxml=test-results.xml
uv run --frozen python scripts/simulate_races.py
uv run --frozen ruff check src tests scripts
uv run --frozen ruff format --check src tests scripts
uv build --no-sources --no-build-isolation
uv run --frozen python scripts/package_smoke.py
```

반복 driver는 seed 17·41·83마다 고정된 경합·소유권·writer·process 테스트 11개 사례를 실행합니다. seed는 test order와 PYTHONHASHSEED만 바꾸며 OS 스케줄링을 고정하지 않습니다. fresh 내부 임시 폴더를 사용하며 실패하면 다음 반복을 중지하고 nonzero로 종료합니다. `.test-runs/simulation-report.json`에는 실제 HEAD, UTC 시작·종료, OS·architecture·Python, 실행 순서, 각 반복 시간·exit code·pass/fail/error/skip와 skip 이유를 기록합니다. timeout도 실패이며 process-tree 종료를 성공했다고 표시하지 않습니다. 이 내부 파일은 Git에 저장하지 않습니다.

## 결과와 판단 조건

로컬 Windows amd64·Python 3.14.4에서 07:45:14–07:47:46 UTC에 seed 17 한 번을 실행해 8 passed/3 skipped, 실패·오류 0건, exit code 0을 확인했습니다. driver 측정 시간은 149.816초이며 pytest는 145.68초였습니다. 3개 skip은 Windows에서 검증되지 않은 실제 POSIX ordinary child group 사례로, `Native POSIX ordinary group test`와 `POSIX process group verification; native Windows UNVERIFIED`를 기록했습니다. 이후 seed 17·41·83의 3회 반복은 최종 head CI의 8개 환경에서 수행합니다.

최초 후보의 [전체 CI run 38034517043](https://github.com/yjj3019/IntelligenceAI/actions/runs/38034517043)는 Linux/Windows/macOS arm64/Intel × Python 3.11/3.14의 8개 조합 모두 성공했습니다. POSIX는 각 181 passed/2 skipped, Windows는 각 177 passed/6 skipped였습니다. 실제 scanner 65개 파일의 탐지 0건과 wheel 설치·격리 import·CLI/MCP smoke도 확인했습니다. 새 최종 후보에서는 전체 검증에 더해 동일한 8개 조합에서 seed 3개를 반복합니다. 최종 실행 결과는 PR에 연결된 해당 head의 CI 로그를 기준으로 합니다.

POSIX의 2개 skip은 `Windows runtime boundary`와 `Windows-specific fail-closed check`입니다. Windows CI에서 확인한 6개 skip은 NUL OS device의 Linux fixture 1개, pinned POSIX scanner 경계 2개, 실제 POSIX process group 3개입니다. symlink 권한이 없는 환경은 해당 fixture가 추가로 skip될 수 있으며 각 실행의 실제 이유를 pytest `-rs` 로그로 보존합니다. skip을 PASS로 바꾸지 않습니다. Python 3.14의 LangChain/Pydantic v1 호환 경고는 숨기지 않습니다. 현재 범위에서 실패가 없고 최종 정확 head의 8개 job이 모두 성공한 후 부모의 독립 확인을 받아 병합합니다. 보호 우회·force push·history rewrite·branch 삭제·배포는 수행하지 않습니다.

성능·비용 벤치마크나 live E2E 결과가 아닙니다. 반복에서 실패가 없다는 관찰은 일반적인 race 부재·OS sandbox·hostile process containment·exactly-once를 보장하지 않습니다. 실제 vendor 실행·credential 강제·Windows process tree는 UNVERIFIED/비활성 상태입니다. Library 원문 전체는 read로 확인했지만 Windows materialize helper의 `os.setxattr` 미지원 blocker는 남아 있습니다.
