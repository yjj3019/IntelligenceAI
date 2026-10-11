# 운영 검증과 다음 작업 인계

2026-10-11 UTC 기준 구현 main은 `a01f6bee9673ba75718e5229dce1c83a86a136f0`입니다.
작성 전 최신 원격 main과 전용 checkout의 clean 상태를 확인했습니다.
이 환경에서는 인계 문서의 검토·병합으로 마무리합니다. 운영 잔여 작업은 사용자가
개발툴에서 이어받습니다. 현재 PC·앱·SSH 연결이나 CLI 로그인을 끊으라는 지시가 아닙니다.

## 완료 상태와 근거

오프라인 core·DAG·승인/복구·제한된 MCP([PR #1](https://github.com/yjj3019/IntelligenceAI/pull/1)),
KO/EN private GUI·고정 fixture supervisor([PR #2](https://github.com/yjj3019/IntelligenceAI/pull/2)),
로컬 CLI 검토([PR #9](https://github.com/yjj3019/IntelligenceAI/pull/9)),
소유자 승인 outbound PC 연결([PR #10](https://github.com/yjj3019/IntelligenceAI/pull/10))을 병합했습니다.
GUI는 공개 합성 데모와 private 프로젝트 작업을 구분하며 8개 주요 화면을 제공합니다.
private API는 서버 세션·project 인가·PostgreSQL ledger를 사용하고 실행을 별도 worker로 분리합니다.

PR #10 검토 head는 `0476bd32dddc8d5ed0f196357cf4eeef818cd3ed`입니다.
그 exact SHA의 [push CI](https://github.com/yjj3019/IntelligenceAI/actions/runs/38097683852)와
[PR CI](https://github.com/yjj3019/IntelligenceAI/actions/runs/38097686445), 병합 후
[main CI](https://github.com/yjj3019/IntelligenceAI/actions/runs/38098154158)가 각각 10/10 성공했습니다.
main CI의 대상은 `a01f6bee9673ba75718e5229dce1c83a86a136f0`입니다.
독립 재검토 세 건에서 GUI 역순 읽기, 취소·결과 journal 경합과 두 deadline 경로의 수정을 확인했습니다.

- 최종 후보 로컬 서버: 합성 PC/local CLI/web 회귀 145 passed / 8 skipped.
  PostgreSQL 잠금·Linux 전용 등의 로컬 skip은 통과로 계산하지 않습니다.
- UI: jsdom·mocked fetch 74 tests, lint·typecheck·private/public build·공개 데모 패키징 성공.
  실제 브라우저 QA를 대신하지 않습니다.
- CI: Windows/Linux/macOS arm64·Intel × Python 3.11/3.14 core 8환경,
  web 계약의 실제 임시 PostgreSQL과 실제 Linux 오프라인 namespace probe를 검증했습니다.
  운영 DB/OIDC, 사용자 PC sandbox·live provider E2E 검증은 아닙니다.
- 최종 후보 Gitleaks 8.30.1: exact tracked blob 177개, finding 0건.
  상세 범위는 [검증 기록](web-validation.md)과 [격리 계약](provider-isolation.ko.md)에 있습니다.

## 실제 CLI 관찰과 남은 한계

| CLI | 앞선 명시적 smoke | 상태 |
| --- | --- | --- |
| Claude | 1회 | 성공 관찰. 전체 GUI·PC 등록·운영 E2E 검증은 아님 |
| Codex | 1회 | 불확실. 원시 로그 미보존으로 당시 판정 복원 불가. parser 합성 수정은 실제 재검증이 아님 |
| Grok | 0회 | 호출 범위의 도구·MCP·hook 제한 미검증. 실행 차단 상태이며 계정·구독 문제로 단정하지 않음 |

추가 모델 호출 전 provider·입력·프로젝트·최대 CLI 실행 횟수·시간/예산·허용 도구와
private 증거 보존 범위를 명시적으로 확인합니다. CLI 실행 횟수와 공급자 내부 모델
요청 수는 구분하며 불확실한 시작·결과를 자동 재시도하지 않습니다.

구독·과금은 각 사용자와 AI 서비스가 관리합니다. 앱은 설치·기존 인증 상태·가용성과
공식 조회 가능한 usage만 제공합니다. 실행 토큰과 구독 창을 구분하고 누락값은 미확인으로
둡니다. PC usage는 `USER_DEVICE_REPORT / INPUT_OUTPUT_ONLY`이며 캐시·추론 토큰과
측정 시각을 제공하지 않습니다. 결제 상태·내부 모델 호출 수의 검증 증거가 아닙니다.

UTF-8 JSON·중복 후보 전송 정리의 앞선 합성 fixture 측정은 499 → 417 bytes,
16.4% 감소입니다. 실제 token·quota 절감은 미측정입니다. 개인 사용률·AI 계정·host IP·
개인 로컬 경로·인증정보는 공개 기록에 넣지 않습니다.

[공개 Sites](web-deployment.md)는 읽기 전용 합성 데모뿐입니다. 실제 backend/public
운영 배포, 운영 DB/OIDC/HTTPS, PC 등록·회수와 desktop/mobile 브라우저 QA는 미검증입니다.
당시 공식 IAB 초기화 실패와 현재 작업의 mcp-ssh 도구 미제공은 실행 환경의 제한이며
제품 자체의 SSH 실패가 아닙니다. 다른 SSH·터널·브라우저 설치·보안 우회로 대체하지 않았습니다.

## 개발툴에서 이어받는 순서

1. 최신 저장소·SHA/CI·clean 상태·사용자 변경·AGENTS/관련 skill·runbook을 확인합니다.
   다른 작업의 checkout·CLI 호출과 겹치거나 사용자 변경을 덮지 않습니다.
2. 운영자가 명시적으로 선택한 배포 환경·지원 접근 경로와 기존 서비스·포트·데이터를
   확인합니다. 실제 상태를 확인하지 않은 기존 포트 점유 서비스를 중단하지 않습니다.
3. 비밀이 아닌 HTTPS/DB/OIDC 대상·callback·owner/project 범위·worker 역할과 private
   상태 보존 위치를 확정합니다. 비밀은 주입 경로만 정하고 PC에 서버 DB/OIDC 비밀을 보내지 않습니다.
4. 서비스 영향·schema/backup·신규 credential/OAuth·영구 접근·공개 네트워크/TLS/security
   변경·테스트 PC 등록/회수·최소 CLI 테스트의 구체적 범위를 묶어 운영자 승인을 확인합니다.
5. [배포 안내](web-deployment.md)의 확인된 초기화·bootstrap·build·serve와 지원 방법으로
   배포 검증을 진행합니다. 기존 DB는 backup과 일회용 복사본 검증을 먼저 합니다.
   `init-db`는 기존 schema 자동 migration이 아닙니다. 실제 container/image digest·TLS도 검증합니다.
6. 승인한 테스트 PC만 등록·지문 확인·회수/만료를 검사하고 고정 합성 job으로 queue·권한·
   결과·취소/재접속을 확인합니다. 기존 다른 PC는 건드리지 않고 native 모델 실행과 구분합니다.
7. 승인된 최소 CLI 가용성 테스트만 실행합니다. Grok 제한을 우회하거나 과거 유실 로그를
   복원하려고 새 호출을 하지 않습니다. 현재 구현은 raw CLI stream을 보존하지 않으므로
   private 증거 계획을 먼저 정하며 성공 판정 근거가 부족하면 불확실로 남깁니다.
8. 지원 전용 브라우저로 KO/EN desktop/mobile·키보드·정상/오류·중복·뒤로가기·재접속·
   권한 회수·교차 사용자 접근과 cancel/result/usage를 확인합니다. exact SHA·실제 배포 상태·
   test/skip·모델 실행 횟수·차단 사항을 비밀 없이 보고합니다.

신규 credential/OAuth·영구 접근, 공개 네트워크/TLS/security, 과금·구독 변경과
사용자 프로젝트 범위 밖 접근은 묵시적 승인이 아닙니다. 운영자는 승인한 보안 경로로
비밀을 주입하며 문서·채팅·Git·인자·URL·공개 로그에 기록하지 않습니다.
기존 native 인증은 PC에 유지합니다. 웹 배포/연결 승인이 paid model·외부 효과를
자동 활성화하지 않습니다. 미인증 public-write나 인증 우회 dev mode를 공개하지 않습니다.

## 실행 자료와 완료·복구 기준

- [배포 runbook](web-deployment.md), [Compose](../deploy/compose.yml),
  [Dockerfile](../deploy/Dockerfile), [환경변수 이름 예시](../deploy/env.example).
  Compose/image는 준비 산출물이며 대상에서 실제 검증이 필요합니다.
- [고정 fixture runner](web-runner.md), [PC 연결 한국어](pc-connection.ko.md)·
  [지원 명령](pc-connection.md), [로컬 CLI 한국어](local-cli.ko.md)·
  [기존 직접 DB worker](local-cli.md). 두 worker 경로는 구분합니다.
- [API](web-api.md), [구조](web-architecture.md), [보안](web-security.md).
  고급 [private dispatcher](paid-dispatch.ko.md)·[Claude worker](claude-transport.ko.md)는
  별도 서명·예산·credential·실행환경 전제를 확인하기 전 활성화하지 않습니다.

환경변수 이름은 `IAI_DATABASE_URL`, `IAI_PUBLIC_ORIGIN`, `IAI_OIDC_ISSUER`,
`IAI_OIDC_CLIENT_ID`, `IAI_OIDC_CLIENT_SECRET`, `IAI_TRUSTED_PROXY_IPS`,
`IAI_STATIC_DIR`, `IAI_LISTEN_HOST`, `IAI_RUNNER_DATABASE_URL`, `IAI_RUNNER_STATE_DIR`입니다.
runner 설정은 실행 subprocess에 상속하지 않습니다. 미확인 서버명·개인 경로·model/version을
지어내지 말고 확인된 저장소 지원 방법만 사용합니다.

완료 기준은 승인된 exact SHA/image와 대상에서 HTTPS/OIDC·private DB·project 인가,
상태/log/artifact/SSE 접근 통제, 중복/승인 binding·만료·generation 재검사,
테스트 PC 등록/회수, 합성/실제 결과 구분과 실제 KO/EN 브라우저 검증의 근거입니다.
취소 요청과 종료 확인·`UNKNOWN`을 구분하며 skip·미검증을 성공으로 바꾸지 않습니다.

단계 전후 private checkpoint에 code/image·schema/backup·ledger/attempt/lease/journal
상태와 검증 결과를 보존합니다. 실패하면 해당 배포의 새 실행을 중지하고 기존 검증
image/commit과 DB/receipt의 호환성을 확인합니다. DB restore·schema rollback·credential
회수는 데이터 영향과 별도 승인 범위로 진행합니다. 다른 서비스·PC를 일괄 중단하거나
backup을 덮지 않습니다. 불확실한 소비 journal 삭제·lease 강제 해제·실행 replay를
하지 않습니다. 동일 저장 결과만 `retry-result`로 재전송하며 [receipt 복구 계약](web-runner.md)을 따릅니다.

## English summary

Implementation baseline: main `a01f6bee9673ba75718e5229dce1c83a86a136f0`.
PR #10 head `0476bd32dddc8d5ed0f196357cf4eeef818cd3ed` passed push/PR CI;
merged main passed its own CI, each 10/10. Local synthetic backend: 145 passed /
8 skipped; component UI: 74 passed. CI covers eight core OS/Python environments,
real ephemeral PostgreSQL contracts and offline Linux probes, not production E2E.

Prior explicit CLI smoke: Claude once successful; Codex once uncertain because raw
output was not preserved; Grok zero runs with tool/MCP/hook restrictions unverified.
Synthetic parser fixes are not a real Codex retest. Further model calls need explicit
scope. Synthetic payload reduction was 499 to 417 bytes (16.4%); actual token/quota
savings are unmeasured. Billing/subscriptions remain with users and AI services.

The Sites page is synthetic/read-only. Production backend, DB/OIDC/HTTPS, actual
PC enrollment and browser QA remain unverified. IAB initialization failed and
official mcp-ssh was unavailable in the execution environment; this is not a product
SSH failure. The user will continue operations in their development tool.

Follow the ordered steps and relative runbooks above. New credentials/OAuth,
persistent access, network/TLS/security, billing changes and out-of-project access
are not implicitly authorized. Operators inject secrets securely, never chat/docs/Git.
This handoff does not disconnect existing PCs, apps, SSH sessions or CLI logins.
Preserve private checkpoints; verify rollback compatibility and backup impact;
never clear unknown attempts/journals or replay uncertain launches.
