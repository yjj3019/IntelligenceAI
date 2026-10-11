# 운영 검증과 다음 작업 인계

2026-10-11 UTC 기준, GUI와 소유자 승인 PC 연결 구현은 main에 병합했습니다.
기준 구현 commit은 `a01f6bee9673ba75718e5229dce1c83a86a136f0`입니다.
문서 작성 전에 원격 main과 전용 checkout의 clean 상태를 확인했습니다.
운영 배포, 실제 PC 등록, GUI 브라우저 QA는 아직 완료하지 않았습니다.
이 문서는 다음 운영자가 확인할 순서와 승인 범위를 기록합니다.
현재 연결된 PC, Codex 앱, SSH 연결이나 CLI 로그인을 끊으라는 지시가 아닙니다.
이 환경에서의 작업은 문서 인계와 검토·병합으로 마무리합니다. 아래 운영 잔여 작업은
사용자가 개발툴에서 이어받습니다. 새 코드·배포·연결·모델 호출을 여기서 시작하지 않습니다.

## 완료된 구현과 근거

로컬 core는 LangGraph·SQLite ledger, typed DAG, 후보·증거·승인 digest,
generation·lease와 제한된 stdio MCP를 제공합니다. 웹 콘솔은 공개 읽기 전용
합성 데모와 private 프로젝트 작업을 구분합니다. 대시보드, 프로젝트·구성원,
새 작업·계획 미리보기, 작업 상세·단계, 후보 diff·검사, 승인·복구,
연결·실행환경, 감사의 8개 화면과 KO/EN UI를 구현했습니다.
웹 API는 서버 세션·프로젝트 권한·CSRF·중복 제출 방지와 PostgreSQL 원장을 사용하고,
실행은 API와 분리한 worker 경로를 사용합니다.

아래 commit 링크는 각 PR의 병합 commit을 가리킵니다. 당시 검증을 현재 운영 성공으로
해석하지 않습니다. 상세 계약은 해당 PR과 연결된 실행 문서에서 확인합니다.

| PR | 완료한 코드 범위 | 병합 commit | 해당 main CI |
| --- | --- | --- | --- |
| [#1](https://github.com/yjj3019/IntelligenceAI/pull/1) | 오프라인 core, DAG, 승인·복구, 제한된 MCP | [b41bb91aa312](https://github.com/yjj3019/IntelligenceAI/commit/b41bb91aa3120f040afa441c105bc8e285014e27) | [성공](https://github.com/yjj3019/IntelligenceAI/actions/runs/38036610851) |
| [#2](https://github.com/yjj3019/IntelligenceAI/pull/2) | 이중 언어 private 콘솔과 고정 fixture supervisor | [3c4f36006771](https://github.com/yjj3019/IntelligenceAI/commit/3c4f36006771d746ed5f48841c5dd8adcc0d8fef) | [성공](https://github.com/yjj3019/IntelligenceAI/actions/runs/38060613361) |
| [#3](https://github.com/yjj3019/IntelligenceAI/pull/3) | provider readiness와 Linux 오프라인 격리 probe | [21fc70a9d2e8](https://github.com/yjj3019/IntelligenceAI/commit/21fc70a9d2e8e194cee4c1104f0071985053258c) | [성공](https://github.com/yjj3019/IntelligenceAI/actions/runs/38067218181) |
| [#4](https://github.com/yjj3019/IntelligenceAI/pull/4) | 승인된 합성 프로세스 일회성 실행·private 결과 | [a8f9718a96df](https://github.com/yjj3019/IntelligenceAI/commit/a8f9718a96df3b87425e107523272bbca83148cf) | [성공](https://github.com/yjj3019/IntelligenceAI/actions/runs/38075485398) |
| [#5](https://github.com/yjj3019/IntelligenceAI/pull/5) | Claude 격리 worker·broker·예산 원장 | [55c6484d4a41](https://github.com/yjj3019/IntelligenceAI/commit/55c6484d4a41a1914a960df3fcaf5cadd95bd646) | [성공](https://github.com/yjj3019/IntelligenceAI/actions/runs/38082373311) |
| [#6](https://github.com/yjj3019/IntelligenceAI/pull/6) | 제한된 유료 검토 동의·대기 요청 | [3c0137fe2935](https://github.com/yjj3019/IntelligenceAI/commit/3c0137fe293567eb5f8753d300a50486241be7a9) | [성공](https://github.com/yjj3019/IntelligenceAI/actions/runs/38084691764) |
| [#7](https://github.com/yjj3019/IntelligenceAI/pull/7) | 요청에서 서명된 private dispatcher로 연결 | [6993eb5a89a0](https://github.com/yjj3019/IntelligenceAI/commit/6993eb5a89a01a3924272241fa73e7983e1079d6) | [당시 실패](https://github.com/yjj3019/IntelligenceAI/actions/runs/38084997596), #8 후속 수정 |
| [#8](https://github.com/yjj3019/IntelligenceAI/pull/8) | 병렬 fixture의 유료 profile 회수 회귀 수정 | [353b51e20d8e](https://github.com/yjj3019/IntelligenceAI/commit/353b51e20d8e2b3bafd05c7509a5f8de1785531f) | [성공](https://github.com/yjj3019/IntelligenceAI/actions/runs/38087429913) |
| [#9](https://github.com/yjj3019/IntelligenceAI/pull/9) | 소유자에 결합된 로컬 native CLI 검토·usage | [ab5d2b3c3834](https://github.com/yjj3019/IntelligenceAI/commit/ab5d2b3c383422b193c463dc5195a0ba77cbb7a9) | [성공](https://github.com/yjj3019/IntelligenceAI/actions/runs/38093925432) |
| [#10](https://github.com/yjj3019/IntelligenceAI/pull/10) | outbound HTTPS PC 등록·승인·회수, deadline·취소 경합 수정 | [a01f6bee9673](https://github.com/yjj3019/IntelligenceAI/commit/a01f6bee9673ba75718e5229dce1c83a86a136f0) | [성공](https://github.com/yjj3019/IntelligenceAI/actions/runs/38098154158) |

PR #10의 최종 검토 head는 `0476bd32dddc8d5ed0f196357cf4eeef818cd3ed`입니다.
그 exact SHA의 [push CI](https://github.com/yjj3019/IntelligenceAI/actions/runs/38097683852)와
[PR CI](https://github.com/yjj3019/IntelligenceAI/actions/runs/38097686445), 병합 후
`a01f6bee9673ba75718e5229dce1c83a86a136f0`의 main CI가 각각 10/10 성공했습니다.
독립 재검토 세 건에서 GUI 역순 읽기, 취소·결과 journal 경합과 최종 gate·실행 중
deadline 수정 및 회귀를 확인했고 추가 차단 사항은 없었습니다.

| 검증 종류 | 확인한 범위 | 남은 경계 |
| --- | --- | --- |
| 최종 후보의 로컬 서버 회귀 | PC·local CLI·web 합성 suite 145 passed, 8 skipped | skip은 PostgreSQL 잠금·Linux 전용 검증 등의 로컬 미실행 항목이며 통과로 계산하지 않음 |
| UI component·정적 빌드 | 74 tests, lint·typecheck, private/public build와 단일 공개 데모 패키징 성공 | mocked fetch·jsdom 결과이며 실제 브라우저 QA 아님 |
| exact release scanner | Gitleaks 8.30.1, tracked blob 177개, finding 0건 | 실제 provider 성공·운영 credential 검사 증거 아님 |
| 최종 main CI | Windows·Linux·macOS arm64/Intel × Python 3.11/3.14의 core 8환경, web 계약, Linux probe의 10 jobs 성공 | live provider·운영 배포 검증 아님 |
| CI의 실제 임시 PostgreSQL | 권한·원장·claim/start 동시성 계약과 row lock 검증 | 운영 DB·백업·migration·OIDC 연결 검증 아님 |
| CI의 실제 Linux namespace probe | 네트워크 차단·고정 악성 probe·합성 relay 등 오프라인 경계 검증 | 사용자 PC의 OS sandbox나 native provider 실행 안전성을 대신하지 않음 |

추가 검증 설명은 [웹 검증 기록](web-validation.md),
[Linux 격리 범위](provider-isolation.ko.md),
[과거 core 시뮬레이션](final-simulation.md)에 있습니다. 과거 기록의 날짜·SHA를 유지합니다.

## 실제 CLI 관찰과 사용량

아래는 앞선 작업에서 수행한 명시적 CLI smoke 관찰입니다. 이번 문서 작업에서는
모델을 호출하지 않습니다. CLI 한 번의 실행과 공급자 내부 모델 요청 수는 구분합니다.

| CLI | 실제 smoke 횟수 | 상태와 다음 확인 |
| --- | --- | --- |
| Claude | 1회 | 성공 관찰. 이 한 번의 응답은 전체 GUI·PC 등록·운영 배포나 모든 제한 경로의 E2E 검증이 아님 |
| Codex | 1회 | 불확실. 원시 로그가 보존되지 않아 당시 최종 응답 판정을 복원할 수 없음. 이후 parser 합성 회귀 수정은 실제 재검증이 아님 |
| Grok | 0회 | 도구·MCP·hook을 호출 범위로 제한하는 조건 미검증. 현재 실행 경로는 차단하며 계정·구독 문제로 단정하지 않음 |

추가 모델 호출 전에는 운영자가 provider, 대상 입력·프로젝트, 최대 CLI 실행 횟수,
실행 시간·예산, 허용 도구와 보존할 private 증거 범위를 명시적으로 확인합니다.
불확실한 시작·결과를 해결하려고 자동 재시도하지 않습니다.

구독·과금 관리는 각 사용자와 AI 서비스의 책임입니다. 앱은 설치·기존 인증 상태,
가용성 관찰과 공식 인터페이스로 조회 가능한 usage만 제공합니다. 실행 토큰과
계정 구독 창을 구분하고 누락된 값은 미확인으로 표시합니다. 원격 PC usage는
`USER_DEVICE_REPORT / INPUT_OUTPUT_ONLY`이며 캐시·추론 토큰과 측정 시각을 제공하지
않습니다. 원격 보고는 결제 상태나 provider 내부 호출 수의 검증 증거가 아닙니다.

토큰 최적화에는 실제 UTF-8 JSON과 중복 후보 전송 정리가 포함됩니다.
앞선 합성 fixture 측정은 499 → 417 bytes, 16.4% 감소입니다.
이는 payload bytes의 감소이며 실제 token·quota 절감은 측정하지 않았습니다.
개인 사용률, AI 계정, host IP, 개인 로컬 경로와 인증정보는 공개 기록에 넣지 않습니다.
세부 계약은 [로컬 CLI 안내](local-cli.ko.md)와 [PC 연결 안내](pc-connection.ko.md)에 있습니다.

## 현재 배포 상태와 환경 제한

[공개 Sites 소개·배포 기록](web-deployment.md)은 읽기 전용 합성 데모입니다.
Python backend, private PostgreSQL·OIDC, 사용자 PC pairing을 연결한 공개 운영 서비스의
성공 증거가 아닙니다. 실제 backend 배포, 운영 DB·OIDC·HTTPS 연결,
실제 PC 등록·회수와 desktop/mobile 브라우저 QA는 미검증 상태입니다.

당시 지원된 공식 IAB 초기화가 실패해 실제 브라우저 QA를 실행하지 못했습니다.
현재 작업 환경에는 공식 mcp-ssh 도구가 제공되지 않아 승인된 운영 접근 경로를 사용할
수 없었습니다. 이는 작업 도구의 환경 제한이며 제품 자체의 SSH 연결 실패를 뜻하지
않습니다. 다른 SSH 경로, 터널, 브라우저 설치나 보안 우회로 대체하지 않았습니다.

API 서버는 임의 저장소 코드·vendor CLI를 직접 실행하지 않습니다.
유료 provider 운영은 서명·기존 credential·예산·실행환경 검증이 준비될 때까지
차단합니다. 웹 배포나 PC 연결 승인이 외부 효과·paid model 실행을 자동 활성화하지
않습니다. 인증 우회 dev mode나 미인증 public-write 데모를 공개하지 않습니다.

## 이어받는 순서

1. **기준과 작업 상태 확인.** 최신 원격 main·commit·CI, clean 상태, 사용자 변경,
   현재 적용되는 `AGENTS.md`·`.agents`·관련 skill과 아래 runbook을 확인합니다.
   문서 기준 SHA와 새 head가 다르면 변경 내용을 먼저 검토합니다. 사용자 변경을
   덮거나 기존 작업의 checkout·CLI 호출과 겹치지 않습니다.
2. **대상과 충돌 확인.** 운영자가 명시적으로 선택한 배포 환경과 지원 접근 경로를
   확인합니다. 실제 기존 서비스·포트 점유·데이터·worker 상태를 읽고 충돌을 검토합니다.
   상태를 확인하지 않은 기존 포트 점유 서비스를 중단하지 않습니다. 준비된 Compose의
   바인딩도 대상에서 확인하며 PC 포트 개방·새 터널을 기본 배포 방법으로 삼지 않습니다.
3. **비밀이 아닌 운영 조건 확정.** HTTPS origin·TLS ingress 역할, DB/OIDC 연결 대상의
   식별 정보와 callback, owner/project 범위, worker 역할·private 상태 보존 위치를
   운영자와 확정합니다. 비밀값은 받거나 기록하지 않고 주입 경로만 정합니다.
   사용자 PC에는 outbound PC 경로를 사용하며 서버 DB·OIDC 비밀을 전달하지 않습니다.
4. **필요 승인을 묶어 확인.** 현재 서비스 영향, schema·backup/restore 계획, 필요한
   credential/OAuth·영구 접근, 네트워크·TLS·보안 변경, 실제 PC 등록·테스트 대상 회수,
   최소 모델 테스트 범위를 구체적인 계획으로 운영자에게 확인합니다.
   승인되지 않은 항목은 차단 상태로 남기고 독립적으로 가능한 검증을 진행합니다.
5. **배포와 보안 경계 검증.** [배포 안내](web-deployment.md)에 확인된 초기화·bootstrap·
   빌드·serve 절차와 운영자가 선택한 지원 방법을 사용합니다. 기존 DB는 백업하고
   일회용 복사본에서 schema 변경을 먼저 검증합니다. `init-db`는 기존 schema를
   자동 migration하는 도구가 아닙니다. 준비된 image/Compose의 실제 build·runtime·
   immutable image digest·TLS를 대상에서 검증하고 테스트 issuer를 공개하지 않습니다.
6. **실제 등록과 합성 job 검증.** 승인된 테스트 PC의 지문 확인·등록·회수·만료를
   확인합니다. 이미 연결된 다른 PC는 건드리지 않습니다. 별도의 고정 fixture job으로
   대기열·권한·결과·취소·재접속을 먼저 확인합니다. 합성 job은 모델 호출이 아니며,
   실제 PC 등록 확인만으로 native CLI 실행을 시작하지 않습니다.
7. **승인된 최소 CLI 가용성 테스트.** 선택된 provider·입력·범위 안에서만 테스트하고
   성공·불확실·미실행을 구분합니다. Grok 제한 미검증 상태를 우회하지 않습니다.
   현재 구현은 원시 CLI 스트림을 보존하지 않으므로 증거 수집 계획을 먼저 정하고,
   성공 판정 근거가 부족하면 불확실로 남깁니다. 새 호출로 과거 유실 로그를 복원하지
   않습니다. 비밀이 제거된 결과·terminal/exit/usage 근거만 승인된 private 경로에 둡니다.
8. **GUI와 최종 보고.** 지원된 전용 브라우저로 KO/EN desktop/mobile, 키보드 접근성,
   정상·오류·중복·뒤로가기·재접속·권한 회수·교차 사용자 접근을 확인합니다.
   cancel은 요청과 종료 확인을 구분하고 result·usage의 출처·누락값을 검사합니다.
   실제 SHA·배포 상태·테스트 종류·skip·차단 사항·모델 실행 횟수와 checkpoint를
   보고합니다. 공개 보고에는 개인 계정·주소·경로·비밀값을 넣지 않습니다.

## 승인과 비밀 주입

신규 credential/OAuth 등록·로그인, 영구 접근 설정, 공개 네트워크·TLS·보안 설정
변경, 과금·구독 변경과 사용자 프로젝트 범위 밖 접근은 묵시적으로 승인되지 않습니다.
GUI 구현·배포 승인을 그 작업들의 자동 승인으로 확대하지 않습니다.
필요한 변경은 영향과 검증·복구 계획을 묶어 운영자에게 확인합니다.

운영자는 승인한 secret manager나 별도 보안 경로로 비밀을 주입합니다.
문서·채팅·Git·명령 인자·URL·공개 로그에 비밀값을 남기지 않습니다.
기존 native CLI 인증은 해당 PC에 유지하고 서버로 복사하지 않습니다.
이 인계 기록은 기존 연결의 해제·회수나 새 credential 생성을 실행하지 않습니다.

## 준비된 실행 자료

실행할 대상과 값이 확인된 뒤 아래 저장소 지원 방법을 사용합니다.
미확인 서버명·개인 경로·model/version 값으로 명령을 완성하지 않습니다.

| 자료 | 용도와 주의 |
| --- | --- |
| [배포 안내](web-deployment.md) | 공개 산출물, private 초기화·bootstrap·빌드·serve와 운영 경계 |
| [Compose](../deploy/compose.yml), [Dockerfile](../deploy/Dockerfile) | Linux 준비 산출물. 실제 대상의 container·TLS 검증은 남아 있음 |
| [환경변수 이름 예시](../deploy/env.example) | 값은 비어 있음. 운영자가 기존 승인 값을 보안 경로로 주입 |
| [고정 fixture runner](web-runner.md) | `allow-fixed-fixture`, `runner --once`, receipt 기반 reconcile와 최소 DB 권한 |
| [PC 연결 한국어](pc-connection.ko.md), [실행 명령](pc-connection.md) | 숨김 pairing 입력·지문 확인, `pair`·`once`·`retry-result`; 새 등록은 별도 승인 |
| [로컬 CLI 한국어](local-cli.ko.md), [기존 DB worker 실행](local-cli.md) | 초기 직접 DB worker와 outbound PC는 별도 경로. 실행·quota·구독 경계 |
| [API](web-api.md), [구조](web-architecture.md), [보안](web-security.md) | 세션·project 인가, private artifact, CSRF·XSS·SSRF·Host/Origin 방어 |
| [private dispatcher](paid-dispatch.ko.md), [Claude worker](claude-transport.ko.md) | 고급 경로의 별도 서명·예산·credential·실행환경 전제. 기본 활성화하지 않음 |

환경변수 이름은 `IAI_DATABASE_URL`, `IAI_PUBLIC_ORIGIN`, `IAI_OIDC_ISSUER`,
`IAI_OIDC_CLIENT_ID`, `IAI_OIDC_CLIENT_SECRET`, `IAI_TRUSTED_PROXY_IPS`,
`IAI_STATIC_DIR`, `IAI_LISTEN_HOST`, `IAI_RUNNER_DATABASE_URL`,
`IAI_RUNNER_STATE_DIR`입니다. 이 목록은 값이나 배포 대상을 제공하지 않습니다.
runner 전용 설정은 실행 subprocess에 상속하지 않습니다.

## 완료 수용 기준과 checkpoint·rollback

운영 작업은 다음 근거가 있을 때 해당 범위만 완료로 보고합니다.

- 승인된 exact SHA·image와 배포 대상에서 HTTPS·OIDC 로그인·세션·private DB를
  확인하고, owner/project 권한과 상태·로그·artifact·SSE의 교차 사용자 차단을 검증합니다.
- 읽기·refresh·재접속으로 작업을 시작하지 않고, 중복 제출이 일회성으로 처리되며
  승인 binding·만료·generation 변경이 실행 전에 재검사되는지 확인합니다.
- 승인한 테스트 PC만 등록·회수되고 비밀은 PC/서버의 승인 경로에 남습니다.
  `CANCEL_REQUESTED`·종료 보고·`UNKNOWN`을 구분하고 불확실한 실행을 반복하지 않습니다.
- 합성 fixture와 실제 CLI 결과를 구분하며 KO/EN·모바일·키보드·오류 화면을 실제
  브라우저로 확인합니다. 모델·quota·비용·OS 격리의 미검증 상태를 성공으로 바꾸지 않습니다.
- 실패·skip과 미완료 운영 항목, 승인된 최소 CLI 테스트 결과를 비밀 없이 보고합니다.

각 단계 전후에 승인된 private 운영 기록으로 코드/image 식별자, schema·backup,
원장·attempt·lease·journal 상태, 실행한 검증과 결과를 남깁니다. 공개 인계 문서에는
비밀이나 개인 식별값을 옮기지 않습니다. 별도 worker 상태와 private artifact도 보존합니다.

실패하면 새 작업 수락·실행을 그 배포 범위에서 중지하고 이전 검증 image/commit으로
돌아갈 수 있는지 운영자가 확인합니다. 다른 서비스나 현재 PC 연결을 일괄 중단하지
않습니다. DB restore·schema rollback과 권한/credential 회수는 데이터 영향과 호환성을
확인한 뒤 별도 승인 범위로 수행합니다. schema를 무조건 삭제하거나 backup을 덮지 않습니다.
`STARTING`·`RUNNING`·`UNKNOWN`의 소비 journal을 삭제하거나 lease를 강제로 지워
재실행하지 않습니다. 저장된 동일 결과만 `retry-result`로 재전송하고 기존 receipt 기반
복구 계약을 따릅니다. 이전 버전이 최신 schema·receipt와 호환되지 않으면 rollback도
차단 상태로 보고하고, 안전한 복구 계획을 운영자와 확정합니다.

## English summary

The implementation baseline is main commit
`a01f6bee9673ba75718e5229dce1c83a86a136f0`. PRs #1–#10 are merged; their exact
merge commits and CI links are listed above. PR #10 head
`0476bd32dddc8d5ed0f196357cf4eeef818cd3ed` passed push and PR CI, and merged main
passed its own CI, each 10/10 jobs. Local affected synthetic backend tests were
145 passed / 8 skipped; UI had 74 passing component tests. Eight core OS/Python
environments, real ephemeral PostgreSQL contracts and Linux offline probes are
verified within CI scope. These results do not prove live deployment or native model E2E.

Prior explicit CLI smoke observations: Claude once successful; Codex once
uncertain because raw output was not preserved; Grok zero runs with invocation
tool/MCP/hook restrictions unverified and execution blocked. Synthetic parser
fixes do not constitute a real Codex retest. Further model calls require explicit
provider/input/project/count/time/budget and evidence scope. Billing and
subscriptions remain each user's and AI service's responsibility. The application
only exposes installation/authentication observations, availability and officially
available usage. Remote usage is device-reported input/output only. Synthetic
payload reduction was 499 to 417 bytes (16.4%); actual token/quota savings are unmeasured.

The public Sites page is a synthetic read-only demo. Production backend,
DB/OIDC/HTTPS, real PC enrollment and browser QA remain unverified. Supported IAB
initialization failed in the prior environment; official mcp-ssh tools were not
provided here. These are execution-environment limitations, not product SSH failures.

Continue in this order: verify repository/clean state/instructions; select an
explicit deployment target and inspect existing service/port conflicts; resolve
non-secret HTTPS/DB/OIDC/owner/project/worker conditions; obtain bundled operator
approvals; validate deployment; test approved PC enrollment/revocation and a fixed
synthetic job; perform only explicitly approved minimal CLI checks; verify KO/EN
desktop/mobile/error/cancel/result/usage; report exact evidence and blockers.
Use the relative runbook, Compose, Dockerfile and variable-name links above;
never invent hosts, personal paths or model/version values.

New credentials/OAuth, persistent access, network/TLS/security changes, billing
changes and access outside the user's project are not implicitly authorized.
Operators inject secrets through an approved secure path, never documents/chat/Git.
This handoff does not disconnect an existing PC, app, SSH session or CLI login.
Work in this environment closes with documentation review and merge; the user
will continue the remaining operational work in their development tool.
Keep private checkpoints and rollback compatibility/backup evidence. Preserve
unknown attempts and journals; never clear leases or replay uncertain launches.
