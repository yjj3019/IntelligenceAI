# IntelligenceAI

[English guide](README.en.md) · [구조와 상태](docs/architecture.md) · [보안 한계](SECURITY.md) · [설계 대조표](docs/requirements.md)

IntelligenceAI는 AI 작업의 실행 상태와 변경 후보, 검사 근거, 승인을 연결하는 로컬 제어 프로젝트입니다. LangGraph가 작업 흐름을 저장하고 별도 SQLite 실행 원장이 실제 호출의 시작·결과를 기록합니다. Git 작업 공간과 후보 digest를 사용해 사용자 변경을 보존하고, 확인한 후보에 대해서만 승인을 판단합니다.

현재 실행 가능한 범위는 비용이 발생하지 않는 결정적 fixture입니다. Claude·Codex·Grok·Gemini CLI·Antigravity와 Omnilane·MCO·PAL의 실제 연결은 권한 강제를 확인할 때까지 비활성화했습니다. 범용 AI 제품을 위한 초기 기반이며, 실제 모델로 임의의 개발 요청을 처리하는 완성 제품은 아닙니다. Meta AI는 이번 범위에서 제외했습니다.

## 설치

같은 controller를 사용하는 [로컬 stdio MCP](docs/mcp.md)를 제공합니다. 여섯 tool만 노출하며 모델에 승인·외부 공개 기능을 주지 않습니다. 포트 개방이나 앱 등록 없이 SDK client로 검증합니다.

버전별 argv·stdin·결과 parser와 lifecycle 계약은 [오프라인 adapter 문서](docs/protocols.md)에 있습니다. 테스트 소유 fake transport로 검사하며 실제 dispatch는 항상 차단합니다. 공개 입력으로 fake transport나 live gate를 선택할 수 없습니다.

Python 3.11 이상, Git, 이미 설치한 uv가 필요합니다. 이 저장소에서 실행합니다.

```powershell
uv sync --frozen --extra dev
.venv\Scripts\intelligenceai.exe capabilities
```

Linux에서는 `uv run --frozen intelligenceai capabilities`를 사용합니다. 의존성은 저장소 전용 `.venv`에 설치합니다. 버전·배포 파일 hash는 `uv.lock`, 출처·라이선스·선택 도구는 [도입 기록](docs/dependencies.md)에 정리했습니다. vendor 도구 설치나 인증, 전역 설정 변경은 하지 않습니다.

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

Gitleaks 8.30.1과 Linux 프로세스 감독을 확인하지 못한 환경에서는 fixture 검사가 통과해도 `UNVERIFIED`로 남습니다. Windows의 프로세스 트리 종료 경로는 비활성 상태입니다. 테스트용 scanner 주입을 실제 시크릿 검사나 OS 격리의 증거로 사용하지 않습니다.

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

fixture 수직 흐름, 계획·경로 계약, 승인 변경, crash·재시작, 시크릿 마스킹, Linux 자식 프로세스 종료를 테스트합니다. 실제 vendor E2E, 모델 선택, API 연결, Windows/WSL 격리와 성능·비용은 별도 `UNVERIFIED`입니다. 외부 작업의 exactly-once 실행이나 측정하지 않은 품질·속도 향상을 보장하지 않습니다.

실제 연결을 열기 전에는 고정 버전별 caller·프로세스·모델 확인과 OS 권한 경계를 검증해야 합니다. MCP와 상태 화면, 임의 프로젝트의 테스트 실행, production 배포는 이후 범위입니다.

