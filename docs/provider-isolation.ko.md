# Provider 격리 후속 구현

[상세 계약과 출처](provider-isolation.md)를 함께 확인합니다.

이번 구현은 실제 provider 실행에 필요한 내부 계약과 Linux 오프라인 격리
probe를 추가합니다. 유료 모델과 외부 효과는 계속 차단합니다. Fixture 실행
권한이나 probe 통과만으로 실제 모델 실행 권한을 부여하지 않습니다.

실행 manifest는 프로젝트·세션 actor·작업·generation·provider·모델·effort·실행
모드·OS·backend와 실행 파일·runner·정책·이미지·작업 디렉터리 digest를 연결합니다.
쓰기 가능한 파일, 네트워크 정책, credential 참조, caller·overlay digest, 만료와
예산도 포함합니다. 브라우저에서 명령·환경변수·서버 경로·actor·격리 해제 플래그를
입력하는 API는 없습니다. 증거 digest 일치만으로 권한이나 실제 모델 신원을
검증했다고 판단하지 않습니다.

별도 `LinuxOfflineExecutor`는 고정된 합성 probe만 실행합니다. 읽기 전용 이미지와
작업 파일, 명시한 쓰기 파일만 mount하며 host HOME·ledger·credential·Docker socket을
노출하지 않습니다. namespace와 환경변수 격리를 적용하고 모든 네트워크를 분리합니다.
호스트의 동시 파일 변경 방지와 cgroup 자원 제한, credential broker, provider 전용
egress, 과금 제한은 아직 구현·검증되지 않았습니다. 따라서 실제 provider backend로
사용할 수 없습니다.

Omnilane v0.53.0 Grok runner의 기본 재시도는 5회입니다. 준비 계약은 wrapper 시도를
1회로 고정합니다. 내부 native 재시도와 실제 청구 횟수는 별도로 미검증입니다.
Grok의 macOS 파일 변경 모드는 거부하며 unconfined 우회로 전환하지 않습니다.
Gemini CLI와 Antigravity/agy는 서로 다른 계약으로 취급합니다. 실제 caller와
transport overlay를 자동 생성하거나 재서명하지 않습니다.

연결 화면은 서버 OS의 provider·모드별 차단 사유를 KO/EN으로 표시합니다. 상태 API는
프로젝트 권한을 다시 확인하며 DB를 변경하지 않습니다. 경로나 명령, credential을
응답하지 않습니다. Linux CI의 합성 probe는 host 파일 접근, 읽기 전용 파일 쓰기,
host loopback 접속, 환경·설정 누출, timeout·취소 후 setsid 자식 종료를 검사합니다.
backend 부재와 namespace 정책 차단은 `BLOCKED`, 예상 밖의 probe 실패는 `FAILED`,
실제 오프라인 검사 통과만 `VERIFIED_OFFLINE_PROBE`로 구분합니다.

Windows·macOS에서는 이 Linux namespace 검사를 통과로 계산하지 않습니다. 실제
provider는 `NOTRUN`, provider capability는 `UNVERIFIED`로 유지합니다. 지원되는
전용 브라우저가 없어 최신 UI의 브라우저 QA도 `NOTRUN`입니다. Private 공개 배포,
유료 호출, 새 credential, 사용자 PC 패키지 설치·보안 설정 변경은 수행하지 않습니다.
