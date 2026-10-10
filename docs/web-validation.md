# 웹 GUI 검증 기록

## 최종 검토 수정

완료 후 취소와 취소 후 완료는 현재 generation의 검증된 정적 receipt와 lease 종료를 근거로 `CANCELLED`에 수렴합니다. 완료 proof가 없는 `FINISHED`는 취소 완료로 과장하지 않고 거부합니다. 미시작 receipt는 별도 `kind: never_started`로 조회·표시하며 steps를 읽지 않습니다. SSE의 artifact ID·digest·generation 변경은 후보 본문을 무효화하고 지연된 이전 응답을 폐기합니다. 만료·정책 불일치 권한의 100개 작업 뒤에 있는 정상 프로젝트를 같은 claim 호출에서 찾도록 keyset 페이지를 순회합니다.

수정된 frontend는 component/locale/API mock 회귀 32개, lint, typecheck, private/public build를 통과했습니다. 실제 core fixture 완료→취소→복구 2개 profile, 미시작 receipt 및 큐 진행 회귀는 로컬에서 통과했습니다. 이 검증은 실제 모델 실행 또는 OS sandbox 성공을 뜻하지 않습니다. 새 supervisor UI의 지원 브라우저 도구는 현재 없어 실제 브라우저 검증은 NOTRUN입니다. 최종 커밋의 PostgreSQL 별도 pool 완료/취소 경합과 기존 8환경 core matrix 결과는 draft PR의 해당 head SHA CI에서 확인합니다. 최종 배포는 사용자 요청에 따라 제외했습니다.

2026-10-10, Windows의 GUI 전용 checkout에서 Python 3.11.15(win-amd64)·Node 24.15.0(x64)로 확인했습니다. 이 기록은 로컬 검증과 실제 운영 연결을 구분합니다. 합성 데이터만 포함한 정적 Sites 공개 배포를 완료했습니다. private 서버·DB·OIDC 등록은 생성하지 않았으며 유료 모델과 외부 효과를 실행하지 않았습니다.

| 검사 | 로컬 결과 | 범위 |
|---|---|---|
| backend 웹 회귀 | 44 passed, 1 skipped | SQLite fixture, 객체별 인가, CSRF/Host/Origin, 공격 입력, 세션, 중복·취소·복구·승인 binding, receipt GET의 SQL 쓰기 0회·actor/task/권한 재검사; 실제 PostgreSQL 동시성 테스트는 로컬 skip |
| 서명된 OIDC 회귀 | 위 44개에 포함 | 실제 Authlib 검증 경로 + 오프라인 서명 issuer; nonce/audience/issuer/expiry/서명/미등록 사용자 거부 |
| frontend 회귀 | 26 passed | 8개 화면, 공개·private 경계, 취소 대상 고정·뒤로가기·다른 작업 이동·중복 확인, 자동 재접속 권한회수, 승인 payload/key/expiry 보존·읽기 전용 receipt 조회·명시 재전송, 로그아웃 후 지연 GET·mutation 차단, 안전한 KO/EN 오류 안내 |
| frontend lint / typecheck | 통과 | ESLint 및 strict TypeScript |
| 일반·공개 frontend build | 통과 | `dist` 및 별도 `dist-public` |
| Python lint / format | 통과 | 전체 `src tests scripts` |
| npm audit | 0 vulnerabilities | 고정 lock 설치 시점의 조회 결과 |
| 공개 단일 HTML | 생성 | 자체 JS/CSS, hash navigation, CSP connect-src none |
| 정확한 release blob 비밀 검사 | 0 findings | 공식 SHA256 검증 Gitleaks 8.30.1, 원문 보고서는 보관하지 않음 |
| 기존 core 로컬 회귀 | 171 passed, 12 skipped | 개발 중 전체 pytest의 core 항목; 후속 웹 검사는 위 결과로 별도 재실행 |
| 기존 core 8환경 CI + 웹 CI | 9개 job 모두 성공 | [P2 수정 commit d146775 검증](https://github.com/yjj3019/IntelligenceAI/actions/runs/38046454197), Ubuntu/Windows/macOS arm64·Intel × Python 3.11·3.14 |
| 실제 임시 PostgreSQL CI | 45 passed | 프로젝트 인가·승인·중복·취소·복구·읽기 전용 receipt 및 8개 동시 제출·별도 pool 재연결 |

지원되는 전용 Chrome 테스트 탭에서 공개 데모의 모바일 390px, KO/EN 전환, 새로고침·뒤로가기·직접 링크, 키보드 계획 미리보기·메뉴 Escape와 후보 diff를 확인했습니다. 최종 공개 빌드의 8개 모바일 화면에서 document 너비가 viewport를 넘지 않았으며 콘솔 warning/error가 없었습니다. locale 시간대는 실제 브라우저의 Asia/Seoul로 표시되었습니다.

전용 loopback fullstack에서는 합성 서명 issuer와 실제 Authlib callback을 거쳐 LOCAL TEST USER로 로그인하고, private 계획 미리보기·HELD 제출·취소 확인 대화상자·never-started 취소 확인 완료·복구 generation 증가·불확실한 lease의 복구 차단·로그아웃 데이터 제거를 검증했습니다. 이 검증은 실제 외부 issuer나 운영 PostgreSQL 연결 증거가 아닙니다. 브라우저 설치나 보안 우회는 하지 않았습니다.

독립 리뷰 후 추가한 회귀 9개는 수정 전 `eb72aa5` 소스에서 모두 실패했고, 수정 후 기존 16개와 함께 25개가 통과했습니다. 테스트는 실제 모델 성공을 만들지 않는 fetch mock과 합성 검증 evidence를 사용합니다. 승인 의도는 사용자가 준비할 때 한 번 고정하며, 응답 유실 후 명시적인 재전송만 동일 payload와 key로 POST합니다. receipt 조회는 쓰기 없는 GET으로 별도 처리합니다. 새로운 승인은 별도 의도를 준비해야 합니다. 로그아웃·권한회수·다른 사용자 및 경로 전환은 요청 epoch를 갱신해 오래된 응답의 데이터·오류·피드백 적용을 차단합니다.

후속 리뷰의 receipt 조회 P2에는 회귀 1개를 더 추가했습니다. 이 테스트는 수정 전 `f826d10`에서 실패하고 수정 후 통과했습니다. 승인 준비 후 조회·새로고침의 승인 POST는 0회이고, 응답 유실 상태의 반복 조회에도 추가 POST는 0회입니다. "동일 승인 요청 다시 전송"만 이전 payload/key를 재사용합니다. backend에서는 SQL 이벤트와 원장 snapshot을 함께 비교해 receipt가 없거나 만료된 기존 receipt를 여러 번 조회해도 INSERT/UPDATE/DELETE가 0회임을 확인했습니다. 다른 사용자·프로젝트·작업, viewer, 권한 회수와 만료 세션도 검사합니다.

[실제 공개 Sites URL](https://intelligenceai.violet-pixie-4145.chatgpt.site)에서 지원되는 전용 Chrome으로 KO/EN 각각 8개 화면을 390×844 viewport에서 확인했습니다. 모든 화면의 document 너비가 viewport 이내였고, 읽기 전용 합성 안내·모델 호출 0·승인 비활성·언어 보존·reload·Back/Forward·메뉴 Enter/Escape·문서 링크·private 미연결 안내를 확인했습니다. P2 수정 빌드를 기존 Site의 버전 2로 갱신한 후에도 KO/EN 16개 모바일 화면과 private 미연결 안내를 다시 확인했습니다. 테스트 탭의 warning/error는 0개였으며 임시 viewport는 복원했습니다. Sites API의 접근 모드는 `public`, 최신 버전 2의 배포 상태는 `succeeded`입니다.

Cookie·Authorization 없이 일반 HTML User-Agent로 보낸 독립 HTTP 요청도 로그인 리디렉션 없이 200을 반환했습니다. HTML parser의 줄바꿈 정규화 후 애플리케이션 JS·CSS와 CSP가 공개 빌드와 일치했습니다. Sites가 자체 bootstrap script 하나를 추가하므로 전체 응답 바이트가 원본 HTML과 같다고 주장하지 않습니다. 기본 Python User-Agent 요청은 호스팅 측에서 403으로 거부됐습니다.

## 실제 운영에서 남은 검증

실제 PostgreSQL은 로컬에 제공되지 않았습니다. 별도 CI의 임시 PostgreSQL 17.6에서 웹 계약 45개가 통과했습니다. 8개 동시 요청의 단일 task/job/receipt, 별도 pool 재연결 및 receipt 조회의 SQL 쓰기 0회도 포함합니다. 기존 8개 OS·Python core matrix를 유지했고 모든 job이 성공했습니다. 검사에 사용하는 합성 토큰은 런타임에서 구성하며 비밀 검사 정책이나 ignore는 완화하지 않았습니다.

CI의 임시 DB 검증은 운영 DB의 장애 재시작·backup 검증이 아닙니다. 실제 OIDC 등록, HTTPS ingress의 Secure cookie, 운영 권한회수, DB backup/암호화, 프록시·rate limit·접근 로그, 컨테이너와 Linux runner 격리는 확인하지 못했습니다. runner는 고정 fixture와 정적 검사로 제한되며 실제 모델·외부 dispatch를 거부합니다.

운영 배포에 필요한 값의 이름과 초기화 순서는 [배포 절차](web-deployment.md)에 있습니다. 사용자 또는 부모 작업이 승인한 공개 Linux 대상·기존 DB/OIDC 정보가 제공된 뒤 실제 private 배포와 운영 검증을 진행합니다. 공개 합성 데모의 정적 호스팅은 별도로 완료했습니다.


## 고정 fixture supervisor 후속 검증

후속 구현은 HELD 원장과 실제 core DAG의 고정 fixture 실행을 연결합니다. 임의 저장소 코드·shell·vendor CLI·유료 모델·외부 효과는 허용하지 않습니다. 후보는 합성 데이터이며 정적 parser의 PASS를 실제 모델 성공이나 OS 격리 검증으로 표시하지 않습니다. 실제 모델은 NOTRUN, OS 격리와 core secret scanner는 UNVERIFIED입니다. 운영 DB/OIDC/TLS나 최종 배포를 수행하지 않았습니다.

검토 후보 `16eccfa2817311d9bbb5f782dc9ecc25bf62f760`에서 push CI [38055210689](https://github.com/yjj3019/IntelligenceAI/actions/runs/38055210689)와 PR CI [38055213292](https://github.com/yjj3019/IntelligenceAI/actions/runs/38055213292)의 9개 job이 각각 통과했습니다. 실제 임시 PostgreSQL은 59 passed, SQLite는 55 passed·4 skipped, signed loopback HTTP/OIDC/API/supervisor는 1 passed입니다. frontend lint·typecheck·28 tests·private/public build가 통과했고, 정확한 release blob 115개의 Gitleaks 결과는 0건입니다. 이 수치는 해당 검토 후보의 결과입니다.

후보 이후에는 실제 subprocess 생성도 project 잠금 아래 두고 role·capability·generation·lease·취소를 다시 확인합니다. 이 보완의 로컬 집중 회귀 6개와 signed loopback fullstack 1개가 통과했습니다. GET/status/SSE/로그/Refresh에서 SQL INSERT·UPDATE·DELETE가 0회임을 검사합니다. 실제 PostgreSQL의 별도 connection pool로 claim 경쟁·claim/cancel·claim/revocation과 launch/revocation 경계를 시험합니다. launch 경계의 probe는 잠금 순서를 관찰하는 테스트용 marker이며 provider receipt나 모델 실행 성공으로 사용하지 않습니다. 최신 최종 commit의 결과는 draft PR과 해당 SHA의 CI를 기준으로 확인합니다.

로컬 Windows의 깊은 테스트 경로에서는 Git이 `fatal: '$GIT_DIR' too big`을 반환했습니다. 전역 설정을 바꾸지 않고 저장소 내부의 짧은 전용 fixture 경로를 사용했으며 runner는 과도하게 긴 Windows state root를 시작 전에 거부합니다. 실제 subprocess 회귀는 로컬에서 수분이 걸렸지만 동일 검토 후보의 CI web 회귀는 PostgreSQL 21.57초, SQLite 17.96초, loopback fullstack 2.51초로 종료됐습니다. 각 subprocess의 90초 deadline과 owned-child cleanup이 있으며 timeout은 종료 확인으로 과장하지 않습니다.

이번 후속 변경은 지원 테스트 브라우저 도구가 노출되지 않아 실제 브라우저의 모바일·키보드·취소/재시작 재검증은 NOTRUN입니다. 기존 GUI의 브라우저 검증과 새 component/HTTP fullstack 검증을 구분합니다. 브라우저를 설치하거나 보안 설정을 우회하지 않았습니다. 공개 Sites 배포는 이전 버전을 유지하며 이번 최종 배포는 제외했습니다.
