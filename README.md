# IntelligenceAI

승인된 고정 fake 프로세스의 DB 일회성 예약·실행 직전 권한 검사·private 결과·취소/복구 경로는 [합성 vendor 실행 계약](docs/web-approved-vendor.md)에 정리했습니다. 모델 호출은 0회이며 실제 provider와 OS 격리는 미검증입니다.

Provider 격리 후속 구현으로 [내부 실행 계약과 Linux 오프라인 probe](docs/provider-isolation.ko.md)를 추가했습니다. 연결 화면에서 OS·provider·실행 모드별 차단 사유를 확인할 수 있습니다. 실제 provider·유료 모델은 계속 비활성화하며 오프라인 격리 검사를 실제 모델 실행 성공으로 계산하지 않습니다.

[실제 모델 실행 권한의 서명 계약](docs/live-authority-ko.md)은 승인과 manifest에 결합된 증거 6개의 서명·역할·만료를 검증합니다. 정상 증거도 서명 검증 결과만 반환하며 실행은 `BLOCKED`, 모델은 `NOTRUN`을 유지합니다. 실제 broker·egress·자원·비용 통제와 일회성 실행 예약은 후속 구현·운영 검증이 필요합니다.

[English guide](README.en.md) · [구조와 상태](docs/architecture.md) · [보안 한계](SECURITY.md) · [설계 대조표](docs/requirements.md)

IntelligenceAI는 AI 작업의 실행 상태와 변경 후보, 검사 근거, 승인을 연결하는 로컬 제어 프로젝트입니다. LangGraph가 작업 흐름을 저장하고 별도 SQLite 실행 원장이 실제 호출의 시작·결과를 기록합니다. Git 작업 공간과 후보 digest를 사용해 사용자 변경을 보존하고, 확인한 후보에 대해서만 승인을 판단합니다.

현재 실행 가능한 범위는 비용이 발생하지 않는 정적 검사 DAG와 결정적 fixture 작성입니다. Claude·Codex·Grok·Gemini CLI·Antigravity와 Omnilane·MCO·PAL의 실제 연결은 권한 강제를 확인할 때까지 비활성화했습니다. 범용 AI 제품을 위한 초기 기반이며, 실제 모델로 임의의 개발 요청을 처리하는 완성 제품은 아닙니다. Meta AI는 이번 범위에서 제외했습니다.

## 웹 GUI

공개 소개·문서와 합성 읽기 전용 데모, 로그인한 사용자의 private 프로젝트 콘솔을 추가했습니다. 대시보드, 프로젝트·구성원, 새 작업·계획 미리보기, 작업 상세·단계, 후보 diff·검사, 승인·복구, 연결·실행환경, 감사 화면을 제공합니다. 상단 KO/EN 전환은 선택한 언어만 저장하며 날짜·시간대는 브라우저 설정을 따릅니다.

공개 데모에는 실제 작업·로그인이 없습니다. private API는 별도의 PostgreSQL 원장과 OIDC 서버 세션을 사용하고 객체별 프로젝트 권한을 확인합니다. 제출 작업은 HELD 대기에 기록됩니다. 운영자가 만료되는 프로젝트 실행 권한을 설정한 뒤 사용자가 직접 요청하면 [고정 fixture supervisor](docs/web-runner.md)가 실제 core DAG를 실행합니다. 후보는 합성 데이터이며 검사는 정적 파서만 사용합니다. 유료 모델·외부 효과는 비활성이고 OS 격리는 미검증 상태입니다. task·generation별 core 저장소를 분리하며 로컬 CLI의 공유 SQLite와 파일 잠금을 HTTP로 노출하지 않습니다.

완료한 GUI 범위는 고정 fixture의 제출·대기열·core DAG 실행·정적 결과·승인·취소·복구 연결입니다. 임의 저장소 코드·shell·vendor CLI 실행은 제공하지 않습니다. 운영 인증·DB·TLS 검증과 최신 supervisor UI의 실제 브라우저 QA는 미완료이며, 전체 AI 제품의 완성을 뜻하지 않습니다. 검증 근거와 NOTRUN 항목은 [검증 기록](docs/web-validation.md)에 구분했습니다.

[공개 소개·KO/EN 데모](https://intelligenceai.violet-pixie-4145.chatgpt.site)를 Sites에 배포했습니다. 합성 데이터만 표시하는 정적 사이트이며 로그인이나 프로젝트 쓰기 API는 없습니다. 배포 ID와 소스는 [공개 배포 기록](deploy/public-site.json)에 보존합니다.

[웹 구조](docs/web-architecture.md) · [API 계약](docs/web-api.md) · [웹 보안](docs/web-security.md) · [배포 절차](docs/web-deployment.md) · [검증 기록](docs/web-validation.md)

```powershell
uv sync --frozen --extra web --extra dev
cd web
npm ci --ignore-scripts
npm run build
npm run build:public
cd ..
uv run --frozen --extra web python scripts/pack_public_demo.py
```

공개 배포용 산출물은 `deliverables/public-demo.html`입니다. private 운영에는 기존 Linux 실행 대상, PostgreSQL 연결과 OIDC 등록, HTTPS origin이 필요합니다. 배포 대상이 제공되기 전에는 실제 공개 서버를 실행하지 않습니다. Docker·Compose 파일은 준비된 배포 레시피이며 실제 대상에서의 실행 검증은 남아 있습니다.

## 설치

같은 controller를 사용하는 [로컬 stdio MCP](docs/mcp.md)를 제공합니다. 여섯 tool만 노출하며 모델에 승인·외부 공개 기능을 주지 않습니다. 포트 개방이나 앱 등록 없이 SDK client로 검증합니다.

버전별 argv·stdin·결과 parser와 lifecycle 계약은 [오프라인 adapter 문서](docs/protocols.md)에 있습니다. 테스트 소유 fake transport로 검사하며 실제 dispatch는 항상 차단합니다. 공개 입력으로 fake transport나 live gate를 선택할 수 없습니다.

Python 3.11 이상, Git, 이미 설치한 uv가 필요합니다. 이 저장소에서 실행합니다.

```powershell
uv sync --frozen --extra dev
.venv\Scripts\intelligenceai.exe capabilities
```

Linux·macOS에서는 `uv run --frozen intelligenceai capabilities`를 사용합니다. 의존성은 저장소 전용 `.venv`에 설치합니다. 버전·배포 파일 hash는 `uv.lock`, 출처·라이선스·선택 도구는 [도입 기록](docs/dependencies.md)에 정리했습니다. vendor 도구 설치나 인증, 전역 설정 변경은 하지 않습니다.

## 하나의 작업 실행

여러 step을 실행하는 [DAG·정적 검사 안내](docs/dag.md)와 Python/JSON 샘플 계획을 제공합니다. 실제 파일 존재·JSON·AST 검사는 사용자 코드를 실행하지 않습니다. 정적 검토는 고정 후보 바이트를 사용하고 writer는 직렬화합니다. fixture profile은 controller와 분리돼 있습니다.

최소 한 개의 커밋이 있는 테스트용 Git 저장소를 준비합니다. 상태 폴더는 대상 저장소 밖에 둡니다. controller는 커밋된 HEAD에서 detached worktree를 만들며, 원래 checkout의 미커밋 변경을 복사하거나 초기화하지 않습니다.

```powershell
.venv\Scripts\intelligenceai.exe --state-dir ..\iai-state preview
.venv\Scripts\intelligenceai.exe --state-dir ..\iai-state submit --repo C:\path\to\fixture-repo --request "fixture 흐름 확인" --scenario repair --run
.venv\Scripts\intelligenceai.exe --state-dir ..\iai-state status TASK_ID
.venv\Scripts\intelligenceai.exe --state-dir ..\iai-state results TASK_ID
```

`TASK_ID`는 submit 결과의 작업 ID로 바꿉니다. `success`는 `answer.py`에 `ANSWER = 42`를 작성합니다. `repair`는 잘못된 값 41을 재현한 뒤 한 번 수리하고, `exhaust`는 수리 한도를 확인합니다. 대상 코드를 실행하지 않고 Python AST를 검사합니다. fixture 리뷰는 결정적 검사이며 실제 MCO 독립 리뷰가 아닙니다.

Gitleaks 8.30.1과 Linux/macOS 프로세스 감독을 확인하지 못한 환경에서는 fixture 검사가 통과해도 `UNVERIFIED`로 남습니다. Windows의 프로세스 트리 종료 경로는 비활성 상태입니다. 테스트용 scanner 주입을 실제 시크릿 검사나 OS 격리의 증거로 사용하지 않습니다.

## 승인·취소·복구

```powershell
.venv\Scripts\intelligenceai.exe --state-dir ..\iai-state approve TASK_ID --action push --destination example.invalid/repo --ttl 900
.venv\Scripts\intelligenceai.exe --state-dir ..\iai-state dry-run TASK_ID --action push --destination example.invalid/repo
.venv\Scripts\intelligenceai.exe --state-dir ..\iai-state reject TASK_ID
.venv\Scripts\intelligenceai.exe --state-dir ..\iai-state cancel TASK_ID
.venv\Scripts\intelligenceai.exe --state-dir ..\iai-state recover TASK_ID
```

필수 검사가 실패하거나 빠지면 approve를 거부합니다. 승인은 repo·base, 후보 파일과 untracked/ignored 파일, 범위, 목적지·동작·인자, 정책, generation, 검사 근거와 만료 시간을 묶습니다. 후보가 달라지면 기존 근거와 승인을 무효화합니다. 이 버전의 외부 동작은 항상 비활성 상태이며 승인된 dry-run도 실행 횟수 0을 반환합니다.

재시작한 작업은 실행 원장을 먼저 대조합니다. 예약만 한 호출은 진행할 수 있지만 시작 여부가 불명인 호출은 `NEEDS_RECONCILIATION`으로 두고 writer 소유권을 유지합니다. 상태 DB나 writer 기록을 삭제해 재실행을 강제하지 않습니다. 실제 작업 대조가 검증되지 않아 강제 복구 명령은 제공하지 않습니다.

로컬 CLI는 단일 사용자의 승인 채널입니다. worker에게 승인 API나 정책 변경 권한을 제공하지 않습니다. worktree는 파일 충돌을 줄이는 장치이며 OS sandbox가 아닙니다. 같은 OS 권한을 가진 악성 프로세스로부터 controller를 보호했다고 주장하지 않습니다. [보안 문서](SECURITY.md)에 적용 조건과 남은 한계를 정리했습니다.

## 검증과 다음 단계

```powershell
uv run --frozen pytest -q
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
```

fixture 수직 흐름, 계획·경로 계약, 승인 변경, crash·재시작, 시크릿 마스킹, Linux/macOS 자식 프로세스 종료와 MCP SDK stdio 연결를 테스트합니다. 실제 vendor E2E, 모델 선택, API 연결, Windows/WSL 격리와 성능·비용은 별도 `UNVERIFIED`입니다. 외부 작업의 exactly-once 실행이나 측정하지 않은 품질·속도 향상을 보장하지 않습니다.

실제 연결을 열기 전에는 고정 버전별 caller·프로세스·모델 확인과 OS 권한 경계를 검증해야 합니다. 웹 상태 화면은 별도의 private 원장에 연결했습니다. 임의 프로젝트의 테스트 실행과 실제 production 배포 검증은 남아 있습니다. Apple Silicon·Intel 설치와 정확한 CI 검증 범위는 [macOS 안내](docs/macos.md)에 정리했습니다.

