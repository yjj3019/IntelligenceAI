export type Role = "owner" | "operator" | "approver" | "viewer" | "revoked";
export type Page =
  | "dashboard"
  | "projects"
  | "new"
  | "task"
  | "candidate"
  | "approvals"
  | "connections"
  | "audit";
export type Plan = {
  profile: string;
  steps: { id: string; role: string; depends_on: string[]; mode: string }[];
  scope: string[];
  model_calls: number;
  execution_enabled: boolean;
  evidence: string;
  reason: string;
};
export type TaskInput = {
  title: string;
  request: string;
  profile: "python-review" | "json-review";
};
export type Project = {
  id: string;
  tenant_id: string;
  name: string;
  policy_digest: string;
  role: Role;
  members?: { user_id: string; name: string; role: Role }[];
};
export type Binding = {
  candidate_digest: string;
  policy_digest: string;
  evidence_digest: string;
  destination_id: "private-review";
  generation: number;
  expires_at: number;
};
export type Artifact = {
  id: string;
  name: string;
  kind: string;
  digest: string;
};
export type Task = {
  id: string;
  project_id: string;
  title: string;
  request: string;
  state: string;
  generation: number;
  created_at: number;
  plan: Plan;
  candidate_digest: string | null;
  evidence_digest: string | null;
  evidence_verified: boolean;
  destination_id: "private-review";
  execution_enabled: boolean;
  model_calls: number | null;
  local_cli_invocations?: number | null;
  source: string;
  artifacts?: Artifact[];
  approval?: Binding | null;
  vendor_runs?: {
    id: string;
    generation: number;
    state: string;
    result: null | {
      kind: "completed" | "terminated" | "never_started";
      scope: "FAKE_VENDOR_TEST_ONLY";
      live_model: "NOTRUN";
      termination_confirmed: boolean;
      returncode?: number;
      output?: { message: string; value: number; status: "SYNTHETIC_OUTPUT" };
    };
  }[];
  runs?: {
    core_task_id: string;
    generation: number;
    phase: string;
    receipt:
      | null
      | { kind: "never_started"; never_started: true }
      | {
          kind: "completed";
          scope: string;
          live_model: string;
          os_sandbox: string;
          core_state: string;
          steps: {
            step_id: string;
            status: string;
            result: null | { status: string };
          }[];
        };
  }[];
};
export type Audit = {
  id: string;
  actor_id: string;
  event: string;
  detail: Record<string, unknown>;
  created_at: number;
  task_id: string | null;
};
export type Session = { user: { id: string; name: string }; csrf: string };
export type ProviderReadiness = {
  provider: "claude" | "codex" | "grok" | "gemini-cli" | "antigravity";
  mode: "read_only" | "write";
  host_os: string;
  status: "BLOCKED";
  reasons: string[];
  live_model: "NOTRUN";
  os_isolation: "UNVERIFIED";
  wrapper_attempts: 1;
  native_retries: "UNVERIFIED";
};
export type Connections = {
  execution_enabled: boolean;
  providers: string;
  sandbox: string;
  runner: string;
  database: string;
  external_effects: string;
  fixture_execution?: string;
  live_model?: string;
  provider_readiness?: ProviderReadiness[];
};
