# macOS 설치와 검증

Apple Silicon arm64와 Intel x86_64를 각각 검증하는 CI를 제공합니다. 공개 저장소의 표준 `macos-15`·`macos-15-intel` runner를 사용하며 Python 3.11·3.14를 검사합니다. 실제 OS·architecture·Python·psutil 버전을 로그에 기록하고, 레이블과 다른 아키텍처면 실패합니다. 다른 macOS 버전과 실제 vendor 실행은 UNVERIFIED입니다. 정확한 commit의 CI가 성공한 범위만 지원 근거로 사용합니다.

Python 3.11 이상, Git, uv 0.11.11이 이미 준비된 터미널에서 저장소를 받습니다. 아래 설치는 저장소의 `.venv`에만 적용합니다.

```sh
git clone https://github.com/yjj3019/IntelligenceAI.git
cd IntelligenceAI
git switch feat/safe-controller
uv sync --frozen --extra dev
uv run --frozen intelligenceai capabilities
uv run --frozen intelligenceai --state-dir ../iai-state preview
```

현재 기능은 정적 검사 DAG와 고정 fixture 작성입니다. [샘플 계획](dag.md)은 최소 한 번 commit한 테스트용 Git 저장소에서 실행합니다. 상태 경로는 대상 저장소 밖에 둡니다. 기존 checkout의 미커밋 변경은 작업 공간으로 복사하지 않습니다. [MCP](mcp.md)는 같은 controller를 stdio로 실행하며 네트워크 포트를 열지 않습니다.

실제 secret 검사는 선택적으로 공식 Gitleaks 8.30.1 binary를 저장소 안에 받아 확인할 수 있습니다. arm64·x64 Darwin archive의 공식 SHA256을 고정 값과 release manifest에 모두 대조합니다. 기존 `.tools`나 목적 파일이 링크이면 설치를 거부합니다. 다운로드한 archive 전체를 추출하거나 설치 스크립트를 실행하지 않습니다.

```sh
uv run --frozen python scripts/fetch_gitleaks.py
export PATH="$PWD/.tools:$PATH"
uv run --frozen pytest -q
```

psutil 7.2.2는 Darwin에서만 설치합니다. 매번 새 Process로 birth identity를 읽고 PID·generation·process group을 확인한 뒤 종료합니다. group 열거의 권한 오류는 종료 성공으로 처리하지 않습니다. leader가 먼저 종료했지만 child가 살아 있으면 불명 상태로 남겨 자동 신호·재실행을 거부합니다. 빠르게 종료한 child와 identity 읽기 실패도 테스트합니다. `/var`·`/tmp` 별칭은 canonical root와 writer lease를 일치시키되 후보 파일의 symlink·hardlink는 계속 거부합니다.

이는 일반적인 자식 process group의 검증입니다. 새 session으로 탈출한 악성 process, 파일·네트워크 접근, credential 격리를 강제하는 OS sandbox가 아닙니다. vendor worker는 이러한 권한 경계를 확인할 때까지 비활성 상태입니다. Windows의 native process tree 종료는 UNVERIFIED입니다.

CI는 설치·CLI/DAG·실제 SDK stdio·프로세스 timeout/cancel·링크·실제 scanner·wheel build/install·격리 import·entry point를 검사합니다. 로컬 ARM/Intel 장치나 유료 vendor를 실제 사용했다는 뜻은 아닙니다. [runner 계약](https://docs.github.com/en/actions/reference/runners/github-hosted-runners), [psutil 계약](https://psutil.readthedocs.io/), [Gitleaks release](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1)를 기준으로 작성했습니다.

## English

Use already installed Python 3.11+, Git and uv 0.11.11; run the commands above in this repository. Standard public GitHub runners separately check Apple Silicon arm64 (`macos-15`) and Intel x86_64 (`macos-15-intel`) with Python 3.11 and 3.14, and assert their actual architecture. A passing run at the exact commit is the evidence; other OS/architecture versions and live providers remain UNVERIFIED.

Darwin supervision uses a fresh psutil 7.2.2 birth identity and verified process group. Enumeration denial is uncertainty, never an empty group. An exited leader with surviving children is not automatically signalled or replayed. Canonical macOS root aliases do not waive candidate symlink/hardlink checks. Ordinary group termination is not an OS sandbox or containment of escaped sessions. The official optional scanner stays repo-local with pinned Darwin hashes. CI also installs the built wheel and verifies isolated imports and CLI/MCP entry points. No vendor installation, account authentication or paid model call is performed.
