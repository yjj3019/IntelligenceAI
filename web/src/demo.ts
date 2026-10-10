import type {
  Audit,
  Connections,
  Plan,
  Project,
  Task,
  TaskInput,
} from "./types";
const hash = (char: string) => char.repeat(64);
export const demoProject: Project = {
  id: "demo-project",
  tenant_id: "synthetic",
  name: "Atlas workspace",
  policy_digest: hash("b"),
  role: "viewer",
  members: [
    { user_id: "sample-owner", name: "Alex · sample owner", role: "owner" },
    {
      user_id: "sample-reviewer",
      name: "Morgan · sample reviewer",
      role: "approver",
    },
  ],
};
export function demoPlan(input: TaskInput): Plan {
  return {
    profile: input.profile,
    steps: [
      { id: "inspect", role: "analyze", depends_on: [], mode: "read_only" },
      {
        id: "candidate",
        role: "implement",
        depends_on: ["inspect"],
        mode: "disabled",
      },
      {
        id: "verify",
        role: "review",
        depends_on: ["candidate"],
        mode: "read_only",
      },
      { id: "approval", role: "gate", depends_on: ["verify"], mode: "human" },
    ],
    scope: [input.profile === "python-review" ? "answer.py" : "settings.json"],
    model_calls: 0,
    execution_enabled: false,
    evidence: "UNVERIFIED",
    reason: "Synthetic walkthrough; no model or runner has executed",
  };
}
const plan = demoPlan({
  title: "Example",
  request: "Example",
  profile: "json-review",
});
export const demoTasks: Task[] = [
  {
    id: "sample-review",
    project_id: demoProject.id,
    title: "Clarify the configuration defaults",
    request:
      "Show a small, reviewable candidate and the evidence required before approval.",
    state: "READY_FOR_APPROVAL",
    generation: 1,
    created_at: 1791583200,
    plan,
    candidate_digest: hash("a"),
    evidence_digest: hash("c"),
    evidence_verified: false,
    destination_id: "private-review",
    execution_enabled: false,
    model_calls: 0,
    source: "synthetic-fixture",
    artifacts: [
      {
        id: "sample-diff",
        name: "candidate.diff",
        kind: "diff",
        digest: hash("d"),
      },
    ],
    approval: null,
  },
  {
    id: "sample-blocked",
    project_id: demoProject.id,
    title: "Check the service boundaries",
    request: "Review the configured runner and permission contract.",
    state: "BLOCKED",
    generation: 1,
    created_at: 1791579600,
    plan,
    candidate_digest: null,
    evidence_digest: null,
    evidence_verified: false,
    destination_id: "private-review",
    execution_enabled: false,
    model_calls: 0,
    source: "synthetic-fixture",
  },
  {
    id: "sample-cancel",
    project_id: demoProject.id,
    title: "Retire an unused draft",
    request: "Cancel a draft before execution.",
    state: "CANCELLED",
    generation: 2,
    created_at: 1791576000,
    plan,
    candidate_digest: null,
    evidence_digest: null,
    evidence_verified: false,
    destination_id: "private-review",
    execution_enabled: false,
    model_calls: 0,
    source: "synthetic-fixture",
  },
];
export const demoDiff =
  '--- a/settings.json\n+++ b/settings.json\n@@ -1,4 +1,4 @@\n {\n-  "timeout": 15,\n+  "timeout": 30,\n   "retry": false\n }\n\nSynthetic illustration only. No model execution or repository changes.';
export const demoAudit: Audit[] = [
  {
    id: "sample-event-1",
    actor_id: "sample-owner",
    event: "plan.previewed",
    detail: { source: "synthetic fixture", model_calls: 0 },
    created_at: 1791583200,
    task_id: "sample-review",
  },
  {
    id: "sample-event-2",
    actor_id: "sample-reviewer",
    event: "evidence.unverified",
    detail: { reason: "No real scanner or provider evidence" },
    created_at: 1791583260,
    task_id: "sample-review",
  },
  {
    id: "sample-event-3",
    actor_id: "sample-owner",
    event: "task.cancelled",
    detail: { source: "synthetic fixture" },
    created_at: 1791583320,
    task_id: "sample-cancel",
  },
];
export const demoConnections: Connections = {
  execution_enabled: false,
  providers: "DISABLED",
  sandbox: "UNVERIFIED",
  runner: "NOT_CONFIGURED",
  database: "SYNTHETIC_DEMO",
  external_effects: "DISABLED",
};
