# 오프라인 adapter 계약

`protocols.prepare`는 버전별 argv 배열, stdin, 절대 cwd, 비어 있는 최소 env, deadline, 요청 provider/model/effort와 candidate digest를 `PreparedInvocation`에 담습니다. executor와 Omnilane lane은 서로 다른 필드입니다. 모델 selector를 임의 명령으로 해석하지 않습니다. 요청한 effort를 upstream 옵션으로 표현할 근거가 없으면 준비를 거부합니다.

Omnilane v0.53.0은 고정 vendor/model의 background single-shot route와 status/result/cancel argv를 준비합니다. JSON result는 가용성 metadata이므로 답변이나 실행 증거로 승격하지 않습니다. cancel에는 upstream이 지원하지 않는 JSON 옵션을 붙이지 않습니다. caller context와 transport overlay는 만들거나 사람 권한을 자칭하지 않습니다.

MCO v0.12.1은 strict read-only review, stdin, 명시적 agent·scope·timeout과 JSON 결과를 준비합니다. complete/partial/failed와 각 output의 success/failed/timeout/cancelled를 구분합니다. raw output은 의견이며 자동 findings나 합의가 아닙니다. PAL v9.8.2는 codereview의 두 단계 메시지와 continuation을 준비합니다. chat/clink는 schema에서 거부합니다. continuation은 실행 receipt가 아닙니다.

Gemini JSON의 response/stats와 agy event stream의 conversation_id/result 구조는 별도 parser로 처리합니다. duplicate result, 잘못된 event, 부분 JSON, 대화 ID 혼합은 거부합니다. 파싱 성공은 모델 매핑이나 OS 격리 검증이 아닙니다.

공개 `LiveGateway`의 submit/poll/collect/cancel/reconcile은 항상 차단합니다. env·CLI·MCP·capability 보고서를 바꿔 활성화할 수 없습니다. `_ProtocolSession`은 프로젝트 테스트가 직접 구성하는 내부 계약 harness입니다. 공개 service는 이 클래스를 생성하지 않으며 fake transport 선택 필드도 없습니다. 테스트 소유 executable과 fake MCP 응답만 주입합니다. 입력 검사 후 ledger STARTING을 먼저 기록하고, receipt 전 crash는 NEEDS_RECONCILIATION으로 남깁니다. rc0 cancel은 process tree 종료를 증명하지 않습니다.

근거: [Omnilane dispatch](https://github.com/Seraphim0916/omnilane/blob/v0.53.0/scripts/dispatch.sh), [jobs](https://github.com/Seraphim0916/omnilane/blob/v0.53.0/scripts/jobs.sh), [MCO CLI](https://github.com/mco-org/mco/blob/v0.12.1/docs/reference/cli.md), [PAL workflow](https://github.com/BeehiveInnovations/pal-mcp-server/blob/v9.8.2/tools/workflow/workflow_mixin.py), [Gemini headless](https://geminicli.com/docs/cli/headless/), [agy headless](https://antigravity.google/docs/cli/headless/).
