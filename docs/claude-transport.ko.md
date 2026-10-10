# Claude 읽기 전용 검토 경로

`intelligenceai.web.claude_worker`에 기존 후보를 검토하는 실제 transport를
추가했다. 별도 Linux worker가 CLI를 실행하고, broker가 provider 요청과 비용을
관리한다. 테스트에는 가짜 CLI와 가짜 provider를 사용했다. 실제 유료 모델 실행과
운영 배포는 아직 검증하지 않았다.

모델·effort·가격은 운영자 설정에서 정한다. 기본 모델이나 최신 가격을 추측하지
않는다. CLI 계약은 `2.1.296`에 맞췄다. 이번 구현은 API key broker 방식의
Claude 검토만 지원한다. Codex·Grok·Gemini와 OAuth 구독 인증은 별도 작업이다.

CLI에는 실제 API key 대신 해당 invocation의 relay capability만 전달한다.
CLI는 네트워크 namespace 안의 loopback bridge에 연결하고, bridge는 private
Unix socket으로 broker에 요청한다. broker만 고정 Anthropic HTTPS endpoint에
연결한다. 사용자 HOME·credential 저장소·프로젝트 hook·MCP 설정을 가져오지
않으며 permission 우회 옵션도 사용하지 않는다.

유료 승인은 후보·증거·정책·destination·generation·actor·만료에 결합한다.
manifest overlay에는 profile·prompt·예산·승인자 ID가 포함된다. 일반 검토 승인과
후보 적용 승인은 유료 호출 권한이 아니다. 실제 요청 직전에 세션과 두 사용자의
역할, 취소 요청, 현재 후보·증거, 프로젝트 예산, 호출 중복 여부를 다시 검사한다.

PostgreSQL은 모델의 전체 입력 context 상한과 제한된 출력 토큰의 최대 비용을
미리 예약한다. 단가는 토큰당 microusd를 올림한 보수적 상한이다. 운영자는
해당 모델의 context와 모든 가격 가산을 검증한 증거를 제공해야 한다.
틀린 상한은 예산 보호를 보장하지 못한다. 완전한 SSE 종료와 알려진 사용량이
확인돼야 예약금을 정산한다. 기록 금액은 사용량에 따른 보수적 비용 상한이며
provider 청구서의 정확한 금액은 아니다.

redirect·timeout·부분 응답·알 수 없는 과금 항목·모델 변경은 전체 예약금을
유지하고 `NEEDS_RECONCILIATION`으로 처리한다. 호출을 자동 재실행하지 않는다.
취소나 로그아웃 후에도 관측한 provider 비용은 정산한다. private 결과를
가져올 때는 현재 권한과 cgroup 전체 종료를 다시 확인하고 저장 전에 비밀을
가린다. 로컬 프로세스 종료만으로 원격 모델 취소를 확정하지 않는다.

실행에는 기존에 위임된 cgroup v2 영역이 필요하다. worker는 새 leaf에
memory·swap·pids·CPU 제한을 적용하고 읽어 확인한 다음 CLI 실행을 허용한다.
종료 후 `cgroup.kill`과 `populated=0`을 확인한다. 전역 controller나 OS 보안
설정은 변경하지 않는다. 위임이 없으면 실행을 막는다.

배포 입력은 PostgreSQL, 서명된 private descriptor, 운영자가 이미 공급한
API key file descriptor, 고정 Linux image와 bubblewrap, 위임된 cgroup,
프로젝트 예산이다. worker의 환경변수명은 `IAI_DATABASE_URL`이다. credential을
`.env`, descriptor, 브라우저 입력에 넣지 않는다. 이번 작업에서 실제 credential을
읽거나 만들지 않았다.

현재 HTTP API에는 유료 검토 enqueue와 활성화 버튼을 추가하지 않았다.
운영 승인 발행·예산 provisioning·GUI admission·배포는 후속 작업으로 남았다.
Linux CI는 실제 namespace와 Unix relay를 가짜 CLI/provider로 검사한다.
실제 cgroup 검사는 기존 `IAI_TEST_DELEGATED_CGROUP`이 있을 때만 실행하며,
없으면 미검증으로 표시한다. 검증 범위와 운영 절차는
[영문 안내](claude-transport.md)에 정리했다.
