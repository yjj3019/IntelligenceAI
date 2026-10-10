# 독립 검토 수정

검토 기준 head는 `0281b498e99e4c64795dc265a732d1e51e0b2209`입니다. 여섯 결함을 기존 자체 소스와 생성한 임시 파일로 재현했습니다. 실제 vendor 호출이나 사용자 파일, 인증·OS 설정은 사용하지 않았습니다. 기존 검증 통과가 이 결함들의 부재를 증명하지 않았음을 기록합니다.

| 결함 | 이전 동작 재현 | 수정과 회귀 |
|---|---|---|
| agy discriminator | 공식 event stream 거부, Gemini type 형식 수용 | executor별 event/type 구분, 다른 discriminator 혼용 거부, 공식 형식 정상 fixture |
| implement/read_only | 입력 수용 후 writer lease 없이 파일 작성 가능 | Step role/mode 일치 검사, model_copy도 submit·authorize에서 재검증, 실제 쓰기 함수의 lease 확인 |
| repair checkpoint 경계 | 같은 논리 repair를 replay하면 예산 두 번 차감 | candidate·generation·round·finding·policy로 operation ID 구성, 원장 decision 재사용, commit 후 checkpoint 전 crash 테스트 |
| state/cancel 경합 | READY 조회 직후 cancel commit 뒤 RUNNING으로 덮어쓰기 | BEGIN IMMEDIATE 상태 전이, expected generation, 두 DB 연결 barrier와 stale 예약 거부 |
| 후보 ValueError | 승인 후 unsafe 경로 검사 실패가 승인 삭제를 건너뜀 | SafetyError/ValueError/OSError 모두 승인 삭제·영구 BLOCKED, Linux NUL 추가 후 제거해도 승인 재사용 거부 |
| 링크 쓰기 | hardlink 외부 inode 변경, dangling symlink는 exists 검사 우회 | lstat 종류·link count 검사, 새 임시 inode 작성 후 os.replace, 외부 생성/변경 0회 및 교체 경합 fixture |

상태 전이와 실제 fixture 쓰기는 generation을 확인합니다. fixture 쓰기의 writer lease 확인부터 원자 교체까지 SQLite 트랜잭션을 유지해 cancel commit이 그 경계에 끼어들지 못하게 합니다. 이는 신뢰한 로컬 fixture의 애플리케이션 경계이며 OS sandbox 보장은 아닙니다.

repair decision·예산 차감·실패 원인 횟수·승인 삭제·상태 변경은 한 트랜잭션에 저장합니다. replay는 동일 operation ID의 결정을 읽습니다. 서로 다른 논리 수리는 별도 ID로 예산을 차감하며, 동일 ID에 다른 서명을 넣으면 거부합니다. generation 없는 이전 체크포인트는 자동 실행하지 않습니다.

정상 agy fixture는 [공식 headless 문서](https://antigravity.google/docs/cli/headless/)의 event/init/step_update/result 형태를 사용합니다. Gemini의 type 형식과 섞지 않습니다. 파서는 여전히 terminal frame 구조 확인 수준이며 전체 live adapter나 모델·권한 검증으로 확대하지 않습니다.

`tests/test_review_regressions.py`가 수정된 항목의 회귀를 담당합니다. Windows의 NUL 경로와 symlink 권한 부재는 명시적으로 skip하며 Linux CI에서 실제 파일 fixture를 검사합니다. hardlink 검사는 Windows에서도 실행합니다. 기존 live 경로는 계속 비활성·UNVERIFIED이며 외부 동작은 dry-run만 제공합니다.

