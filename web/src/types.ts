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
  model_calls: number;
  source: string;
  artifacts?: Artifact[];
  approval?: Binding | null;
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
export type Connections = {
  execution_enabled: boolean;
  providers: string;
  sandbox: string;
  runner: string;
  database: string;
  external_effects: string;
};
