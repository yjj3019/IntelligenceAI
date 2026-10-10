# 실제 모델 실행 권한의 서명 계약

이번 단계는 서버 내부 증거의 서명과 승인 바인딩을 검증합니다. 검증에 성공해도
`VERIFIED_SIGNATURES_ONLY`, 실행 `BLOCKED`, 모델 `NOTRUN`을 반환합니다.
실제 credential broker, egress proxy, 자원·비용 제한기와 vendor 실행기는 아직 연결하지 않았습니다.

서버는 DB의 승인 스냅샷에서 `PaidApprovalBinding`을 구성해야 합니다.
사용자·프로젝트·작업·generation과 후보·증거·정책·목적지·manifest·만료 시각을 함께 묶습니다.
고정 fixture 실행 권한을 유료 모델 실행 승인으로 재사용하지 않습니다.

provider capability, credential broker, provider egress, resource limits, cost accounting,
paid-call authorization에 해당하는 서로 다른 증거 6개가 필요합니다.
운영자가 관리하는 Ed25519 공개 키에는 증거 역할을 하나씩 지정합니다.
서명 역할 불일치, 미등록 키, 원격 키 헤더, 대칭 알고리즘, 중복 JSON 필드와 receipt ID를 거부합니다.
증거는 동일한 manifest와 승인 digest에 결합돼야 하며, 승인보다 오래 유효할 수 없습니다.
검증 시점의 실행 마감은 300초 이내여야 합니다. 만료 시각과 같은 시점도 거부합니다.
키 등록이 없는 기본 상태에서는 검증을 차단합니다.

검증기는 HTTP endpoint, 비밀 키 생성, 자격증명 로딩, DB 쓰기와 프로세스 실행 기능을 제공하지 않습니다.
테스트는 메모리 안의 일회용 키와 합성 증거를 사용합니다.
서명 검증은 등록된 발급자가 해당 내용을 서명했다는 사실만 확인합니다.
실제 OS 격리, 비밀정보 전달, 네트워크와 비용 제한이 작동한다는 운영 증거는 별도로 필요합니다.

운영 실행에는 일회성 invocation 예약과 재사용 방지, 현재 권한·generation·승인·취소 재검사,
발급자 등록·키 폐기, 실제 broker·egress·자원·비용 통제가 남아 있습니다.
이 stateless 검증기는 서로 다른 호출 사이의 receipt 재사용을 막았다고 주장하지 않습니다.
실제 프로세스를 생성하는 경계에서도 다시 검증해야 합니다.
현재 Linux executor는 실제 provider 실행을 계속 거부하며 GUI의 readiness도 `BLOCKED`를 유지합니다.
브라우저 QA와 private PostgreSQL·OIDC·HTTPS 운영 배포는 별도 미완료 작업입니다.
