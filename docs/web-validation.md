# 웹 GUI 검증 기록

2026-10-10, Windows x64의 GUI 전용 checkout에서 확인했습니다. 이 기록은 로컬 검증과 실제 운영 연결을 구분합니다. 공개 서버·DB·OIDC 등록은 생성하지 않았으며 유료 모델과 외부 효과를 실행하지 않았습니다.

| 검사 | 로컬 결과 | 범위 |
|---|---|---|
| backend 웹 회귀 | 42 passed, 1 skipped | SQLite fixture, 객체별 인가, CSRF/Host/Origin, 공격 입력, 세션, 중복·취소·복구·승인 binding; 실제 PostgreSQL 동시성 테스트는 로컬 skip |
| 서명된 OIDC 회귀 | 위 42개에 포함 | 실제 Authlib 검증 경로 + 오프라인 서명 issuer; nonce/audience/issuer/expiry/서명/미등록 사용자 거부 |
| frontend 회귀 | 16 passed | 8개 화면, 공개·private 경계, 취소 확인, 자동 재접속 권한회수, 단절 재시도·다음 요청 key 구분, 원문 escaping, KO/EN 키·fallback·언어 보존 |
| frontend lint / typecheck | 통과 | ESLint 및 strict TypeScript |
| 일반·공개 frontend build | 통과 | `dist` 및 별도 `dist-public` |
| Python lint / format | 통과 | 전체 `src tests scripts` |
| npm audit | 0 vulnerabilities | 고정 lock 설치 시점의 조회 결과 |
| 공개 단일 HTML | 생성 | 자체 JS/CSS, hash navigation, CSP connect-src none |
| 정확한 release blob 비밀 검사 | 0 findings | 공식 SHA256 검증 Gitleaks 8.30.1, 원문 보고서는 보관하지 않음 |

지원되는 전용 Chrome 테스트 탭에서 공개 데모의 모바일 390px, KO/EN 전환, 새로고침·뒤로가기, 키보드 계획 미리보기와 후보 diff를 확인했습니다. KO·EN 폼과 후보 화면의 document 너비가 viewport를 넘지 않았습니다. locale 시간대는 실제 브라우저의 Asia/Seoul로 표시되었습니다.

전용 loopback fullstack에서는 합성 서명 issuer와 실제 Authlib callback을 거쳐 LOCAL TEST USER로 로그인하고, private 계획 미리보기·HELD 제출·취소 확인 대화상자·never-started 취소 확인 완료를 검증했습니다. 이 검증은 실제 외부 issuer나 운영 PostgreSQL 연결 증거가 아닙니다. 브라우저 설치나 보안 우회는 하지 않았습니다. 전체 core 회귀와 CI 결과는 실행 완료 후 추가합니다.

## 실제 운영에서 남은 검증

실제 PostgreSQL은 로컬에 제공되지 않았습니다. 별도 CI의 임시 PostgreSQL 17.6에서 웹 계약이 통과했습니다. 8개 동시 요청의 단일 task/job/receipt와 별도 pool 재연결도 포함합니다. [초기 웹 CI](https://github.com/yjj3019/IntelligenceAI/actions/runs/38042438809)는 성공했으며, 같은 run의 POSIX core는 합성 regression token 문자열이 비밀 검사에 걸려 중단되었습니다. 원문 token을 런타임에서 구성하도록 수정한 뒤 정확한 release scan은 0 findings입니다. 기존 8개 OS·Python core matrix는 유지했고 수정된 commit에서 재실행합니다.

CI의 임시 DB 검증은 운영 DB의 장애 재시작·backup 검증이 아닙니다. 실제 OIDC 등록, HTTPS ingress의 Secure cookie, 운영 권한회수, DB backup/암호화, 프록시·rate limit·접근 로그, 컨테이너와 Linux runner 격리는 확인하지 못했습니다. runner는 구현하지 않은 상태로 실행을 거부합니다.

운영 배포에 필요한 값의 이름과 초기화 순서는 [배포 절차](web-deployment.md)에 있습니다. 사용자 또는 부모 작업이 승인한 공개 Linux 대상·기존 DB/OIDC 정보가 제공된 뒤 실제 배포와 운영 검증을 진행합니다. 공개 합성 데모의 정적 호스팅은 부모 작업과 조정합니다.
