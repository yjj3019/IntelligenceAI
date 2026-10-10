import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

export const ko = {
  FIXTURE_ONLY_CAPABILITY: "고정 fixture 실행 권한만 설정됨",
  "Run fixed fixture": "고정 fixture 실행",
  "Fixed fixture queued. No paid model or external action is authorized.":
    "고정 fixture가 대기열에 등록됐습니다. 유료 모델이나 외부 작업은 허용되지 않습니다.",
  "Fixed fixtures create synthetic candidates and run static parsers only. Live models, shell commands and OS containment remain unverified.":
    "고정 fixture는 합성 후보를 만들고 정적 파서만 실행합니다. 실제 모델, shell 명령과 OS 격리는 검증되지 않았습니다.",
  "Core runs & receipts": "Core 실행·수신 기록",
  "Fixed fixture receipt. Static checks verify candidate bytes; they do not verify a live model or sandbox.":
    "고정 fixture 수신 기록입니다. 정적 검사로 후보 bytes를 확인하며 실제 모델이나 sandbox를 검증하지는 않습니다.",
  "Receipt pending. Lease expiry does not confirm termination.":
    "수신 기록을 기다립니다. lease 만료는 실행 종료를 확인하지 않습니다.",
  "Live model": "실제 모델",
  "Core state": "Core 상태",
  "Live model execution is NOTRUN. Fixed fixture receipts describe static checks only.":
    "실제 모델 실행은 NOTRUN입니다. 고정 fixture 수신 기록은 정적 검사만 설명합니다.",
  "An operator must provision an unexpired fixed-fixture capability before this task can be queued.":
    "대기열 등록 전 운영자가 만료되지 않은 고정 fixture 실행 권한을 설정해야 합니다.",
  "This task cannot be queued in its current state. Refresh its saved status.":
    "현재 상태에서는 대기열에 등록할 수 없습니다. 저장된 상태를 새로고침하세요.",
  "fixture execution": "fixture 실행",
  "live model": "실제 모델",
  AUTHORIZED: "권한 설정됨",
  NOTRUN: "미실행",
  CLAIMED: "소유권 확보",
  RESERVED: "실행 예약",
  STARTING: "실행 시작 중",
  RECEIVED: "수신 완료",
  TERMINATED: "종료 확인",
  "Signing out. Private requests are invalidated.":
    "로그아웃 중입니다. 기존 private 요청은 무효화됩니다.",
  "Approval intent expiry:": "승인 요청 만료:",
  "This intent expired. Check its receipt before preparing a new intent.":
    "이 승인 요청은 만료되었습니다. 새 요청을 준비하기 전에 접수 기록을 확인하세요.",
  "The response was not confirmed. Retry this exact intent or check its recorded receipt.":
    "응답을 확인하지 못했습니다. 동일한 승인 요청으로 다시 시도하거나 접수 기록을 확인하세요.",
  "This request receipt was recorded. Review the current task grant and expiry.":
    "이 요청의 접수 기록이 저장되었습니다. 현재 작업의 승인 조건과 만료를 확인하세요.",
  "Candidate, destination, expiry and request key are fixed for this intent.":
    "이 요청의 후보, 대상, 만료와 요청 키가 고정되었습니다.",
  "Prepare new approval intent": "새 승인 요청 준비",
  "Prepare approval intent": "승인 요청 준비",
  "Check recorded approval receipt": "승인 접수 기록 확인",
  "Recovery is blocked until a trusted termination receipt confirms the prior runner stopped. Do not clear its lease.":
    "이전 실행기의 종료를 신뢰할 수 있는 영수증으로 확인할 때까지 복구가 차단됩니다. lease를 지우지 마세요.",
  "Recovery is unavailable in this state. Refresh status and review the task.":
    "현재 상태에서는 복구할 수 없습니다. 상태를 새로고침하고 작업을 확인하세요.",
  "Approval is blocked until trusted candidate and evidence checks are verified.":
    "신뢰할 수 있는 후보와 증거 검사가 검증될 때까지 승인이 차단됩니다.",
  "The candidate, policy, evidence, destination or generation changed. Refresh before preparing a new approval intent.":
    "후보, 정책, 증거, 대상 또는 세대가 변경되었습니다. 새 승인 요청을 준비하기 전에 새로고침하세요.",
  "This approval intent expired. Check its recorded receipt before explicitly preparing a new intent.":
    "이 승인 요청이 만료되었습니다. 접수 기록을 확인한 뒤 새 요청을 직접 준비하세요.",
  "This request key belongs to a different payload. Reconcile the recorded request before starting a new intent.":
    "이 요청 키는 다른 payload에 연결되어 있습니다. 새 요청 전에 기존 접수 기록을 확인하세요.",
  "Signed-out visitor": "로그인 전 방문자",
  "No model or sandbox has executed. This ledger records held work only.":
    "모델이나 샌드박스는 실행되지 않았습니다. 이 원장은 보류된 작업만 기록합니다.",
  Unavailable: "확인 불가",
  Overview: "대시보드",
  "Projects & people": "프로젝트·구성원",
  "New task": "새 작업",
  "Task & steps": "작업·단계",
  "Candidate & checks": "후보·검사",
  "Approval & recovery": "승인·복구",
  Connections: "연결·실행환경",
  "Audit trail": "감사 기록",
  "PRIVATE CONSOLE / NOT CONNECTED": "PRIVATE 콘솔 / 미연결",
  "Return to demo": "데모로 돌아가기",
  "A private deployment": "Private 배포 환경이",
  "is still required.": "아직 필요합니다.",
  "This site is a synthetic, read-only product walkthrough. There is no connected login, private database, Linux runner or model provider.":
    "이 사이트는 합성 데이터로 구성한 읽기 전용 제품 데모입니다. 로그인, private DB, Linux 실행기와 모델 제공자가 연결되어 있지 않습니다.",
  "No credentials are collected here. Real project access requires a separately configured HTTPS server, PostgreSQL and verified OIDC.":
    "여기서는 자격 증명을 수집하지 않습니다. 실제 프로젝트에 접근하려면 별도로 구성한 HTTPS 서버, PostgreSQL과 검증된 OIDC가 필요합니다.",
  "Explore the read-only demo": "읽기 전용 데모 보기",
  Documentation: "문서",
  "Private console": "Private 콘솔",
  "Public navigation": "공개 페이지 탐색",
  "PRODUCT & TRUST": "제품·신뢰",
  "Know what runs.": "무엇이 실행되는지 확인하고,",
  "Know what is still unverified.": "검증되지 않은 부분을 알아보세요.",
  "IntelligenceAI connects a typed plan, a candidate, evidence and an exact approval. This release adds a private project ledger and a synthetic interface walkthrough.":
    "IntelligenceAI는 구조화된 계획, 후보 변경, 증거와 정확한 승인 조건을 연결합니다. 이번 버전은 private 프로젝트 원장과 합성 UI 데모를 제공합니다.",
  "Exact approvals": "정확한 조건에 결합된 승인",
  "Candidate, policy, evidence, destination, generation and expiry must match. Every dispatch rechecks project permissions. Actual dispatch is disabled.":
    "후보·정책·증거·대상·세대·만료가 모두 일치해야 합니다. 실행 직전마다 프로젝트 권한을 재검사합니다. 실제 실행은 비활성입니다.",
  "Private by project": "프로젝트별 private 접근",
  "OIDC identities map to operator-provisioned users. Server sessions and project membership protect status, logs, artifacts and updates.":
    "OIDC 신원은 운영자가 등록한 사용자에 연결됩니다. 서버 세션과 프로젝트 구성원 권한이 상태·로그·산출물·업데이트를 보호합니다.",
  "Honest boundaries": "검증 범위를 명확하게",
  "Provider execution, paid models and an OS sandbox are unverified. A fixture check is never displayed as model success. Meta AI is excluded.":
    "제공자 실행, 유료 모델과 OS 샌드박스는 미검증 상태입니다. 테스트 fixture 검사를 모델 성공으로 표시하지 않습니다. Meta AI는 제외합니다.",
  "English guide ↗": "영문 안내 ↗",
  "한국어 안내 ↗": "한국어 안내 ↗",
  "Security model ↗": "보안 모델 ↗",
  "DELIBERATE BY DESIGN": "신중한 결정을 위한 설계",
  "Move work forward.": "작업은 앞으로.",
  "Keep the decisions yours.": "결정은 당신의 손에.",
  "A clear path from request to review. Inspect every step, compare the candidate, and see the evidence before you approve.":
    "요청부터 검토까지 한눈에 살펴보세요. 각 단계를 확인하고 후보 변경을 비교한 뒤, 증거를 보고 승인하세요.",
  "Explore the demo": "데모 살펴보기",
  "Read the documentation": "문서 읽기",
  "Read-only synthetic data. No model calls or external actions.":
    "읽기 전용 합성 데이터입니다. 모델 호출과 외부 효과는 없습니다.",
  "Product preview": "제품 미리보기",
  "Your work, in perspective": "작업의 전체 흐름을 한눈에",
  "synthetic preview": "합성 미리보기",
  "A REVIEWABLE WORKFLOW": "검토 가능한 작업 흐름",
  "Configuration defaults": "기본 구성 설정",
  "One candidate. Explicit evidence. A human decision.":
    "하나의 후보. 명확한 증거. 사람의 결정.",
  Plan: "계획",
  Candidate: "후보",
  Checks: "검사",
  Approval: "승인",
  "Your decision": "직접 결정",
  "Visible & traceable": "확인·추적 가능",
  "Evidence comes first.": "증거가 먼저입니다.",
  "See what was checked and what is still unverified. External execution remains disabled.":
    "검사한 내용과 미검증 항목을 확인하세요. 외부 실행은 계속 비활성입니다.",
  "unverified evidence": "미검증 증거",
  "Plans you can follow": "따라갈 수 있는 계획",
  "Explicit dependencies and a bounded scope make the next step clear.":
    "명시적 의존성과 제한된 범위로 다음 단계를 분명하게 만듭니다.",
  "Changes you can inspect": "살펴볼 수 있는 변경",
  "Review the candidate alongside checks, provenance and exact digests.":
    "검사 결과, 출처와 정확한 digest를 함께 보며 후보 변경을 검토하세요.",
  "Control you can trust": "근거를 확인하는 제어",
  "Approvals bind to evidence. Recovery preserves uncertain execution.":
    "승인은 증거에 결합됩니다. 복구 중에도 불확실한 실행의 소유권을 보존합니다.",
  "IntelligenceAI · A considered approach to task control.":
    "IntelligenceAI · 신중하게 작업을 제어합니다.",
  "Capabilities & limitations": "기능·검증 한계",
  "Allowed scope:": "허용 범위:",
  ". The request never becomes a shell command.":
    ". 요청은 셸 명령으로 변환되지 않습니다.",
  "0 model calls · execution disabled ·": "모델 호출 0회 · 실행 비활성 ·",
  "No verified Linux runner or provider configured":
    "검증된 Linux 실행기나 제공자가 구성되지 않았습니다",
  "Synthetic walkthrough; no model or runner has executed":
    "합성 데모입니다. 모델이나 실행기는 실행되지 않았습니다",
  "entry point": "시작 단계",
  "after ": "선행 단계: ",
  "Skip to main content": "본문으로 건너뛰기",
  "Private workspace": "Private 작업 공간",
  "Private project console": "Private 프로젝트 콘솔",
  "Synthetic demo workspace": "합성 데모 작업 공간",
  WORKSPACE: "작업 공간",
  "Workspace navigation": "작업 공간 탐색",
  "Evidence before effects": "실행 전에 증거 확인",
  "Live providers and external actions are disabled.":
    "실제 제공자와 외부 효과는 비활성입니다.",
  "Understand the boundaries": "검증 범위 알아보기",
  "Demo visitor": "데모 방문자",
  "Read-only access": "읽기 전용 접근",
  "Sign-in required": "로그인 필요",
  "Sign out": "로그아웃",
  "Open navigation": "탐색 메뉴 열기",
  "Close navigation": "탐색 메뉴 닫기",
  Workspace: "작업 공간",
  "Read-only demo": "읽기 전용 데모",
  "View demo": "데모 보기",
  "Sign in": "로그인",
  "Private deployment": "Private 배포 안내",
  "Private ledger · Execution disabled. No paid model calls, repository execution or external effects.":
    "Private 원장 · 실행 비활성입니다. 유료 모델 호출, 저장소 코드 실행과 외부 효과는 없습니다.",
  "Synthetic walkthrough · Sample tasks and evidence. No model has run. All demo mutations are disabled.":
    "합성 데모 · 예시 작업과 증거입니다. 모델은 실행되지 않았으며 모든 데모 변경 기능은 비활성입니다.",
  "Learn more": "자세히 보기",
  "A CLEAR VIEW OF YOUR WORK": "작업의 흐름을 명확하게",
  "WORKSPACE / ": "작업 공간 / ",
  "Make room for thoughtful work.": "신중하게 작업을 진행하세요.",
  "A plan, a candidate, the evidence. Everything you need for the next decision.":
    "계획, 후보 변경과 증거. 다음 결정에 필요한 내용을 한곳에서 확인하세요.",
  "Inspect the details. Keep every decision tied to its context.":
    "세부 내용을 살펴보고 각 결정의 근거를 확인하세요.",
  Refresh: "새로고침",
  Reconnect: "다시 연결",
  "Sign in securely": "안전하게 로그인",
  "Loading saved workspace…": "저장된 작업 공간을 불러오는 중…",
  "Your private workspace starts with sign-in.":
    "로그인하면 private 작업 공간을 열 수 있습니다.",
  "No accessible project": "접근 가능한 프로젝트가 없습니다",
  "Only provisioned OIDC identities and authorized project members can view private work. Use the synthetic demo to explore the interface.":
    "등록된 OIDC 신원과 인가된 프로젝트 구성원만 private 작업을 볼 수 있습니다. UI는 합성 데모에서 살펴보세요.",
  "Tracked tasks": "기록된 작업",
  "Saved in your project ledger": "프로젝트 원장에 저장됨",
  "Illustrative sample tasks": "설명을 위한 예시 작업",
  "Awaiting review": "검토 대기",
  "Evidence must be verified first": "증거 검증이 먼저 필요합니다",
  "Needs attention": "확인 필요",
  "Clear reasons, deliberate recovery": "사유를 확인하고 신중하게 복구",
  "Model calls": "모델 호출",
  "Live execution is disabled": "실제 실행 비활성",
  "Recent tasks": "최근 작업",
  "From request to a considered decision.": "요청부터 신중한 결정까지.",
  tasks: "개 작업",
  "Search tasks": "작업 검색",
  "Search by task or status…": "작업 이름·상태로 검색…",
  "Latest first": "최신순",
  TASK: "작업",
  STATUS: "상태",
  GENERATION: "세대",
  "private ledger": "private 원장",
  "synthetic sample": "합성 예시",
  "No matching tasks": "검색 결과가 없습니다",
  "A clear starting point": "분명한 시작점",
  "Try another task name or status.": "다른 작업 이름이나 상태를 검색하세요.",
  "Create a plan preview to define the next piece of work.":
    "계획 미리보기로 다음 작업의 범위를 정하세요.",
  "THE NEXT DECISION": "다음 결정",
  "Review with the whole picture.": "전체 흐름을 보고 검토하세요.",
  "A candidate is only one part of the story. Start with the scope, check the evidence, then decide.":
    "후보 변경만으로는 충분하지 않습니다. 범위를 살펴보고 증거를 확인한 뒤 결정하세요.",
  "Candidate & policy digests": "후보·정책 digest",
  "Evidence & generation": "증거·세대",
  "Destination & expiry": "대상·만료",
  "Open review queue": "검토 대기열 열기",
  "Real approvals remain unavailable until verified evidence exists.":
    "검증된 증거가 있어야 실제 승인이 가능합니다.",
  "Workspace activity": "작업 공간 활동",
  "Every saved decision leaves a trace.": "저장된 결정마다 기록을 남깁니다.",
  "View audit trail": "감사 기록 보기",
  "Private audit event": "Private 감사 이벤트",
  "Synthetic event": "합성 이벤트",
  "No saved events yet.": "아직 저장된 이벤트가 없습니다.",
  "Projects & membership": "프로젝트·구성원 권한",
  "Authorization is checked on each request, including artifacts and updates.":
    "산출물과 업데이트를 포함한 모든 요청에서 권한을 검사합니다.",
  Project: "프로젝트",
  "Choose project": "프로젝트 선택",
  "Role for": "구성원 역할:",
  "New identities and projects require operator provisioning. Browser input cannot select a principal or tenant.":
    "새 사용자 신원과 프로젝트는 운영자가 등록해야 합니다. 브라우저 입력으로 principal이나 tenant를 선택할 수 없습니다.",
  "Define a bounded task": "범위가 제한된 작업 정의",
  "Describe the outcome. Inspect the fixed plan before saving.":
    "원하는 결과를 설명하고 저장 전에 고정된 계획을 확인하세요.",
  "Task title": "작업 제목",
  "A small, reviewable piece of work": "검토 가능한 작은 작업",
  "What should change?": "무엇을 변경해야 하나요?",
  "Describe the intended result and its scope. Do not include secrets.":
    "원하는 결과와 범위를 설명하세요. 비밀 정보는 포함하지 마세요.",
  "Review profile": "검토 프로필",
  "Python · static review": "Python · 정적 검토",
  "JSON · configuration review": "JSON · 구성 검토",
  "Preparing…": "준비 중…",
  "Preview plan": "계획 미리보기",
  "Plan preview": "계획 미리보기",
  "Saving…": "저장 중…",
  "Save to private ledger": "Private 원장에 저장",
  "Saving creates a held job. No runner or model starts.":
    "저장하면 보류된 큐 항목이 만들어집니다. 실행기나 모델은 시작하지 않습니다.",
  "The demo supports previews only. Sign in to save a private task.":
    "데모에서는 미리보기만 가능합니다. Private 작업을 저장하려면 로그인하세요.",
  "Make the next step visible": "다음 단계를 확인하세요",
  "Your preview will show dependencies, allowed scope and execution limits.":
    "미리보기에서 의존성, 허용 범위와 실행 제한을 확인할 수 있습니다.",
  "· generation": "· 세대",
  "Inspect candidate": "후보 변경 살펴보기",
  "Review & recovery": "검토·복구",
  "Request cancellation": "취소 요청",
  "Provenance & execution": "출처·실행 상태",
  Source: "출처",
  "Verified static evidence": "검증된 정적 증거",
  UNVERIFIED: "미검증",
  DISABLED: "비활성",
  "External effects": "외부 효과",
  "A sample status is an illustration. It does not mean a model or sandbox has executed.":
    "예시 상태는 설명을 위한 것입니다. 모델이나 샌드박스가 실행되었다는 뜻이 아닙니다.",
  "No task selected": "선택한 작업이 없습니다",
  "Create a task or select one from the overview.":
    "작업을 만들거나 대시보드에서 선택하세요.",
  "Candidate diff": "후보 변경 diff",
  "Private artifact · rendered as plain text":
    "Private 산출물 · 일반 텍스트로 표시",
  "Synthetic diff · illustration only": "합성 diff · 설명을 위한 예시",
  "No candidate artifact yet": "아직 후보 산출물이 없습니다",
  "This task is held. No runner has produced a candidate.":
    "작업은 보류 상태입니다. 실행기가 후보 변경을 만들지 않았습니다.",
  "Evidence & checks": "증거·검사",
  "Secret scan": "비밀 정보 검사",
  "UNVERIFIED · no real scanner receipt": "미검증 · 실제 검사기 영수증 없음",
  "Provider execution": "제공자 실행",
  "DISABLED · no model has run": "비활성 · 모델 실행 없음",
  "OS sandbox": "OS 샌드박스",
  "UNVERIFIED · no containment claim": "미검증 · 격리 보장 없음",
  "Candidate digest": "후보 digest",
  "No candidate fingerprint": "후보 fingerprint 없음",
  "Evidence digest": "증거 digest",
  "No verified evidence": "검증된 증거 없음",
  "Review approval binding": "승인 결합 조건 확인",
  "No candidate selected": "선택한 후보가 없습니다",
  "Select a saved task from the overview.":
    "대시보드에서 저장된 작업을 선택하세요.",
  "Approve an exact review": "정확한 검토 조건 승인",
  "A review grant does not enable publishing, paid models or execution.":
    "검토 승인으로 게시, 유료 모델이나 실행이 활성화되지는 않습니다.",
  Policy: "정책",
  Evidence: "증거",
  Destination: "대상",
  Generation: "세대",
  "Grant duration": "승인 유효 기간",
  "10 minutes · checked again before dispatch": "10분 · 실행 직전에 재검사",
  "Static evidence is verified. No live model or sandbox claim is implied.":
    "정적 증거가 검증되었습니다. 실제 모델 실행이나 샌드박스 검증을 뜻하지 않습니다.",
  "Approval blocked: verified evidence is required.":
    "승인 차단: 검증된 증거가 필요합니다.",
  "Review grant recorded. Expiry:": "검토 승인 기록됨. 만료:",
  ". Dispatch remains disabled.": ". 실행은 계속 비활성입니다.",
  "Record review approval": "검토 승인 기록",
  "Reject review": "검토 거절",
  "Recover with certainty": "확인한 뒤 복구",
  "An unstarted held job can be prepared again. Uncertain execution requires a real termination receipt and keeps its lease.":
    "시작하지 않은 보류 작업은 다시 준비할 수 있습니다. 실행 여부가 불확실하면 실제 종료 영수증이 필요하며 lease를 유지합니다.",
  "Prepare recovery": "복구 준비",
  "Recovery invalidates old approvals and increments the generation. Execution remains disabled.":
    "복구하면 기존 승인이 무효화되고 세대가 증가합니다. 실행은 계속 비활성입니다.",
  "No reviews to inspect": "확인할 검토가 없습니다",
  "Select a task to inspect its approval and recovery state.":
    "작업을 선택해 승인·복구 상태를 확인하세요.",
  "Connection & environment status": "연결·실행환경 상태",
  "Configuration belongs to the server operator. Credentials and paths are never entered here.":
    "구성은 서버 운영자가 관리합니다. 여기서는 자격 증명이나 서버 경로를 입력하지 않습니다.",
  providers: "제공자",
  sandbox: "샌드박스",
  runner: "실행기",
  database: "데이터베이스",
  "external effects": "외부 효과",
  NOT_CONFIGURED: "미구성",
  POSTGRESQL: "PostgreSQL",
  TEST_FIXTURE_SQLITE: "테스트 fixture SQLite",
  SYNTHETIC_DEMO: "합성 데모",
  "Claude, Codex, Grok, Gemini and other planned integrations remain disabled until provider permissions and Linux containment are verified. Meta AI is excluded.":
    "Claude, Codex, Grok, Gemini 등 예정된 통합은 제공자 권한과 Linux 격리를 검증할 때까지 비활성입니다. Meta AI는 제외합니다.",
  "Deployment prerequisites": "배포 준비 조건",
  "A canonical HTTPS origin, PostgreSQL database, OIDC issuer and isolated Linux runner need independent validation. The public demo contains no private API or write endpoint.":
    "공식 HTTPS origin, PostgreSQL, OIDC issuer와 격리된 Linux 실행기를 각각 검증해야 합니다. 공개 데모에는 private API나 쓰기 endpoint가 없습니다.",
  "Read the deployment boundaries": "배포 범위 읽기",
  "Project audit trail": "프로젝트 감사 기록",
  "Redacted before persistence. Scoped to the current project.":
    "저장 전에 민감 정보를 가립니다. 현재 프로젝트에 한정된 기록입니다.",
  "Synthetic events. No real actor activity or model execution.":
    "합성 이벤트입니다. 실제 사용자 활동이나 모델 실행이 아닙니다.",
  "No audit events yet": "아직 감사 이벤트가 없습니다",
  "Saved submissions and decisions will appear here.":
    "저장한 작업 제출과 결정이 여기에 표시됩니다.",
  "Project-scoped private ledger": "프로젝트별 private 원장",
  "Synthetic data · read-only demo": "합성 데이터 · 읽기 전용 데모",
  "Execution disabled": "실행 비활성",
  "Request task cancellation?": "작업 취소를 요청할까요?",
  "The server confirms cancellation only if the queue item has never started. Otherwise the state stays “Cancellation requested” until termination is verified.":
    "서버는 큐 항목이 한 번도 시작되지 않은 경우에만 취소를 확정합니다. 그 외에는 종료가 검증될 때까지 “취소 요청 중” 상태를 유지합니다.",
  "Keep task": "작업 유지",
  "Confirm cancellation": "취소 요청 확인",
  "Cancellation requested. Termination has not been confirmed.":
    "취소를 요청했습니다. 종료는 아직 확인되지 않았습니다.",
  "Saved to the private ledger. Execution remains disabled.":
    "Private 원장에 저장했습니다. 실행은 계속 비활성입니다.",
  "Update could not be read. Refresh to reconnect.":
    "업데이트를 읽지 못했습니다. 새로고침해 다시 연결하세요.",
  "You have signed out.": "로그아웃했습니다.",
  "Your session expired. Sign in again to continue.":
    "세션이 만료되었습니다. 계속하려면 다시 로그인하세요.",
  "Access is unavailable. Your project permissions may have changed.":
    "접근할 수 없습니다. 프로젝트 권한이 변경되었을 수 있습니다.",
  "The task or approval changed. Refresh and review the latest evidence.":
    "작업이나 승인 조건이 변경되었습니다. 새로고침한 뒤 최신 증거를 확인하세요.",
  "Check your input. Credentials, commands and authority fields are not accepted.":
    "입력을 확인하세요. 자격 증명, 명령이나 권한 관련 필드는 허용되지 않습니다.",
  "The service could not complete this request. Try again with the same request key.":
    "요청을 완료하지 못했습니다. 같은 요청 키로 다시 시도하세요.",
  "Connection interrupted. Reconnect to retrieve the latest saved state.":
    "연결이 끊어졌습니다. 다시 연결해 최신 저장 상태를 확인하세요.",
  "ready for approval": "승인 검토 대기",
  blocked: "차단됨",
  cancelled: "취소 확인 완료",
  "cancel requested": "취소 요청 중",
  failed: "실패",
  "needs reconciliation": "실행 대조 필요",
  running: "실행 중",
  planned: "계획됨",
  completed: "완료",
  unverified: "미검증",
  owner: "소유자",
  operator: "운영자",
  approver: "승인자",
  viewer: "열람자",
  revoked: "권한 회수됨",
  analyze: "분석",
  implement: "구현",
  review: "검토",
  gate: "승인 검사",
  "read only": "읽기 전용",
  disabled: "비활성",
  human: "사람이 결정",
  Language: "언어",
  "No recorded receipt was found. Checking did not submit approval.":
    "저장된 접수 기록이 없습니다. 기록 조회로 승인을 제출하지 않았습니다.",
  "Resend the same approval request": "동일 승인 요청 다시 전송",
  "Switch to Korean": "한국어로 전환",
  "Switch to English": "영어로 전환",
  Timezone: "시간대",
  "Clarify the configuration defaults": "기본 구성 설정 정리",
  "Check the service boundaries": "서비스 검증 범위 확인",
  "Retire an unused draft": "사용하지 않는 초안 취소",
  "Show a small, reviewable candidate and the evidence required before approval.":
    "검토 가능한 작은 후보 변경과 승인에 필요한 증거를 표시합니다.",
  "Review the configured runner and permission contract.":
    "구성된 실행기와 권한 계약을 검토합니다.",
  "Cancel a draft before execution.": "실행 전에 초안을 취소합니다.",
} as const;

export type Language = "ko" | "en";
export const en: Record<keyof typeof ko, string> = Object.fromEntries(
  Object.keys(ko).map((key) => [key, key]),
) as Record<keyof typeof ko, string>;
export const catalogs: Record<Language, Record<string, string>> = { en, ko };
export function translate(language: Language, key: string): string {
  return catalogs[language][key] ?? catalogs.en[key] ?? key;
}
export function initialLanguage(): Language {
  try {
    const stored = localStorage.getItem("iai.language");
    if (stored === "ko" || stored === "en") return stored;
  } catch {
    /* Private browsing may disable storage. */
  }
  return navigator.language.toLowerCase().startsWith("ko") ? "ko" : "en";
}
const Context = createContext<{
  language: Language;
  setLanguage: (value: Language) => void;
} | null>(null);
export function LocaleProvider({ children }: { children: ReactNode }) {
  const [language, update] = useState(initialLanguage);
  useEffect(() => {
    document.documentElement.lang = language;
    document.title =
      language === "ko"
        ? "IntelligenceAI · 작업 제어"
        : "IntelligenceAI · Task control";
  }, [language]);
  const setLanguage = (value: Language) => {
    update(value);
    try {
      localStorage.setItem("iai.language", value);
    } catch {
      /* Language still works without persistence. */
    }
  };
  return (
    <Context.Provider value={{ language, setLanguage }}>
      {children}
    </Context.Provider>
  );
}
export function useLocale() {
  const context = useContext(Context);
  if (!context) throw new Error("LocaleProvider required");
  const locale = context.language === "ko" ? "ko-KR" : "en-US";
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return {
    ...context,
    t: (key: string) => translate(context.language, key),
    timezone,
    formatNumber: (value: number, minimumIntegerDigits = 1) =>
      new Intl.NumberFormat(locale, { minimumIntegerDigits }).format(value),
    formatDate: (seconds: number, timeOnly = false) =>
      new Intl.DateTimeFormat(locale, {
        timeZone: timezone,
        ...(timeOnly
          ? { hour: "2-digit", minute: "2-digit" }
          : { dateStyle: "medium", timeStyle: "short" }),
      }).format(new Date(seconds * 1000)),
  };
}
export function LanguageSwitcher() {
  const { language, setLanguage, t } = useLocale();
  return (
    <div className="language-switcher" role="group" aria-label={t("Language")}>
      <button
        type="button"
        aria-label={t("Switch to Korean")}
        aria-pressed={language === "ko"}
        onClick={() => setLanguage("ko")}
      >
        KO
      </button>
      <button
        type="button"
        aria-label={t("Switch to English")}
        aria-pressed={language === "en"}
        onClick={() => setLanguage("en")}
      >
        EN
      </button>
    </div>
  );
}
