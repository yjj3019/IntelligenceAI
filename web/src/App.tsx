import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  Code2,
  FileDiff,
  FolderKanban,
  GitBranch,
  Layers3,
  LayoutDashboard,
  LockKeyhole,
  Menu,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Users,
  X,
} from "lucide-react";
import type {
  Audit,
  Binding,
  Connections,
  Page,
  Plan,
  Project,
  Role,
  Session,
  Task,
  TaskInput,
} from "./types";
import { api, ApiError, message, mutation } from "./api";
import { LocaleProvider, LanguageSwitcher, useLocale } from "./i18n";
import {
  demoAudit,
  demoConnections,
  demoDiff,
  demoPlan,
  demoProject,
  demoTasks,
} from "./demo";

const navigation: { id: Page; label: string; icon: typeof Activity }[] = [
  { id: "dashboard", label: "Overview", icon: LayoutDashboard },
  { id: "projects", label: "Projects & people", icon: FolderKanban },
  { id: "new", label: "New task", icon: Plus },
  { id: "task", label: "Task & steps", icon: Layers3 },
  { id: "candidate", label: "Candidate & checks", icon: FileDiff },
  { id: "approvals", label: "Approval & recovery", icon: ShieldCheck },
  { id: "connections", label: "Connections", icon: Settings2 },
  { id: "audit", label: "Audit trail", icon: Activity },
];
const publicOnly = import.meta.env.VITE_PUBLIC_ONLY === "true";
const internalLink = (path: string) => (publicOnly ? "#" + path : path);

function DeploymentPending() {
  const { t } = useLocale();
  return (
    <div className="landing">
      <header className="public-header">
        <a className="brand" href={internalLink("/")}>
          IntelligenceAI
        </a>
        <LanguageSwitcher />
        <a href={internalLink("/demo")} className="button secondary">
          {t("Return to demo")}
        </a>
      </header>
      <main className="docs-page">
        <p className="eyebrow">{t("PRIVATE CONSOLE / NOT CONNECTED")}</p>
        <h1>
          {t("A private deployment")}
          <br />
          {t("is still required.")}
        </h1>
        <p className="lead">
          {t(
            "This site is a synthetic, read-only product walkthrough. There is no connected login, private database, Linux runner or model provider.",
          )}
        </p>
        <div className="notice">
          <LockKeyhole size={19} />
          <span>
            {t(
              "No credentials are collected here. Real project access requires a separately configured HTTPS server, PostgreSQL and verified OIDC.",
            )}
          </span>
        </div>
        <a href={internalLink("/demo")} className="button primary">
          {t("Explore the read-only demo")}
          <ArrowRight size={16} />
        </a>
      </main>
    </div>
  );
}
function route() {
  const value = publicOnly
    ? location.hash.slice(1) || "/"
    : location.pathname + location.search;
  const [path, search = ""] = value.split("?");
  const parts = path.split("/");
  const page = navigation.some((n) => n.id === parts[2])
    ? (parts[2] as Page)
    : "dashboard";
  const query = new URLSearchParams(search);
  return {
    path,
    mode: parts[1] === "app" ? "private" : "demo",
    page,
    project: query.get("project") || "",
    task: query.get("task") || "",
  };
}
function Badge({ state }: { state: string }) {
  const { t } = useLocale();
  const positive = state === "READY_FOR_APPROVAL";
  return (
    <span
      className={
        "badge " +
        (positive ? "purple" : state === "CANCELLED" ? "neutral" : "amber")
      }
    >
      <span className="status-dot" />
      {t(state.replaceAll("_", " ").toLowerCase())}
    </span>
  );
}
function Empty({ title, text }: { title: string; text: string }) {
  const { t } = useLocale();
  return (
    <div className="empty">
      <Layers3 size={28} />
      <h3>{t(title)}</h3>
      <p>{t(text)}</p>
    </div>
  );
}
function PlanView({ plan }: { plan: Plan }) {
  const { t } = useLocale();
  return (
    <>
      <div className="plan-flow">
        {plan.steps.map((step, index) => (
          <div className="plan-step" key={step.id}>
            <span className="step-number">{index + 1}</span>
            <strong>{step.id}</strong>
            <small>
              {t(step.role)} · {t(step.mode.replaceAll("_", " "))}
            </small>
            <span className="dependency">
              {step.depends_on.length
                ? t("after ") + step.depends_on.join(", ")
                : t("entry point")}
            </span>
          </div>
        ))}
      </div>
      <div className="notice">
        <ShieldCheck size={18} />
        <span>
          {t(plan.reason)}.{" "}
          <strong>
            {t("0 model calls · execution disabled ·")}{" "}
            {t(plan.evidence.toLowerCase())}
          </strong>
        </span>
      </div>
      <p className="muted">
        {t("Allowed scope:")} <code>{plan.scope.join(", ")}</code>
        {t(". The request never becomes a shell command.")}
      </p>
    </>
  );
}
function Landing({ docs = false }: { docs?: boolean }) {
  const { t } = useLocale();
  return (
    <div className="landing">
      <header className="public-header">
        <a className="brand" href={internalLink("/")}>
          <span className="brand-mark">
            <Layers3 size={21} />
          </span>
          Intelligence<span>AI</span>
        </a>
        <nav aria-label={t("Public navigation")}>
          <LanguageSwitcher />
          <a href={internalLink("/docs")}>{t("Documentation")}</a>
          <a href="https://github.com/yjj3019/IntelligenceAI">
            GitHub <ArrowUpRight size={14} />
          </a>
          <a className="button secondary" href={internalLink("/app")}>
            {t("Private console")}
            <LockKeyhole size={15} />
          </a>
        </nav>
      </header>
      {docs ? (
        <main className="docs-page">
          <p className="eyebrow">{t("PRODUCT & TRUST")}</p>
          <h1>
            {t("Know what runs.")}
            <br />
            {t("Know what is still unverified.")}
          </h1>
          <p className="lead">
            {t(
              "IntelligenceAI connects a typed plan, a candidate, evidence and an exact approval. This release adds a private project ledger and a synthetic interface walkthrough.",
            )}
          </p>
          <div className="feature-grid">
            <article>
              <ShieldCheck />
              <h2>{t("Exact approvals")}</h2>
              <p>
                {t(
                  "Candidate, policy, evidence, destination, generation and expiry must match. Every dispatch rechecks project permissions. Actual dispatch is disabled.",
                )}
              </p>
            </article>
            <article>
              <LockKeyhole />
              <h2>{t("Private by project")}</h2>
              <p>
                {t(
                  "OIDC identities map to operator-provisioned users. Server sessions and project membership protect status, logs, artifacts and updates.",
                )}
              </p>
            </article>
            <article>
              <CircleHelp />
              <h2>{t("Honest boundaries")}</h2>
              <p>
                {t(
                  "Provider execution, paid models and an OS sandbox are unverified. A fixture check is never displayed as model success. Meta AI is excluded.",
                )}
              </p>
            </article>
          </div>
          <p>
            <a href="https://github.com/yjj3019/IntelligenceAI/blob/main/README.en.md">
              {t("English guide ↗")}
            </a>{" "}
            ·{" "}
            <a href="https://github.com/yjj3019/IntelligenceAI/blob/main/README.md">
              {t("한국어 안내 ↗")}
            </a>{" "}
            ·{" "}
            <a href="https://github.com/yjj3019/IntelligenceAI/blob/main/SECURITY.md">
              {t("Security model ↗")}
            </a>
          </p>
          <a className="button primary" href={internalLink("/demo")}>
            {t("Explore the read-only demo")}
            <ArrowRight size={16} />
          </a>
        </main>
      ) : (
        <main>
          <section className="hero">
            <span className="pill">
              <span className="status-dot" />
              {t("DELIBERATE BY DESIGN")}
            </span>
            <h1>
              {t("Move work forward.")}
              <br />
              <span>{t("Keep the decisions yours.")}</span>
            </h1>
            <p>
              {t(
                "A clear path from request to review. Inspect every step, compare the candidate, and see the evidence before you approve.",
              )}
            </p>
            <div className="hero-actions">
              <a className="button primary" href={internalLink("/demo")}>
                {t("Explore the demo")}
                <ArrowRight size={17} />
              </a>
              <a className="button secondary" href={internalLink("/docs")}>
                {t("Read the documentation")}
              </a>
            </div>
            <small>
              {t(
                "Read-only synthetic data. No model calls or external actions.",
              )}
            </small>
          </section>
          <section className="hero-preview" aria-label={t("Product preview")}>
            <div className="preview-title">
              <span className="brand-mark">
                <Layers3 size={18} />
              </span>
              <strong>{t("Your work, in perspective")}</strong>
              <span className="badge neutral">{t("synthetic preview")}</span>
            </div>
            <div className="preview-columns">
              <div>
                <p className="eyebrow">{t("A REVIEWABLE WORKFLOW")}</p>
                <h2>{t("Configuration defaults")}</h2>
                <p className="muted">
                  {t("One candidate. Explicit evidence. A human decision.")}
                </p>
                <div className="preview-steps">
                  {["Plan", "Candidate", "Checks", "Approval"].map(
                    (label, i) => (
                      <div key={t(label)}>
                        <span>{i + 1}</span>
                        <strong>{t(label)}</strong>
                        <small>
                          {i === 3
                            ? t("Your decision")
                            : t("Visible & traceable")}
                        </small>
                      </div>
                    ),
                  )}
                </div>
              </div>
              <div className="preview-evidence">
                <ShieldCheck size={23} />
                <h3>{t("Evidence comes first.")}</h3>
                <p>
                  {t(
                    "See what was checked and what is still unverified. External execution remains disabled.",
                  )}
                </p>
                <span className="badge amber">{t("unverified evidence")}</span>
              </div>
            </div>
          </section>
          <section className="feature-grid">
            <article>
              <GitBranch />
              <h2>{t("Plans you can follow")}</h2>
              <p>
                {t(
                  "Explicit dependencies and a bounded scope make the next step clear.",
                )}
              </p>
            </article>
            <article>
              <FileDiff />
              <h2>{t("Changes you can inspect")}</h2>
              <p>
                {t(
                  "Review the candidate alongside checks, provenance and exact digests.",
                )}
              </p>
            </article>
            <article>
              <ShieldCheck />
              <h2>{t("Control you can trust")}</h2>
              <p>
                {t(
                  "Approvals bind to evidence. Recovery preserves uncertain execution.",
                )}
              </p>
            </article>
          </section>
        </main>
      )}
      <footer className="public-footer">
        <span>
          {t("IntelligenceAI · A considered approach to task control.")}
        </span>
        <a href={internalLink("/docs")}>{t("Capabilities & limitations")}</a>
      </footer>
    </div>
  );
}

export default function App() {
  return (
    <LocaleProvider>
      <WorkspaceApp />
    </LocaleProvider>
  );
}
function WorkspaceApp() {
  const { t, formatDate, formatNumber, timezone } = useLocale();
  const [current, setCurrent] = useState(route);
  const [menuOpen, setMenuOpen] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [task, setTask] = useState<Task | null>(null);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [connections, setConnections] = useState<Connections | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [authNeeded, setAuthNeeded] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [revision, setRevision] = useState(0);
  const [filter, setFilter] = useState("");
  const [form, setForm] = useState<TaskInput>({
    title: "",
    request: "",
    profile: "python-review",
  });
  const [plan, setPlan] = useState<Plan | null>(null);
  const [artifact, setArtifact] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<{
    projectId: string;
    taskId: string;
    title: string;
    userId: string;
    routeKey: string;
    epoch: number;
  } | null>(null);
  const [approvalIntent, setApprovalIntent] = useState<{
    projectId: string;
    taskId: string;
    userId: string;
    binding: Binding;
    key: string;
    status: "prepared" | "uncertain" | "recorded";
  } | null>(null);
  const [approvalNow, setApprovalNow] = useState(() =>
    Math.floor(Date.now() / 1000),
  );
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const navigationPanel = useRef<HTMLElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const pending = useRef(false);
  const requestKeys = useRef(new Map<string, string>());
  const requestEpoch = useRef(0);
  const identityId = useRef<string | null>(null);
  const signingOut = useRef(false);
  const active = current.mode === "private";
  const isShell =
    /^\/(demo|app)(\/|$)/.test(current.path) && !(publicOnly && active);
  const selectedProject = current.project || projects[0]?.id || "";
  const canWrite = project?.role === "owner" || project?.role === "operator";
  const canApprove = project?.role === "owner" || project?.role === "approver";

  function routeIdentity(value = route()) {
    return (
      value.mode + "|" + value.path + "|" + value.project + "|" + value.task
    );
  }
  function clearPrivate(preserveRetry = false) {
    requestEpoch.current += 1;
    if (!preserveRetry) identityId.current = null;
    pending.current = false;
    if (!preserveRetry) requestKeys.current.clear();
    setBusy(false);
    setLoading(false);
    setSession(null);
    setProjects([]);
    setProject(null);
    setTasks([]);
    setTask(null);
    setAudit([]);
    setConnections(null);
    setArtifact("");
    setFeedback("");
    setConfirm(null);
    if (!preserveRetry) setApprovalIntent(null);
    setPlan(null);
    setForm({ title: "", request: "", profile: "python-review" });
  }
  useEffect(() => {
    if (!approvalIntent) return;
    setApprovalNow(Math.floor(Date.now() / 1000));
    const timer = setTimeout(
      () => setApprovalNow(Math.floor(Date.now() / 1000)),
      Math.max(1, approvalIntent.binding.expires_at * 1000 - Date.now()),
    );
    return () => clearTimeout(timer);
  }, [approvalIntent?.binding.expires_at]);

  useEffect(() => {
    if (menuOpen)
      navigationPanel.current?.querySelector<HTMLAnchorElement>("a")?.focus();
  }, [menuOpen]);

  function navigate(
    page: Page,
    taskId = current.task,
    projectId = selectedProject,
  ) {
    setConfirm(null);
    const query = new URLSearchParams();
    if (projectId) query.set("project", projectId);
    if (taskId) query.set("task", taskId);
    history.pushState(
      {},
      "",
      internalLink("/" + (active ? "app" : "demo") + "/" + page + "?" + query),
    );
    setCurrent(route());
    setMenuOpen(false);
    setFeedback("");
    setError("");
  }
  useEffect(() => {
    const pop = () => {
      setConfirm(null);
      setCurrent(route());
      setError("");
      setFeedback("");
    };
    window.addEventListener("popstate", pop);
    window.addEventListener("hashchange", pop);
    return () => {
      window.removeEventListener("popstate", pop);
      window.removeEventListener("hashchange", pop);
    };
  }, []);
  useEffect(() => {
    heading.current?.focus();
  }, [current.page]);
  useEffect(() => {
    if (confirm) dialog.current?.showModal();
    else dialog.current?.close();
  }, [confirm]);

  useEffect(() => {
    if (!isShell || signingOut.current) return;
    let alive = true;
    const epoch = ++requestEpoch.current;
    setConfirm(null);
    pending.current = false;
    setBusy(false);
    setLoading(true);
    setError("");
    setArtifact("");
    setTask(null);
    setProject(null);
    setTasks([]);
    setAudit([]);
    setConnections(null);
    if (!active) {
      if (identityId.current) clearPrivate();
      setSession(null);
      setProjects([demoProject]);
      setProject(demoProject);
      setTasks(demoTasks);
      setTask(
        demoTasks.find((item) => item.id === current.task) || demoTasks[0],
      );
      setAudit(demoAudit);
      setConnections(demoConnections);
      setLoading(false);
      return;
    }
    void (async () => {
      try {
        const identity = await api<Session>("/session");
        if (!alive || epoch !== requestEpoch.current) return;
        const list = await api<Project[]>("/projects");
        if (!alive || epoch !== requestEpoch.current) return;
        if (identityId.current && identityId.current !== identity.user.id) {
          requestKeys.current.clear();
          setApprovalIntent(null);
          setConfirm(null);
          setPlan(null);
          setForm({ title: "", request: "", profile: "python-review" });
        }
        identityId.current = identity.user.id;
        setSession(identity);
        setProjects(list);
        setAuthNeeded(false);
        const id = current.project || list[0]?.id;
        if (!id) {
          setLoading(false);
          return;
        }
        const base = "/projects/" + encodeURIComponent(id);
        const [detail, taskList, events, config] = await Promise.all([
          api<Project>(base),
          api<Task[]>(base + "/tasks"),
          api<Audit[]>(base + "/audit"),
          api<Connections>(base + "/connections"),
        ]);
        const selected = current.task || taskList[0]?.id;
        const taskDetail = selected
          ? await api<Task>(base + "/tasks/" + encodeURIComponent(selected))
          : null;
        if (!alive || epoch !== requestEpoch.current) return;
        setProject(detail);
        setTasks(taskList);
        setAudit(events);
        setConnections(config);
        setTask(taskDetail);
      } catch (err) {
        if (!alive || epoch !== requestEpoch.current) return;
        clearPrivate(
          !(err instanceof ApiError && [401, 403, 404].includes(err.status)),
        );
        setError(message(err));
        setAuthNeeded(err instanceof ApiError && err.status === 401);
      } finally {
        if (alive && epoch === requestEpoch.current) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [active, current.project, current.task, revision, isShell]);

  useEffect(() => {
    if (!active || !task || !session || error) return;
    let alive = true;
    const epoch = requestEpoch.current;
    let stream: EventSource | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const path =
      "/api/projects/" +
      encodeURIComponent(task.project_id) +
      "/tasks/" +
      encodeURIComponent(task.id) +
      "/events";
    const snapshot = (event: MessageEvent) => {
      if (!alive || epoch !== requestEpoch.current) return;
      try {
        setTask(JSON.parse(event.data) as Task);
      } catch {
        setError("Update could not be read. Refresh to reconnect.");
        stream?.close();
      }
    };
    const connect = () => {
      if (!alive || epoch !== requestEpoch.current) return;
      stream = new EventSource(path);
      stream.addEventListener("snapshot", snapshot);
      // Each finite snapshot reauthorizes. Confirm access before scheduling another stream.
      stream.onerror = () => {
        if (!alive || epoch !== requestEpoch.current) return;
        stream?.close();
        void api<Task>(path.slice(4, -7))
          .then((updated) => {
            if (!alive || epoch !== requestEpoch.current) return;
            setTask(updated);
            timer = setTimeout(connect, 5000);
          })
          .catch((err) => {
            if (!alive || epoch !== requestEpoch.current) return;
            clearPrivate(
              !(
                err instanceof ApiError && [401, 403, 404].includes(err.status)
              ),
            );
            setError(message(err));
            setAuthNeeded(err instanceof ApiError && err.status === 401);
          });
      };
    };
    connect();
    return () => {
      alive = false;
      stream?.close();
      clearTimeout(timer);
    };
  }, [active, task?.id, session, revision, error]);

  useEffect(() => {
    setArtifact("");
    if (current.page !== "candidate" || !task?.artifacts?.length) return;
    if (!active) {
      setArtifact(demoDiff);
      return;
    }
    let alive = true;
    const epoch = requestEpoch.current;
    const artifactId = task.artifacts[0].id;
    void fetch(
      "/api/projects/" +
        encodeURIComponent(task.project_id) +
        "/tasks/" +
        encodeURIComponent(task.id) +
        "/artifacts/" +
        encodeURIComponent(artifactId),
      { credentials: "same-origin", cache: "no-store" },
    )
      .then(async (response) => {
        if (!response.ok)
          throw new ApiError(response.status, "artifact_unavailable");
        const text = await response.text();
        if (alive && epoch === requestEpoch.current) setArtifact(text);
      })
      .catch((err) => {
        if (alive && epoch === requestEpoch.current) {
          setError(message(err));
          setArtifact("");
          if (err instanceof ApiError && [401, 403, 404].includes(err.status)) {
            clearPrivate();
            setAuthNeeded(err.status === 401);
          }
        }
      });
    return () => {
      alive = false;
    };
  }, [current.page, task?.id, active, revision]);

  function keyFor(operation: string, payload: unknown) {
    const fingerprint =
      session?.user.id +
      ":" +
      project?.id +
      ":" +
      operation +
      JSON.stringify(payload);
    if (!requestKeys.current.has(fingerprint))
      requestKeys.current.set(fingerprint, crypto.randomUUID());
    return requestKeys.current.get(fingerprint)!;
  }
  async function perform(
    operation: string,
    payload: unknown = {},
    method = "POST",
    explicitKey?: string,
  ) {
    if (
      !active ||
      !session ||
      !project ||
      pending.current ||
      signingOut.current
    )
      return;
    const epoch = requestEpoch.current;
    pending.current = true;
    setBusy(true);
    setError("");
    setFeedback("");
    try {
      const result = await mutation<{ id?: string; state?: string }>(
        `/projects/${encodeURIComponent(project.id)}/${operation}`,
        session.csrf,
        explicitKey || keyFor(operation, payload),
        payload,
        method,
      );
      if (epoch !== requestEpoch.current) return;
      if (explicitKey)
        setApprovalIntent((intent) =>
          intent?.key === explicitKey
            ? { ...intent, status: "recorded" }
            : intent,
        );
      // Preserve uncertain retries, then release the key after a confirmed response.
      requestKeys.current.delete(
        session.user.id +
          ":" +
          project.id +
          ":" +
          operation +
          JSON.stringify(payload),
      );
      setFeedback(
        result.state === "CANCEL_REQUESTED"
          ? "Cancellation requested. Termination has not been confirmed."
          : "Saved to the private ledger. Execution remains disabled.",
      );
      if (operation === "tasks" && result.id) {
        setForm({ title: "", request: "", profile: "python-review" });
        setPlan(null);
        navigate("task", result.id);
      }
      setRevision((v) => v + 1);
    } catch (err) {
      if (epoch !== requestEpoch.current) return;
      setError(message(err));
      if (err instanceof ApiError && [401, 403, 404].includes(err.status)) {
        clearPrivate();
        setAuthNeeded(err.status === 401);
      }
    } finally {
      if (epoch === requestEpoch.current) {
        pending.current = false;
        setBusy(false);
      }
    }
  }
  async function previewForm() {
    if (pending.current || signingOut.current) return;
    const epoch = requestEpoch.current;
    setPlan(null);
    setError("");
    setFeedback("");
    if (!active) {
      setPlan(demoPlan(form));
      return;
    }
    if (!session || !project) return;
    pending.current = true;
    setBusy(true);
    try {
      const preview = await mutation<Plan>(
        `/projects/${encodeURIComponent(project.id)}/preview`,
        session.csrf,
        crypto.randomUUID(),
        form,
      );
      if (epoch === requestEpoch.current) setPlan(preview);
    } catch (err) {
      if (epoch !== requestEpoch.current) return;
      if (err instanceof ApiError && [401, 403, 404].includes(err.status))
        clearPrivate();
      setError(message(err));
    } finally {
      if (epoch === requestEpoch.current) {
        pending.current = false;
        setBusy(false);
      }
    }
  }
  async function signOut() {
    if (!session || signingOut.current) return;
    const csrf = session.csrf;
    signingOut.current = true;
    clearPrivate();
    const epoch = requestEpoch.current;
    setAuthNeeded(false);
    setFeedback("Signing out. Private requests are invalidated.");
    try {
      await mutation("/logout", csrf, crypto.randomUUID(), {});
      if (epoch !== requestEpoch.current) return;
      setAuthNeeded(true);
      setError("You have signed out.");
    } catch (err) {
      if (epoch !== requestEpoch.current) return;
      setAuthNeeded(true);
      setError(message(err));
    } finally {
      signingOut.current = false;
      if (epoch === requestEpoch.current) setFeedback("");
    }
  }
  const visibleTasks = tasks.filter(
    (item) =>
      (active ? item.title : t(item.title))
        .toLowerCase()
        .includes(filter.toLowerCase()) ||
      t(item.state.replaceAll("_", " ").toLowerCase())
        .toLowerCase()
        .includes(filter.toLowerCase()),
  );
  const title = t(navigation.find((n) => n.id === current.page)!.label);
  const taskPath = task ? "tasks/" + encodeURIComponent(task.id) + "/" : "";
  const binding: Omit<Binding, "expires_at"> | null =
    task?.candidate_digest && task.evidence_digest && project
      ? {
          candidate_digest: task.candidate_digest,
          policy_digest: project.policy_digest,
          evidence_digest: task.evidence_digest,
          destination_id: task.destination_id,
          generation: task.generation,
        }
      : null;
  const intentTargetMatches =
    !!approvalIntent &&
    approvalIntent.projectId === project?.id &&
    approvalIntent.taskId === task?.id &&
    approvalIntent.userId === session?.user.id;
  const intentBindingMatches =
    intentTargetMatches &&
    !!binding &&
    Object.entries(binding).every(
      ([key, value]) => approvalIntent?.binding[key as keyof Binding] === value,
    );
  const intentExpired =
    !!approvalIntent &&
    Math.max(approvalNow, Math.floor(Date.now() / 1000)) >=
      approvalIntent.binding.expires_at;
  const reviewReady =
    active &&
    canApprove &&
    !!task?.evidence_verified &&
    task.state === "READY_FOR_APPROVAL" &&
    !!binding;
  function prepareApproval() {
    if (!reviewReady || !binding || !session || !project || !task || busy)
      return;
    setApprovalIntent({
      projectId: project.id,
      taskId: task.id,
      userId: session.user.id,
      binding: { ...binding, expires_at: Math.floor(Date.now() / 1000) + 600 },
      key: crypto.randomUUID(),
      status: "prepared",
    });
    setError("");
    setFeedback("");
  }
  async function checkApprovalReceipt() {
    if (
      !approvalIntent ||
      !intentTargetMatches ||
      !active ||
      !canApprove ||
      busy ||
      pending.current ||
      signingOut.current
    )
      return;
    const epoch = requestEpoch.current;
    const intent = approvalIntent;
    pending.current = true;
    setBusy(true);
    setError("");
    setFeedback("");
    try {
      const receipt = await api<{ found: boolean }>(
        "/projects/" +
          encodeURIComponent(intent.projectId) +
          "/tasks/" +
          encodeURIComponent(intent.taskId) +
          "/approval-receipts/" +
          encodeURIComponent(intent.key),
      );
      if (epoch !== requestEpoch.current) return;
      if (receipt.found) {
        setApprovalIntent((currentIntent) =>
          currentIntent?.key === intent.key
            ? { ...currentIntent, status: "recorded" }
            : currentIntent,
        );
        setFeedback(
          "This request receipt was recorded. Review the current task grant and expiry.",
        );
        setRevision((value) => value + 1);
      } else {
        setFeedback(
          "No recorded receipt was found. Checking did not submit approval.",
        );
      }
    } catch (err) {
      if (epoch !== requestEpoch.current) return;
      setError(message(err));
      if (err instanceof ApiError && [401, 403, 404].includes(err.status)) {
        clearPrivate();
        setAuthNeeded(err.status === 401);
      }
    } finally {
      if (epoch === requestEpoch.current) {
        pending.current = false;
        setBusy(false);
      }
    }
  }
  function submitApproval() {
    if (
      !approvalIntent ||
      !intentTargetMatches ||
      !active ||
      !canApprove ||
      busy ||
      pending.current
    )
      return;
    if (!reviewReady || !intentBindingMatches || intentExpired) return;
    setApprovalIntent({ ...approvalIntent, status: "uncertain" });
    void perform(
      "tasks/" + encodeURIComponent(approvalIntent.taskId) + "/approve",
      approvalIntent.binding,
      "POST",
      approvalIntent.key,
    );
  }

  if (publicOnly && active) return <DeploymentPending />;
  if (!isShell) return <Landing docs={current.path === "/docs"} />;
  return (
    <div className="app-shell">
      <a
        className="skip-link"
        href="#main"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        {t("Skip to main content")}
      </a>
      <aside
        id="workspace-navigation"
        ref={navigationPanel}
        className={"sidebar " + (menuOpen ? "open" : "")}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            setMenuOpen(false);
            menuButton.current?.focus();
          }
        }}
      >
        <a className="brand" href={internalLink("/")}>
          <span className="brand-mark">
            <Layers3 size={21} />
          </span>
          Intelligence<span>AI</span>
        </a>
        <div className="workspace-picker">
          <span className="workspace-avatar">
            {project?.name.charAt(0) || "I"}
          </span>
          <div>
            <strong>{project?.name || t("Private workspace")}</strong>
            <small>
              {active
                ? t("Private project console")
                : t("Synthetic demo workspace")}
            </small>
          </div>
          <ChevronDown size={15} />
        </div>
        <p className="nav-label">{t("WORKSPACE")}</p>
        <nav aria-label={t("Workspace navigation")}>
          {navigation.map(({ id, label, icon: Icon }) => (
            <a
              key={id}
              href={internalLink("/" + (active ? "app" : "demo") + "/" + id)}
              aria-current={current.page === id ? "page" : undefined}
              className={current.page === id ? "selected" : ""}
              onClick={(event) => {
                event.preventDefault();
                navigate(id);
              }}
            >
              <Icon size={18} />
              {t(label)}
              {id === "approvals" && (
                <span className="nav-count">
                  {
                    tasks.filter((item) => item.state === "READY_FOR_APPROVAL")
                      .length
                  }
                </span>
              )}
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="trust-note">
            <ShieldCheck size={19} />
            <strong>{t("Evidence before effects")}</strong>
            <p>{t("Live providers and external actions are disabled.")}</p>
            <a href={internalLink("/docs")}>
              {t("Understand the boundaries")}
              <ArrowUpRight size={13} />
            </a>
          </div>
          <a className="support-link" href={internalLink("/docs")}>
            <CircleHelp size={17} />
            {t("Documentation")}
          </a>
          <div className="identity">
            <span className="user-avatar">
              {session?.user.name.charAt(0) || "D"}
            </span>
            <div>
              <strong>
                {session?.user.name ||
                  t(active ? "Signed-out visitor" : "Demo visitor")}
              </strong>
              <small>
                {active
                  ? t(project?.role || "Sign-in required")
                  : t("Read-only access")}
              </small>
            </div>
            {session && (
              <button className="text-button" onClick={() => void signOut()}>
                {t("Sign out")}
              </button>
            )}
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            ref={menuButton}
            aria-controls="workspace-navigation"
            aria-label={menuOpen ? t("Close navigation") : t("Open navigation")}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen(!menuOpen)}
          >
            {menuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
          <span className="breadcrumb">
            {t("Workspace")}
            <span>/</span> {title}
          </span>
          <div className="topbar-actions">
            <LanguageSwitcher />
            <span className={"mode-chip " + (active ? "private" : "")}>
              {active ? <LockKeyhole size={13} /> : <Sparkles size={13} />}
              {active ? t("Private console") : t("Read-only demo")}
            </span>
            <a href={internalLink(active ? "/demo" : "/app")}>
              {active
                ? t("View demo")
                : publicOnly
                  ? t("Private deployment")
                  : t("Sign in")}{" "}
              <ArrowUpRight size={14} />
            </a>
          </div>
        </header>
        <div className={"mode-banner " + (active ? "private" : "")}>
          <ShieldCheck size={17} />
          <span>
            {active
              ? t(
                  "Private ledger · Execution disabled. No paid model calls, repository execution or external effects.",
                )
              : t(
                  "Synthetic walkthrough · Sample tasks and evidence. No model has run. All demo mutations are disabled.",
                )}
          </span>
          <a href={internalLink("/docs")}>{t("Learn more")}</a>
        </div>
        <main id="main" className="workspace-main" tabIndex={-1}>
          <div className="page-heading">
            <div>
              <p className="eyebrow">
                {current.page === "dashboard"
                  ? t("A CLEAR VIEW OF YOUR WORK")
                  : t("WORKSPACE / ") + title.toUpperCase()}
              </p>
              <h1 ref={heading} tabIndex={-1}>
                {current.page === "dashboard"
                  ? t("Make room for thoughtful work.")
                  : title}
              </h1>
              <p>
                {current.page === "dashboard"
                  ? t(
                      "A plan, a candidate, the evidence. Everything you need for the next decision.",
                    )
                  : t(
                      "Inspect the details. Keep every decision tied to its context.",
                    )}
              </p>
            </div>
            <div className="heading-actions">
              <button
                className="button secondary"
                onClick={() => setRevision((v) => v + 1)}
                disabled={loading || busy}
              >
                <RefreshCw size={15} />
                {t("Refresh")}
              </button>
              {current.page !== "new" && (
                <button
                  className="button primary"
                  onClick={() => navigate("new")}
                >
                  <Plus size={16} />
                  {t("New task")}
                </button>
              )}
            </div>
          </div>
          {error && (
            <div className="error notice" role="alert">
              <CircleHelp size={19} />
              <span>{t(error)}</span>
              {authNeeded ? (
                <a href="/auth/login">
                  {t("Sign in securely")}
                  <ArrowRight size={15} />
                </a>
              ) : (
                <button
                  className="text-button"
                  onClick={() => setRevision((v) => v + 1)}
                >
                  {t("Reconnect")}
                </button>
              )}
            </div>
          )}
          {feedback && (
            <div className="success notice" role="status">
              <Check size={17} />
              {t(feedback)}
            </div>
          )}
          {loading ? (
            <div className="loading" role="status">
              <RefreshCw size={22} />
              {t("Loading saved workspace…")}
            </div>
          ) : active && !project ? (
            <Empty
              title={
                authNeeded
                  ? t("Your private workspace starts with sign-in.")
                  : t("No accessible project")
              }
              text={t(
                "Only provisioned OIDC identities and authorized project members can view private work. Use the synthetic demo to explore the interface.",
              )}
            />
          ) : (
            <>
              {current.page === "dashboard" && (
                <>
                  <div className="stat-grid">
                    <article className="stat-card">
                      <div>
                        <span>{t("Tracked tasks")}</span>
                        <Layers3 size={18} />
                      </div>
                      <strong>{formatNumber(tasks.length, 2)}</strong>
                      <small>
                        {active
                          ? t("Saved in your project ledger")
                          : t("Illustrative sample tasks")}
                      </small>
                    </article>
                    <article className="stat-card">
                      <div>
                        <span>{t("Awaiting review")}</span>
                        <ShieldCheck size={18} />
                      </div>
                      <strong>
                        {formatNumber(
                          tasks.filter(
                            (item) => item.state === "READY_FOR_APPROVAL",
                          ).length,
                          2,
                        )}
                      </strong>
                      <small>{t("Evidence must be verified first")}</small>
                    </article>
                    <article className="stat-card">
                      <div>
                        <span>{t("Needs attention")}</span>
                        <Clock3 size={18} />
                      </div>
                      <strong>
                        {formatNumber(
                          tasks.filter((item) =>
                            [
                              "BLOCKED",
                              "FAILED",
                              "CANCEL_REQUESTED",
                              "NEEDS_RECONCILIATION",
                            ].includes(item.state),
                          ).length,
                          2,
                        )}
                      </strong>
                      <small>{t("Clear reasons, deliberate recovery")}</small>
                    </article>
                    <article className="stat-card">
                      <div>
                        <span>{t("Model calls")}</span>
                        <Code2 size={18} />
                      </div>
                      <strong>{formatNumber(0, 2)}</strong>
                      <small>{t("Live execution is disabled")}</small>
                    </article>
                  </div>
                  <div className="overview-grid">
                    <section className="panel task-panel">
                      <div className="panel-heading">
                        <div>
                          <h2>{t("Recent tasks")}</h2>
                          <p>{t("From request to a considered decision.")}</p>
                        </div>
                        <span className="subtle-tag">
                          {formatNumber(tasks.length)} {t("tasks")}
                        </span>
                      </div>
                      <div className="table-toolbar">
                        <label className="search">
                          <Search size={17} />
                          <input
                            aria-label={t("Search tasks")}
                            placeholder={t("Search by task or status…")}
                            value={filter}
                            onChange={(event) => setFilter(event.target.value)}
                          />
                        </label>
                        <span className="muted">{t("Latest first")}</span>
                      </div>
                      {visibleTasks.length ? (
                        <div className="task-table">
                          <div className="table-head">
                            <span>{t("TASK")}</span>
                            <span>{t("STATUS")}</span>
                            <span>{t("GENERATION")}</span>
                          </div>
                          {visibleTasks.map((item) => (
                            <button
                              className="task-row"
                              key={item.id}
                              onClick={() => navigate("task", item.id)}
                            >
                              <span className="task-title">
                                <span className="task-icon">
                                  <GitBranch size={17} />
                                </span>
                                <span>
                                  <strong>
                                    {active ? item.title : t(item.title)}
                                  </strong>
                                  <small>
                                    {item.id.slice(0, 12)} ·{" "}
                                    {active
                                      ? t("private ledger")
                                      : t("synthetic sample")}
                                  </small>
                                </span>
                              </span>
                              <Badge state={item.state} />
                              <span className="generation">
                                v{item.generation}
                                <ArrowUpRight size={16} />
                              </span>
                            </button>
                          ))}
                        </div>
                      ) : (
                        <Empty
                          title={
                            filter
                              ? t("No matching tasks")
                              : t("A clear starting point")
                          }
                          text={
                            filter
                              ? t("Try another task name or status.")
                              : t(
                                  "Create a plan preview to define the next piece of work.",
                                )
                          }
                        />
                      )}
                    </section>
                    <section className="panel decision-panel">
                      <span className="panel-icon">
                        <ShieldCheck size={22} />
                      </span>
                      <p className="eyebrow">{t("THE NEXT DECISION")}</p>
                      <h2>{t("Review with the whole picture.")}</h2>
                      <p>
                        {t(
                          "A candidate is only one part of the story. Start with the scope, check the evidence, then decide.",
                        )}
                      </p>
                      <ul className="check-list">
                        <li>
                          <Check size={15} />
                          {t("Candidate & policy digests")}
                        </li>
                        <li>
                          <Check size={15} />
                          {t("Evidence & generation")}
                        </li>
                        <li>
                          <Check size={15} />
                          {t("Destination & expiry")}
                        </li>
                      </ul>
                      <button
                        className="button secondary"
                        onClick={() => navigate("approvals")}
                      >
                        {t("Open review queue")}
                        <ArrowRight size={15} />
                      </button>
                      <small>
                        {t(
                          "Real approvals remain unavailable until verified evidence exists.",
                        )}
                      </small>
                    </section>
                  </div>
                  <section className="panel activity-panel">
                    <div className="panel-heading">
                      <div>
                        <h2>{t("Workspace activity")}</h2>
                        <p>{t("Every saved decision leaves a trace.")}</p>
                      </div>
                      <button
                        className="text-button"
                        onClick={() => navigate("audit")}
                      >
                        {t("View audit trail")}
                        <ArrowRight size={15} />
                      </button>
                    </div>
                    <div className="activity-row">
                      {audit.length ? (
                        audit.slice(0, 3).map((event) => (
                          <div key={event.id}>
                            <span className="activity-icon">
                              <Activity size={16} />
                            </span>
                            <div>
                              <strong>
                                {event.event.replaceAll(".", " · ")}
                              </strong>
                              <small>
                                {active
                                  ? t("Private audit event")
                                  : t("Synthetic event")}{" "}
                                · {formatDate(event.created_at, true)}
                              </small>
                            </div>
                          </div>
                        ))
                      ) : (
                        <p className="muted">{t("No saved events yet.")}</p>
                      )}
                    </div>
                  </section>
                </>
              )}
              {current.page === "projects" && (
                <section className="panel">
                  <div className="panel-heading">
                    <div>
                      <h2>{t("Projects & membership")}</h2>
                      <p>
                        {t(
                          "Authorization is checked on each request, including artifacts and updates.",
                        )}
                      </p>
                    </div>
                    <Users size={22} />
                  </div>
                  <label className="field project-select">
                    {t("Project")}
                    <select
                      aria-label={t("Choose project")}
                      value={project?.id || ""}
                      onChange={(event) =>
                        navigate("projects", "", event.target.value)
                      }
                    >
                      {projects.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="member-list">
                    {project?.members?.map((member) => (
                      <div className="member-row" key={member.user_id}>
                        <span className="user-avatar">
                          {member.name.charAt(0)}
                        </span>
                        <div>
                          <strong>{member.name}</strong>
                          <small>{member.user_id}</small>
                        </div>
                        <span className="subtle-tag">{t(member.role)}</span>
                        {active &&
                          project.role === "owner" &&
                          member.user_id !== session?.user.id && (
                            <label className="role-select">
                              <span className="sr-only">
                                {t("Role for")}
                                {member.name}
                              </span>
                              <select
                                disabled={busy}
                                value={member.role}
                                onChange={(event) =>
                                  void perform(
                                    "members",
                                    {
                                      user_id: member.user_id,
                                      role: event.target.value as Role,
                                    },
                                    "PUT",
                                  )
                                }
                              >
                                {[
                                  "viewer",
                                  "operator",
                                  "approver",
                                  "owner",
                                  "revoked",
                                ].map((role) => (
                                  <option key={role} value={role}>
                                    {t(role)}
                                  </option>
                                ))}
                              </select>
                            </label>
                          )}
                      </div>
                    ))}
                  </div>
                  <div className="notice">
                    <LockKeyhole size={18} />
                    <span>
                      {t(
                        "New identities and projects require operator provisioning. Browser input cannot select a principal or tenant.",
                      )}
                    </span>
                  </div>
                </section>
              )}
              {current.page === "new" && (
                <div className="two-columns">
                  <section className="panel form-panel">
                    <h2>{t("Define a bounded task")}</h2>
                    <p className="muted">
                      {t(
                        "Describe the outcome. Inspect the fixed plan before saving.",
                      )}
                    </p>
                    <form
                      onSubmit={(event) => {
                        event.preventDefault();
                        void previewForm();
                      }}
                    >
                      <label className="field">
                        {t("Task title")}
                        <input
                          required
                          minLength={3}
                          maxLength={120}
                          value={form.title}
                          onChange={(event) => {
                            setForm({ ...form, title: event.target.value });
                            setPlan(null);
                          }}
                          placeholder={t("A small, reviewable piece of work")}
                        />
                      </label>
                      <label className="field">
                        {t("What should change?")}
                        <textarea
                          required
                          minLength={3}
                          maxLength={4000}
                          rows={6}
                          value={form.request}
                          onChange={(event) => {
                            setForm({ ...form, request: event.target.value });
                            setPlan(null);
                          }}
                          placeholder={t(
                            "Describe the intended result and its scope. Do not include secrets.",
                          )}
                        />
                      </label>
                      <label className="field">
                        {t("Review profile")}
                        <select
                          value={form.profile}
                          onChange={(event) => {
                            setForm({
                              ...form,
                              profile: event.target
                                .value as TaskInput["profile"],
                            });
                            setPlan(null);
                          }}
                        >
                          <option value="python-review">
                            {t("Python · static review")}
                          </option>
                          <option value="json-review">
                            {t("JSON · configuration review")}
                          </option>
                        </select>
                      </label>
                      <button
                        className="button primary"
                        type="submit"
                        disabled={busy || (active && !canWrite)}
                      >
                        {busy ? t("Preparing…") : t("Preview plan")}
                        <ArrowRight size={16} />
                      </button>
                    </form>
                  </section>
                  <section className="panel">
                    <h2>{t("Plan preview")}</h2>
                    {plan ? (
                      <>
                        <PlanView plan={plan} />
                        <button
                          className="button primary"
                          disabled={!active || !canWrite || busy}
                          onClick={() => void perform("tasks", form)}
                        >
                          {busy ? t("Saving…") : t("Save to private ledger")}
                          <Plus size={16} />
                        </button>
                        <p className="muted">
                          {active
                            ? t(
                                "Saving creates a held job. No runner or model starts.",
                              )
                            : t(
                                "The demo supports previews only. Sign in to save a private task.",
                              )}
                        </p>
                      </>
                    ) : (
                      <Empty
                        title={t("Make the next step visible")}
                        text={t(
                          "Your preview will show dependencies, allowed scope and execution limits.",
                        )}
                      />
                    )}
                  </section>
                </div>
              )}
              {current.page === "task" &&
                (task ? (
                  <>
                    <section className="panel">
                      <div className="panel-heading">
                        <div>
                          <h2>{active ? task.title : t(task.title)}</h2>
                          <p>
                            {task.id}
                            {t("· generation")}
                            {task.generation}
                          </p>
                        </div>
                        <Badge state={task.state} />
                      </div>
                      <p className="task-request">
                        {active ? task.request : t(task.request)}
                      </p>
                      <PlanView plan={task.plan} />
                      <div className="button-row">
                        <button
                          className="button secondary"
                          onClick={() => navigate("candidate", task.id)}
                        >
                          <FileDiff size={16} />
                          {t("Inspect candidate")}
                        </button>
                        <button
                          className="button secondary"
                          onClick={() => navigate("approvals", task.id)}
                        >
                          <ShieldCheck size={16} />
                          {t("Review & recovery")}
                        </button>
                        <button
                          className="button danger"
                          disabled={
                            !active ||
                            !canWrite ||
                            busy ||
                            task.state === "CANCELLED"
                          }
                          onClick={() => {
                            if (project && session)
                              setConfirm({
                                projectId: project.id,
                                taskId: task.id,
                                title: task.title,
                                userId: session.user.id,
                                routeKey: routeIdentity(),
                                epoch: requestEpoch.current,
                              });
                          }}
                        >
                          {t("Request cancellation")}
                        </button>
                      </div>
                    </section>
                    <section className="panel provenance">
                      <h2>{t("Provenance & execution")}</h2>
                      <dl>
                        <div>
                          <dt>{t("Source")}</dt>
                          <dd>{task.source}</dd>
                        </div>
                        <div>
                          <dt>{t("Model calls")}</dt>
                          <dd>{task.model_calls}</dd>
                        </div>
                        <div>
                          <dt>{t("Evidence")}</dt>
                          <dd>
                            {task.evidence_verified
                              ? t("Verified static evidence")
                              : t("UNVERIFIED")}
                          </dd>
                        </div>
                        <div>
                          <dt>{t("External effects")}</dt>
                          <dd>{t("DISABLED")}</dd>
                        </div>
                      </dl>
                      <p className="muted">
                        {t(
                          active
                            ? "No model or sandbox has executed. This ledger records held work only."
                            : "A sample status is an illustration. It does not mean a model or sandbox has executed.",
                        )}
                      </p>
                    </section>
                  </>
                ) : (
                  <Empty
                    title={t("No task selected")}
                    text={t("Create a task or select one from the overview.")}
                  />
                ))}
              {current.page === "candidate" &&
                (task ? (
                  <div className="two-columns candidate-layout">
                    <section className="panel diff-panel">
                      <div className="panel-heading">
                        <div>
                          <h2>{t("Candidate diff")}</h2>
                          <p>
                            {active
                              ? t("Private artifact · rendered as plain text")
                              : t("Synthetic diff · illustration only")}
                          </p>
                        </div>
                        <FileDiff size={20} />
                      </div>
                      {artifact ? (
                        <pre
                          className="diff"
                          tabIndex={0}
                          aria-label={t("Candidate diff")}
                        >
                          {artifact.split("\n").map((line, index) => (
                            <span
                              key={index}
                              className={
                                line.startsWith("+")
                                  ? "addition"
                                  : line.startsWith("-")
                                    ? "deletion"
                                    : ""
                              }
                            >
                              <span className="line-number">{index + 1}</span>
                              {line || " "}
                              {"\n"}
                            </span>
                          ))}
                        </pre>
                      ) : (
                        <Empty
                          title={t("No candidate artifact yet")}
                          text={t(
                            "This task is held. No runner has produced a candidate.",
                          )}
                        />
                      )}
                    </section>
                    <section className="panel">
                      <h2>{t("Evidence & checks")}</h2>
                      <div className="evidence-item">
                        <ShieldCheck size={21} />
                        <div>
                          <strong>{t("Secret scan")}</strong>
                          <p>{t("UNVERIFIED · no real scanner receipt")}</p>
                        </div>
                      </div>
                      <div className="evidence-item">
                        <Code2 size={21} />
                        <div>
                          <strong>{t("Provider execution")}</strong>
                          <p>{t("DISABLED · no model has run")}</p>
                        </div>
                      </div>
                      <div className="evidence-item">
                        <LockKeyhole size={21} />
                        <div>
                          <strong>{t("OS sandbox")}</strong>
                          <p>{t("UNVERIFIED · no containment claim")}</p>
                        </div>
                      </div>
                      <h3>{t("Candidate digest")}</h3>
                      <code className="digest">
                        {task.candidate_digest || t("No candidate fingerprint")}
                      </code>
                      <h3>{t("Evidence digest")}</h3>
                      <code className="digest">
                        {task.evidence_digest || t("No verified evidence")}
                      </code>
                      <button
                        className="button secondary"
                        onClick={() => navigate("approvals", task.id)}
                      >
                        {t("Review approval binding")}
                        <ArrowRight size={15} />
                      </button>
                    </section>
                  </div>
                ) : (
                  <Empty
                    title={t("No candidate selected")}
                    text={t("Select a saved task from the overview.")}
                  />
                ))}
              {current.page === "approvals" &&
                (task ? (
                  <div className="two-columns">
                    <section className="panel">
                      <h2>{t("Approve an exact review")}</h2>
                      <p className="muted">
                        {t(
                          "A review grant does not enable publishing, paid models or execution.",
                        )}
                      </p>
                      <dl className="binding-list">
                        <div>
                          <dt>{t("Candidate")}</dt>
                          <dd>
                            <code>
                              {task.candidate_digest || t("Unavailable")}
                            </code>
                          </dd>
                        </div>
                        <div>
                          <dt>{t("Policy")}</dt>
                          <dd>
                            <code>{project?.policy_digest}</code>
                          </dd>
                        </div>
                        <div>
                          <dt>{t("Evidence")}</dt>
                          <dd>
                            <code>
                              {task.evidence_digest || t("UNVERIFIED")}
                            </code>
                          </dd>
                        </div>
                        <div>
                          <dt>{t("Destination")}</dt>
                          <dd>private-review</dd>
                        </div>
                        <div>
                          <dt>{t("Generation")}</dt>
                          <dd>{task.generation}</dd>
                        </div>
                        <div>
                          <dt>{t("Grant duration")}</dt>
                          <dd>
                            {t("10 minutes · checked again before dispatch")}
                          </dd>
                        </div>
                      </dl>
                      <div className="notice">
                        <ShieldCheck size={18} />
                        <span>
                          {task.evidence_verified
                            ? t(
                                "Static evidence is verified. No live model or sandbox claim is implied.",
                              )
                            : t(
                                "Approval blocked: verified evidence is required.",
                              )}
                        </span>
                      </div>
                      {task.approval && (
                        <p className="muted">
                          {t("Review grant recorded. Expiry:")}{" "}
                          {formatDate(task.approval.expires_at)}
                          {t(". Dispatch remains disabled.")}
                        </p>
                      )}
                      {approvalIntent && intentTargetMatches && (
                        <div className="notice">
                          <span>
                            {t("Approval intent expiry:")}{" "}
                            {formatDate(approvalIntent.binding.expires_at)}
                            <br />
                            {t(
                              intentExpired
                                ? "This intent expired. Check its receipt before preparing a new intent."
                                : approvalIntent.status === "uncertain"
                                  ? "The response was not confirmed. Retry this exact intent or check its recorded receipt."
                                  : approvalIntent.status === "recorded"
                                    ? "This request receipt was recorded. Review the current task grant and expiry."
                                    : "Candidate, destination, expiry and request key are fixed for this intent.",
                            )}
                          </span>
                        </div>
                      )}
                      <div className="button-row">
                        <button
                          className="button secondary"
                          disabled={
                            !reviewReady ||
                            busy ||
                            (intentBindingMatches &&
                              !intentExpired &&
                              approvalIntent?.status !== "recorded")
                          }
                          onClick={prepareApproval}
                        >
                          {t(
                            approvalIntent
                              ? "Prepare new approval intent"
                              : "Prepare approval intent",
                          )}
                        </button>
                        <button
                          className="button primary"
                          disabled={
                            !active ||
                            !canApprove ||
                            !task.evidence_verified ||
                            task.state !== "READY_FOR_APPROVAL" ||
                            !intentBindingMatches ||
                            intentExpired ||
                            approvalIntent?.status === "recorded" ||
                            busy
                          }
                          onClick={() => submitApproval()}
                        >
                          {t(
                            approvalIntent?.status === "uncertain"
                              ? "Resend the same approval request"
                              : "Record review approval",
                          )}
                        </button>
                        {intentTargetMatches && approvalIntent && (
                          <button
                            className="button secondary"
                            disabled={!active || !canApprove || busy}
                            onClick={() => void checkApprovalReceipt()}
                          >
                            {t("Check recorded approval receipt")}
                          </button>
                        )}
                        <button
                          className="button secondary"
                          disabled={!active || !canApprove || busy}
                          onClick={() => void perform(taskPath + "reject")}
                        >
                          {t("Reject review")}
                        </button>
                      </div>
                    </section>
                    <section className="panel">
                      <span className="panel-icon">
                        <RefreshCw size={22} />
                      </span>
                      <h2>{t("Recover with certainty")}</h2>
                      <p className="muted">
                        {t(
                          "An unstarted held job can be prepared again. Uncertain execution requires a real termination receipt and keeps its lease.",
                        )}
                      </p>
                      <div className="recovery-state">
                        <Badge state={task.state} />
                        <span>
                          {t("Generation")}
                          {task.generation}
                        </span>
                      </div>
                      <button
                        className="button secondary"
                        disabled={
                          !active ||
                          !canWrite ||
                          busy ||
                          !["BLOCKED", "FAILED", "CANCELLED"].includes(
                            task.state,
                          )
                        }
                        onClick={() => void perform(taskPath + "recover")}
                      >
                        {t("Prepare recovery")}
                        <RefreshCw size={15} />
                      </button>
                      <p className="muted">
                        {t(
                          "Recovery invalidates old approvals and increments the generation. Execution remains disabled.",
                        )}
                      </p>
                    </section>
                  </div>
                ) : (
                  <Empty
                    title={t("No reviews to inspect")}
                    text={t(
                      "Select a task to inspect its approval and recovery state.",
                    )}
                  />
                ))}
              {current.page === "connections" && (
                <>
                  <section className="panel">
                    <h2>{t("Connection & environment status")}</h2>
                    <p className="muted">
                      {t(
                        "Configuration belongs to the server operator. Credentials and paths are never entered here.",
                      )}
                    </p>
                    <div className="connection-grid">
                      {connections &&
                        Object.entries(connections)
                          .filter(([key]) => key !== "execution_enabled")
                          .map(([key, value]) => (
                            <article key={key}>
                              <span className="connection-icon">
                                <LockKeyhole size={18} />
                              </span>
                              <h3>{t(key.replaceAll("_", " "))}</h3>
                              <span className="subtle-tag">
                                {t(String(value))}
                              </span>
                            </article>
                          ))}
                    </div>
                    <div className="notice">
                      <CircleHelp size={18} />
                      <span>
                        {t(
                          "Claude, Codex, Grok, Gemini and other planned integrations remain disabled until provider permissions and Linux containment are verified. Meta AI is excluded.",
                        )}
                      </span>
                    </div>
                  </section>
                  <section className="panel">
                    <h2>{t("Deployment prerequisites")}</h2>
                    <p className="muted">
                      {t(
                        "A canonical HTTPS origin, PostgreSQL database, OIDC issuer and isolated Linux runner need independent validation. The public demo contains no private API or write endpoint.",
                      )}
                    </p>
                    <a
                      className="button secondary"
                      href={internalLink("/docs")}
                    >
                      {t("Read the deployment boundaries")}
                      <ArrowUpRight size={15} />
                    </a>
                  </section>
                </>
              )}
              {current.page === "audit" && (
                <section className="panel">
                  <div className="panel-heading">
                    <div>
                      <h2>{t("Project audit trail")}</h2>
                      <p>
                        {active
                          ? t(
                              "Redacted before persistence. Scoped to the current project.",
                            )
                          : t(
                              "Synthetic events. No real actor activity or model execution.",
                            )}
                      </p>
                    </div>
                    <Activity size={22} />
                  </div>
                  {audit.length ? (
                    <div className="audit-list">
                      {audit.map((event) => (
                        <article key={event.id}>
                          <span className="activity-icon">
                            <Activity size={17} />
                          </span>
                          <div>
                            <strong>{event.event}</strong>
                            <small>
                              {event.actor_id} · {formatDate(event.created_at)}
                            </small>
                            <pre>{JSON.stringify(event.detail, null, 2)}</pre>
                          </div>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <Empty
                      title={t("No audit events yet")}
                      text={t(
                        "Saved submissions and decisions will appear here.",
                      )}
                    />
                  )}
                </section>
              )}
            </>
          )}
          <footer className="workspace-footer">
            <span>
              <span className="status-dot" />{" "}
              {active
                ? t("Project-scoped private ledger")
                : t("Synthetic data · read-only demo")}
            </span>
            <span>
              {t("Timezone")}: {timezone} · {t("Execution disabled")}
              <LockKeyhole size={12} />
            </span>
          </footer>
        </main>
      </div>
      <dialog
        ref={dialog}
        aria-labelledby="cancel-title"
        onCancel={() => setConfirm(null)}
        onClose={() => setConfirm(null)}
      >
        <div className="dialog-content">
          <h2 id="cancel-title">{t("Request task cancellation?")}</h2>
          {confirm && (
            <p>
              <strong>{confirm.title}</strong>
              <br />
              <code>{confirm.taskId}</code>
            </p>
          )}
          <p>
            {t(
              "The server confirms cancellation only if the queue item has never started. Otherwise the state stays “Cancellation requested” until termination is verified.",
            )}
          </p>
          <div className="button-row">
            <button
              className="button secondary"
              autoFocus
              onClick={() => setConfirm(null)}
            >
              {t("Keep task")}
            </button>
            <button
              className="button danger"
              disabled={!confirm || busy}
              onClick={() => {
                const target = confirm;
                setConfirm(null);
                if (
                  !target ||
                  target.epoch !== requestEpoch.current ||
                  target.routeKey !== routeIdentity() ||
                  target.taskId !== task?.id ||
                  target.projectId !== project?.id ||
                  target.userId !== session?.user.id
                )
                  return;
                void perform(
                  "tasks/" + encodeURIComponent(target.taskId) + "/cancel",
                );
              }}
            >
              {t("Confirm cancellation")}
            </button>
          </div>
        </div>
      </dialog>
    </div>
  );
}
