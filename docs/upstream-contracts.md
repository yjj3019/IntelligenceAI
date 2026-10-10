# 조사 계약과 미검증 연결

이 문서와 `adapter_contracts.py`는 연결 준비 자료입니다. 설치·실제 운영·vendor E2E 지원을 주장하지 않습니다. JSON/stream 예시는 controller가 만든 합성 fixture이며 upstream이 제공한 녹화 응답이 아닙니다. fixture 검증이 실패하면 연결을 열지 않습니다. 성공하더라도 OS 권한 강제·모델 확인·재시작 receipt를 별도로 검증해야 합니다.

## Omnilane

후보 upstream은 [Seraphim0916/omnilane v0.53.0](https://github.com/Seraphim0916/omnilane/tree/v0.53.0)입니다. 사용자의 기존 정확 도구인지 확인되지 않았습니다. 단일 작업 배분 책임을 유지하며 caller context/host transport 근거 없이는 disabled입니다. operator-human 신원 환경 변수를 controller가 위조하지 않습니다. `sysops`와 권한 우회 플래그를 노출하지 않습니다.

route의 background/single-shot, mode advise/work, workdir/vendor/model/effort/timeout/job-timeout과 stdin 계약을 조사했습니다. background job은 상위 프로세스 종료 후에도 살아 있을 수 있습니다. 실제 jobs ID와 `jobs cancel` 계약이 필요하며 `jobs --json result`의 가용성 metadata를 답변 본문으로 취급하지 않습니다.

v0.53.0의 gemini provider는 [common.sh](https://github.com/Seraphim0916/omnilane/blob/v0.53.0/scripts/lib/common.sh)에서 agy로 연결합니다. Gemini CLI와 자동 대체하지 않습니다. 비공개 `--app_data_dir`나 display-string 모델 매핑을 복제하지 않습니다.

## MCO

후보 upstream은 [mco-org/mco v0.12.1 CLI](https://github.com/mco-org/mco/blob/v0.12.1/docs/reference/cli.md)입니다. 응답은 raw opaque answers와 운영 상태이며 자동 findings/severity/consensus 판정이 아닙니다. complete/partial/failed 종료와 invocation success/failed/timeout/cancelled를 별개로 봅니다.

조사한 profile은 `review --execution-mode read_only --enforcement-mode strict --agent alias=provider:model --task-id stable-id --file - --json --result-mode both` 및 명시 timeout입니다. 제거된 `--format`, `--strict-contract`, `--diff`, staged/unstaged/diff-base 옵션을 생성하지 않습니다. task-id는 artifact 이름이며 upstream idempotency 보장이 아닙니다. allow-paths는 sandbox가 아닙니다.

gemini와 agy는 별개 provider입니다. [Gemini detect](https://github.com/mco-org/mco/blob/v0.12.1/runtime/adapters/gemini.py)는 실제 생성 호출을 할 수 있어 무료 preflight로 호출하지 않습니다. [agy adapter](https://github.com/mco-org/mco/blob/v0.12.1/runtime/adapters/agy.py)의 plan+sandbox와 rc0/nonempty text는 enforced read-only나 검증 완료를 증명하지 않습니다. 메모리 shim handle은 재시작 내구성 근거가 아닙니다.

## PAL

[PAL v9.8.2](https://github.com/BeehiveInnovations/pal-mcp-server/tree/v9.8.2)는 선택 분석 후보입니다. `clink`는 미노출이며 allowlist 검증 전 전체 adapter가 disabled입니다. chat은 `readOnlyHint=false`이며 생성 artifact가 있으므로 단순 read-only 분석이라고 선언하지 않습니다. codereview 다단계 step/findings/relevant_files, continuation_id는 실제 tools/list와 version별 확인이 필요합니다. continuation은 job receipt나 공유 기억이 아닙니다.

## Gemini CLI와 Antigravity

[Gemini headless](https://geminicli.com/docs/cli/headless/)의 스트림은 init/message/tool_use/tool_result/error/result입니다. exit0/1/42 입력/53 turn-limit를 조사했습니다. [Antigravity headless](https://antigravity.google/docs/cli/headless/)는 별도 agy 실행 제품입니다. print/model/effort/output-format, conversation_id/status/response/usage, init/step_update/result를 구분합니다. JSON 부분·EOF·final 누락·중복은 성공으로 처리하지 않습니다.

agy의 SUCCESS/rc0도 soft-denied tool 실행을 완료로 증명하지 않습니다. [modes](https://antigravity.google/docs/cli/modes/)의 plan mode는 prompt 방향이며 OS write-deny 증거가 아닙니다. WAITING/RUNNING은 terminal result가 아니며 control_request/control_response를 지원한다고 가정하지 않습니다. 모델 선택 증거·Windows 권한·취소/재시작을 확인하지 못했으므로 disabled입니다.

## Gitleaks와 LangGraph

[Gitleaks v8.30.1 root flags](https://github.com/gitleaks/gitleaks/blob/v8.30.1/cmd/root.go)를 확인해 고정 profile을 작성했습니다. redaction100, explicit trusted config, ignore-inline-allow, JSON report, 전용 leak exit10과 inner20/outer25초를 사용합니다. target 자체의 .gitleaksignore도 읽을 수 있어 후보 파일을 controller-owned 이름으로 export해 검사합니다. scanner stdout/stderr와 Match/Secret/Line은 저장하지 않습니다.

[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)와 [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)에 따라 노드 재실행을 전제로 설계했습니다. 실제 pinned SqliteSaver를 테스트하며 ledger와 checkpoint 원자성을 주장하지 않습니다.

