# GUI 실행·배포 안내

별도 [Claude 검토 worker](claude-transport.ko.md)는 실제 transport를 구현했지만
운영 배포와 유료 모델 실행은 아직 검증하지 않았다. 배포 입력은 기존
PostgreSQL·위임된 cgroup·고정 image·서명된 유료 승인·broker 전용 credential
fd다. credential이나 OS 설정을 새로 만들거나 바꾸지 않는다. 기존 fixture
worker와 유료 worker를 같은 실행 권한으로 취급하지 않는다.

공개 소개와 합성 데모는 backend 없이 배포할 수 있습니다. Private 콘솔은 실제 PostgreSQL·OIDC·HTTPS ingress가 필요합니다. 이번 구현에서는 서버 대상이나 외부 인증 정보가 제공되지 않았으므로 실제 private 배포와 해당 환경의 검증을 완료했다고 표시하지 않습니다.

## 공개 정적 산출물

Node 24와 저장소 전용 의존성을 사용합니다. 저장소 root에서 다음 순서로 준비합니다.

```sh
cd web
npm ci --ignore-scripts
npm run build:public
cd ..
uv run --frozen --extra web python scripts/pack_public_demo.py
```

폴더형 결과는 `web/dist-public/`, 단일 HTML은 `deliverables/public-demo.html`입니다. 단일 파일은 hash 탐색을 사용하므로 정적 iframe에서도 별도 서버 경로가 필요하지 않습니다. KO/EN 사전과 화면은 private build와 같은 소스를 사용합니다.

HTML의 CSP는 모든 network 연결을 차단합니다. 실제 로그인 대신 private 배포 미연결 안내를 표시하며 자격 증명을 수집하지 않습니다. 호스팅 플랫폼이 module script나 CSP를 지원하지 않으면 지원 여부를 먼저 확인합니다. 제한을 우회하거나 backend가 연결된 것처럼 표시하지 않습니다. 공개할 파일은 `public-demo.html` 하나입니다. 진행 메모나 테스트 산출물은 게시하지 않습니다.

로컬에서 공개 파일만 확인할 때는 아래와 같이 loopback에 한정합니다.

```sh
python -m http.server 4174 --bind 127.0.0.1 --directory deliverables
```

브라우저에서 `http://127.0.0.1:4174/public-demo.html`을 엽니다. 이 명령은 공개 서버 배포가 아닙니다. PC 포트를 외부에 개방하지 않습니다.

## Private 배포 준비

운영자는 기존 PostgreSQL DB, 검증할 OIDC issuer와 기존 client 등록, 공개 HTTPS origin, TLS ingress·인증서와 명시적인 proxy IP를 제공해야 합니다. 새 계정·유료 자원·credential·DNS·방화벽·터널은 이 안내가 자동으로 만들지 않습니다. 환경변수 이름은 `deploy/env.example`에 있으며 값은 저장소나 browser 입력에 넣지 않습니다.

| 이름 | 의미 |
| --- | --- |
| `IAI_DATABASE_URL` | 기존 `postgresql+psycopg://` DB 연결. 운영자 secret manager 사용 |
| `IAI_PUBLIC_ORIGIN` | path 없는 canonical HTTPS origin |
| `IAI_OIDC_ISSUER` | 기존 HTTPS OIDC issuer |
| `IAI_OIDC_CLIENT_ID` | 기존 client ID. callback은 `/auth/callback` |
| `IAI_OIDC_CLIENT_SECRET` | 기존 credential. server에만 주입 |
| `IAI_TRUSTED_PROXY_IPS` | 신뢰할 기존 ingress의 정확한 IP 목록. wildcard 금지 |
| `IAI_STATIC_DIR` | 운영자가 정한 frontend build 경로 |
| `IAI_LISTEN_HOST` | 기본 loopback. container 내부에서만 `0.0.0.0` 사용 |

준비된 DB에 최초 schema를 만들고, 이미 존재하는 OIDC subject를 프로젝트 소유자로 등록합니다. 초기화 도구는 기존 schema를 자동 migration하지 않습니다. 기존 설치에는 먼저 백업과 별도 migration 검토가 필요합니다.

```sh
uv sync --frozen --extra web
uv run --frozen --extra web python -m intelligenceai.web.manage init-db
uv run --frozen --extra web python -m intelligenceai.web.manage bootstrap --subject EXISTING_SUBJECT --name "Project owner" --project "Private project"
cd web
npm ci --ignore-scripts
npm run build
cd ..
uv run --frozen --extra web python -m intelligenceai.web.serve
```

server는 기본 `127.0.0.1:8080`에서 실행됩니다. 기존 ingress가 HTTPS를 종료하고 정확한 Host와 신뢰할 proxy IP를 전달해야 합니다. 실제 접속에서 Secure/HttpOnly/SameSite cookie, callback/state, 권한 회수와 교차 사용자 접근을 다시 검증합니다. 운영 ingress에 16 KiB body 제한, request timeout, rate limit을 적용하고 callback query·cookie·raw token을 access log에 남기지 않습니다. 실제 설정 변경은 배포 대상이 확인된 뒤 진행합니다.

`deploy/Dockerfile`과 `deploy/compose.yml`은 Linux 배포용 준비 산출물입니다. 외부 DB/기존 OIDC만 참조하고 host port는 loopback에 한정합니다. 비특권 user, read-only filesystem, capability 제거와 resource limit을 정의했지만 실제 container build·TLS ingress·서버 운영은 아직 검증하지 않았습니다. 현재 runtime image는 초기 버전 tag로 고정했으며 실제 운영 전 승인한 immutable image digest와 취약점 검사를 확정해야 합니다.

Private 콘솔에 작업을 저장하면 `BLOCKED`와 `HELD`로 기록됩니다. API에서 임의 저장소 코드나 vendor CLI를 실행하지 않습니다. 별도 supervisor는 운영자 권한과 명시적인 실행 요청이 있는 고정 fixture만 처리합니다. `IAI_RUNNER_DATABASE_URL`과 `IAI_RUNNER_STATE_DIR`는 supervisor에만 설정하며 실행 subprocess에 상속하지 않습니다. 기존 DB에는 additive table 3개만 추가합니다. [runner 운영 계약](web-runner.md)에 초기화·만료 권한·단일 실행·receipt 복구 명령과 최소 DB 권한이 있습니다. paid 모델·게시·push·merge·deploy는 항상 비활성이고 OS 격리는 미검증입니다. 배포 정보만 제공해도 이 기능들은 자동 활성화되지 않습니다. 이번 후속 작업은 최종 배포를 제외합니다.

## 공개 정적 Sites 배포

[공개 소개·데모](https://intelligenceai.violet-pixie-4145.chatgpt.site)는 사용자 승인을 받은 새 Sites 프로젝트 하나에 배포했습니다. 접근 모드는 `public`이며 최신 버전 2의 배포 결과는 `succeeded`입니다. [배포 기록](../deploy/public-site.json)에 project/version/deployment ID와 소스 commit을 보존합니다. 이후 수정에서는 이 project ID를 재사용하고 새 Site를 중복 생성하지 않습니다.

GUI의 공개 빌드를 단일 `dist/index.html`로 복사한 전용 Site checkout을 사용했습니다. 공식 `site-workflow.mjs`의 숨겨진 stdin으로 메모리의 단기 소스 자격 증명을 전달하고, 정확한 소스를 push한 뒤 두 파일만 포함한 archive를 저장·배포했습니다. 자격 증명은 argv·파일·로그에 저장하지 않았으며 Git 작성자는 일반 Sites 이름을 사용했습니다. Windows에서는 이미 설치된 Git Bash를 해당 프로세스의 PATH에 앞세우고 GNU tar의 `TAR_OPTIONS=--force-local`로 드라이브 문자를 로컬 경로로 처리했습니다. 전역 설정, WSL·브라우저 설치, 포트 개방이나 터널은 사용하지 않았습니다.

이 정적 호스팅은 Python API·PostgreSQL·OIDC·Linux 실행기를 대체하지 않습니다. 공개 페이지의 private 링크는 환경 미연결 안내를 표시하며 자격 증명을 받지 않습니다. CSP는 모든 API 연결과 form 제출을 차단합니다. 실제 private 콘솔의 배포는 위 운영 연결 정보가 제공된 후 진행합니다.

## 독립 로컬 검증

```sh
uv sync --frozen --extra dev --extra web
uv run --frozen --extra web --extra dev pytest tests/test_web.py -q
cd web
npm run lint
npm run typecheck
npm test
npm run build
npm run build:public
cd ..
uv run --frozen --extra web python tests/support/web_fixture.py
```

마지막 명령은 `127.0.0.1:4173` 전용 테스트 서버입니다. 실행마다 임시 SQLite와 테스트 사용자, 임시 서명 키를 만들며 인증 우회 endpoint를 제공하지 않습니다. 실제 Authlib client가 합성 issuer의 state·nonce·PKCE·JWT를 검사합니다. 이 fixture는 실제 OIDC/DB 운영 증거가 아니며 배포 image에 포함하지 않습니다. 지원된 전용 테스트 브라우저만 사용합니다. Chromium 설치나 보안 우회가 필요하면 진행하지 않고 차단 사항을 보고합니다.

현재 결과와 남은 검증 항목은 [검증 기록](web-validation.md), 서비스 관계는 [웹 구조](web-architecture.md), API는 [계약 문서](web-api.md), 위협 경계는 [보안 문서](web-security.md)에 있습니다.


## Provider backend readiness

This release does not provide a live runner image or an enable-provider setting.
The internal [Linux executor](provider-isolation.md) is an offline probe only.
Installing bubblewrap or passing that probe does not authorize paid models or a
production deployment. Before live rollout, independently verify credentials,
provider-only egress, budgets, immutable materialization and OS/provider/mode
capabilities. CI package installation is limited to its ephemeral Linux test job;
user-PC packages, AppArmor/sysctl changes and privileged fallback are excluded.

승인된 fake 프로세스 경로는 같은 DB의 additive invocation table을 사용합니다. 기존 운영자 설정 `IAI_RUNNER_DATABASE_URL`, `IAI_RUNNER_STATE_DIR`로 별도 `python -m intelligenceai.web.vendor_runner --once`를 실행합니다. 필요한 세션·승인 읽기 권한과 crash/reconcile 조건은 [합성 vendor 실행 계약](web-approved-vendor.md)에 정리했습니다. 새 credential이나 실제 모델 권한을 만들지 않으며 유료 실행은 계속 비활성입니다. 루프백 테스트 fixture에는 이 runner가 포함되지만 운영 image에 테스트 issuer를 포함하지 않습니다.
