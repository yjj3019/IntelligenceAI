# 로컬 stdio MCP

공식 Python SDK mcp 1.26.0을 고정하고 기존 CLI와 같은 Controller를 사용합니다. 이 server는 stdin/stdout만 사용합니다. HTTP 포트, 앱 등록, 로그인이나 모델 sampling은 없습니다.

```sh
uv run --frozen intelligenceai-mcp --state-dir /absolute/controller-state --repo sample=/absolute/owned-repo
```

Windows에서는 `.venv\Scripts\intelligenceai-mcp.exe`와 절대 Windows 경로를 사용합니다. repository 이름과 경로는 운영자가 시작 인자로 부여합니다. tool 입력으로 저장소 경로·상태 폴더·env·credential·transport·principal·approval을 바꿀 수 없습니다. 상태 폴더는 부여한 저장소 밖에 둡니다. Mac 설치는 macOS 안내를 따릅니다.

노출 tool은 capabilities, preview, submit, status, results, cancel 여섯 개입니다. approve/reject/publish/merge/deploy는 없습니다. 사람의 CLI 승인은 별도입니다. model tool의 annotation은 권한 강제 수단이 아니며 실제 schema·repository grant·불변 live gate가 요청을 차단합니다.

submit은 repository 이름, request, typed plan, idempotency_key를 받습니다. 검증 후 durable admission을 먼저 기록하고 로컬 작업을 최대 두 개까지 수행합니다. 같은 key와 내용은 같은 task를 반환합니다. 다른 내용은 거부합니다. admission 도중 crash로 CLAIMED만 남으면 자동 재제출하지 않습니다. 재접속은 상태와 결과를 조회하며 이전 작업을 자동 실행하지 않습니다. 불명확한 STARTING invocation은 NEEDS_RECONCILIATION으로 남습니다. 같은 cancel은 generation을 다시 증가시키지 않습니다.

worktree 준비 중 cancel이 들어오면 원래 state·generation에 묶인 READY 전이가 거부되어 worker를 큐에 넣지 않습니다. CLAIMED 중복 응답으로 알게 된 task ID도 취소할 수 있습니다. 실행 중인 controller는 task별 OS 파일 잠금을 보유합니다. 시작 복구는 현재 grant에 포함되고 살아 있는 실행 소유자가 없는 작업에만 적용합니다. 다른 저장소나 다른 host의 활성 실행을 crash 잔여 작업으로 바꾸지 않습니다. 이 잠금은 로컬 단일 사용자 소유권 장치이며 OS sandbox나 분산 잠금이 아닙니다.

사용자 코드는 정적 검사만 하며 fixture profile은 신뢰한 상수만 씁니다. 실제 vendor adapter와 test/build 실행은 비활성화합니다. multi-user 인증·다른 앱 등록·네트워크 service는 구현 범위가 아닙니다. 기본 scanner가 없거나 process 종료 검증이 불가능하면 결과는 UNVERIFIED이고 승인을 통한 외부 공개 근거가 될 수 없습니다.

`tests/test_mcp_stdio.py`는 실제 SDK client/server의 handshake, tools/list, 세 단계 submit→status→result, 재접속, 중복·충돌 요청, 권한 주입 및 취소 경합을 검증합니다. 별도 테스트 소유 PAL MCP server는 codereview 두 단계 메시지만 응답하며 공개 application 설정에서 선택할 수 없습니다. [공식 SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.26.0)와 [고정 PyPI 배포](https://pypi.org/project/mcp/1.26.0/)를 사용합니다.
