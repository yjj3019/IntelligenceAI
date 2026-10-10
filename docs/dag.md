# 다단계 계획과 정적 검사

Plan은 최대 16개의 typed Step과 명시적 dependency를 받습니다. 순서와 관계없이 DAG를 검증하며 순환·없는 dependency·중복 ID·범위 밖 checker·dependency가 아닌 result_ref는 거부합니다. 실행기는 step별 round·generation·상태·candidate ID·result ID·참조를 SQLite step_runs에 기록합니다. graph 위치와 달리 이 기록이 완료된 step의 재실행을 막습니다.

ready writer는 한 번에 하나만 실행합니다. fixture 모델 호출 예산은 전체 작업에 공유되며 최대 3회입니다. 정적 parser는 모델 호출이 아니므로 별도 step receipt를 기록합니다. writer 이후 ready read-only step은 같은 후보 바이트를 최대 3개 thread로 검사합니다. 검토가 끝나면 후보를 다시 동결해 변화를 확인합니다. 실패·미검증 dependency의 후속 step은 BLOCKED로 남습니다. 이전 후보의 evidence는 새 후보의 승인 근거로 사용하지 않습니다.

file_exists는 파일 유무, json_shape는 object key와 엄격한 literal 타입·값, python_ast는 구문·최상위 symbol과 literal을 검사합니다. 대상 코드를 import하거나 실행하지 않습니다. 입력은 검사당 1 MiB, AST는 100,000 node로 제한합니다. test_command/build_command는 고정 command profile 계약만 있으며 실제 실행은 UNVERIFIED입니다. OS 격리 검증 전에는 프로젝트 pytest/build 코드를 실행할 수 없습니다.

fixture executor는 controller와 분리된 원래의 answer-v1 및 새 json-config-v1 profile을 갖습니다. 둘 다 controller 소유 상수만 씁니다. 사용자 요청을 생성 코드나 shell로 변환하지 않습니다. repair는 새 round를 만들고 같은 논리 decision의 예산을 다시 차감하지 않습니다. 시작한 writer의 receipt가 불명확하면 자동 재실행하지 않습니다. 외부 효과가 없는 정적 parser만 같은 고정 바이트에서 다시 검사할 수 있습니다.

`examples/python`과 `examples/json`은 소유 샘플입니다. 원하는 샘플 폴더를 새 전용 폴더로 복사하고 Git init·최초 commit 후, `submit --repo 샘플루트 --plan 샘플루트/plan.json --request 정적검사 --run`으로 실행합니다. 상태 폴더는 샘플 저장소 밖에 둡니다. 기본 fixture 하나와 달리 writer 뒤 두 개의 독립 read-only step을 수행합니다. 테스트는 두 샘플의 성공·repair·부분 실패·중간 crash·취소를 검사합니다.
