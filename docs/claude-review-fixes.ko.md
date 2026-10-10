# Claude 전송 검토 보완

PR #5 검토에서 요청 경로, thinking 응답, 누적 사용량, 실행 직전 권한과
전송 전 예산 해제를 보완했다. bridge는 `/v1/messages`와
`/v1/messages?beta=true`만 허용한다. 고정 CLI 환경에서
`CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`과
`CLAUDE_CODE_DISABLE_STRUCTURED_OUTPUTS=1`을 사용해 context management 등
사전 공개 필드를 제거한다. 모든 모델에서 thinking을 끌 수 있다고 가정하지
않으며 adaptive thinking과 제한된 manual thinking을 검증한다. thinking도
동일한 출력 토큰·단가 상한에 포함하고, private 결과에는 답변 텍스트만 저장한다.
여러 `message_delta`의 누적 사용량은 최종 값으로 정산한다.

이미지 해시와 cgroup 준비가 끝난 뒤 DB의 project·review·task·job·session
잠금을 유지한 채 프로세스를 생성하고 실행 gate를 허가한다. cgroup에 붙인 뒤
만료와 취소를 다시 확인한다. HTTP·프로세스 대기·relay 정리 중에는 DB 잠금을
유지하지 않는다. gate 허가가 로컬 실행 admission 시점이며, 실제 CLI 생성은
이후에 일어난다. 지원된 구성원·취소 API는 project 잠금을, 로그아웃은 session
잠금을 따르며 운영 provisioning SQL도 같은 잠금 규칙을 지켜야 한다.

lease 없는 예약 취소와 HTTP admission 전에 정리가 확인된 `LAUNCHING`은
보류 예산을 원자적으로 한 번 해제한다. 이미 전송했거나 결과가 불명확하면
로컬 종료만으로 환불하지 않는다. 새 실행은 task 복구로 새 generation을 만들고
새 승인을 받아야 한다. 사용한 승인은 다시 예약할 수 없다.

요청 계약은 [공식 gateway 안내](https://code.claude.com/docs/en/llm-gateway-protocol),
누적 이벤트는 [공식 streaming 안내](https://platform.claude.com/docs/en/build-with-claude/streaming),
thinking 비용은 [공식 thinking 안내](https://platform.claude.com/docs/en/build-with-claude/thinking)를
따른다. 합성 회귀 통과가 실제 CLI·모델 호환성이나 운영 cgroup 검증을 뜻하지 않는다.

Linux의 선택적 cgroup 검사는 fork한 부모·자식의 시작 메시지와 실제
`cgroup.procs` 등록을 먼저 확인한 뒤 `cgroup.kill`, `populated=0`, 두 PID의
종료를 확인한다. 이미 위임된 cgroup이 없으면 이 검사는 건너뛴다.

전체 범위와 배포 입력은 [영문 전송 문서](claude-transport.md)에 정리했다.
