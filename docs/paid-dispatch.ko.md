# 승인 요청을 private worker에 전달하는 경로

사용자가 확정 견적을 승인하고 요청하면 `PaidDispatcher.prepare`가 기존 Claude
worker에 전달할 기록을 만든다. 서명과 전달은 private 서버 코드에서 수행한다.
브라우저에는 실행환경·서명·credential 입력이나 worker 실행 API를 추가하지 않았다.
이 변경을 검증할 때 실제 유료 모델은 호출하지 않았다.

서명 발급기는 외부 `ReceiptIssuer` 인터페이스로 주입한다. 검증용 공개키와 역할은
별도 운영 설정에서 가져온다. 코드가 운영 개인키를 만들거나 읽지는 않는다.
운영자는 유효기간이 있는 제어 증거 5개를 제공해야 한다. 유료 호출 승인 증거는
저장된 정확한 견적 digest에서 만든다. 기존 6개 서명은 manifest·승인·증거·만료에
결합하며, 발급된 내용이 요청한 서명 문장과 정확히 일치하는지 검사한다.
파일 존재나 테스트 성공으로 운영 증거를 대체하지 않는다.

서명 작업 뒤 서버는 현재 owner 권한과 session, 후보·증거·프로필·정책·generation,
취소·lease·예산을 다시 검사한다. 요청 소비, 기존 paid ledger의 예산 hold,
private 전달 기록은 같은 DB 트랜잭션으로 저장한다. 실패하면 모두 되돌린다.
응답 유실이나 재시작 뒤에는 같은 invocation과 기존 상태를 조회하며 재예약하지 않는다.

기존 operator worker는 `--descriptor` 대신 `--request-id`로 예약된 전달을 읽을 수
있다. 기존 backend·cgroup·runtime·공개키 인자와 별도로 제공된 credential fd는
계속 필요하다. 두 입력 경로는 같은 runner를 호출한다. 서명을 다시 검증하고
예약을 원자적으로 claim한 뒤에만 로컬 프로세스를 실행하므로 중복 전달은 실행되지 않는다.
실행 gate와 HTTP 직전에도 현재 프로필·권한·견적·취소 상태를 재검사한다.

취소는 기존 작업 API를 사용한다. 전송하지 않았다는 증거가 있으면 hold를 한 번만
해제한다. 실행을 claim한 뒤에는 정리 확인을 기다린다. 시작했거나 결과가 불명확한
호출은 hold를 유지하고 자동 재실행하지 않는다. 새 실행은 새 generation과 승인이
필요하다. lease 만료나 worker 응답 유실만으로 `CANCELLED`를 확정하지 않는다.

인가된 상태 조회는 worker 원장을 함께 읽는다. 미시작은 `NOTRUN`, HTTP 접수 이후는
`REQUEST_STARTED`, 응답 정산·저장 이후는 `RESULT_RECEIVED`, 불명확한 실행은
`UNKNOWN`으로 표시한다. 결과 수신은 모델 정확도나 운영 호환성 검증을 뜻하지 않는다.
전달 descriptor·서명·session hash·서버 경로는 브라우저로 보내지 않는다.

`web_paid_dispatches` 테이블은 DB 백업과 schema 검토 후 기존 `web.manage init-db`
절차로 추가한다. 기록에는 private session 결합과 서명된 권한이 있으므로 private
artifact와 같은 수준으로 보호해야 한다. 기본 signer나 새 credential 설정은 없다.
운영 signer·제어 증거·검증된 Linux 환경·실제 credential의 별도 확인이 없으면 차단한다.

회귀 검증에는 일회성 테스트 서명키와 합성 사용자·프로필·예산을 사용한다.
프로세스·cgroup·HTTP seam도 모의 구현이며, 일반 provider HTTP transport는 차단한다.
요청과 예산의 원자성, 재시작·중복·응답 유실, 취소·권한 철회, 불명확한 결과의
재호출·재과금 차단을 검사한다. CI는 임시 PostgreSQL의 경합도 검사한다.
실제 모델·운영 서명/credential·production cgroup·지원 브라우저와 모바일 QA는
별도 검증이 필요하다. [영문 계약과 운영 조건](paid-dispatch.md)에 상세 내용을 기록했다.
