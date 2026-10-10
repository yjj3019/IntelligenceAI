import { useEffect, useRef, useState } from "react";
import { api, ApiError, message, mutation } from "./api";
import { useLocale } from "./i18n";

type Quote = {
  actor_id: string;
  project_id: string;
  task_id: string;
  generation: number;
  provider: "claude";
  model: string;
  effort: string;
  max_calls: 1;
  currency: "USD";
  cost_ceiling_microusd: number;
  expires_at: number;
  candidate_digest: string;
  evidence_digest: string;
  policy_digest: string;
  destination_id: "private-model-review";
};
type RequestRecord = {
  id: string;
  state: "QUOTED" | "APPROVED" | "REQUESTED" | "STALE";
  quote: Quote;
  quote_digest: string;
  live_model: "NOTRUN";
};
type Status = {
  profiles: {
    id: string;
    name: string;
    model: string;
    effort: string;
    cost_ceiling_microusd: number;
  }[];
  requests: RequestRecord[];
  can_consent: boolean;
  execution_enabled: false;
  live_model: "NOTRUN";
  blockers: string[];
  generation: number;
};

function checkedStatus(value: Status): Status {
  if (
    !value ||
    !Array.isArray(value.profiles) ||
    !Array.isArray(value.requests) ||
    value.execution_enabled !== false ||
    value.live_model !== "NOTRUN"
  )
    throw new ApiError(503, "paid_status_unavailable");
  return value;
}

export function PaidReviewPanel({
  projectId,
  taskId,
  generation,
  csrf,
  onAuthorityLost,
}: {
  projectId: string;
  taskId: string;
  generation: number;
  csrf: string;
  onAuthorityLost: (status: number) => void;
}) {
  const { t, formatDate } = useLocale();
  const [status, setStatus] = useState<Status | null>(null);
  const [record, setRecord] = useState<RequestRecord | null>(null);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [now, setNow] = useState(() => Date.now() / 1000);
  const alive = useRef(false);
  const epoch = useRef(0);
  const pending = useRef(false);
  const keys = useRef(new Map<string, string>());
  const authority = useRef(onAuthorityLost);
  authority.current = onAuthorityLost;
  const path = `/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/paid-review`;
  const lost = (err: unknown) => {
    if (err instanceof ApiError && [401, 403, 404].includes(err.status)) {
      setStatus(null);
      setRecord(null);
      keys.current.clear();
      authority.current(err.status);
    }
  };
  useEffect(() => {
    alive.current = true;
    const version = ++epoch.current;
    const controller = new AbortController();
    void api<Status>(path, { signal: controller.signal })
      .then((value) => {
        if (!alive.current || epoch.current !== version) return;
        checkedStatus(value);
        setStatus(value);
        setSelected(value.profiles[0]?.id || "");
        setRecord(
          value.requests.find(
            (item) =>
              item.quote.generation === generation && item.state !== "STALE",
          ) ||
            value.requests.find(
              (item) => item.quote.generation === generation,
            ) ||
            null,
        );
      })
      .catch((err) => {
        if (
          !alive.current ||
          epoch.current !== version ||
          controller.signal.aborted
        )
          return;
        setError(message(err));
        if (err instanceof ApiError && [401, 403, 404].includes(err.status))
          authority.current(err.status);
      });
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => {
      alive.current = false;
      epoch.current++;
      controller.abort();
      clearInterval(timer);
    };
  }, [path, generation]);
  async function refresh() {
    if (pending.current) return;
    pending.current = true;
    const version = epoch.current;
    setBusy(true);
    setError("");
    try {
      const value = await api<Status>(path);
      if (!alive.current || epoch.current !== version) return;
      checkedStatus(value);
      setStatus(value);
      setRecord(
        value.requests.find(
          (item) =>
            item.quote.generation === generation && item.state !== "STALE",
        ) ||
          value.requests.find((item) => item.quote.generation === generation) ||
          null,
      );
    } catch (err) {
      if (alive.current && epoch.current === version) {
        setError(message(err));
        lost(err);
      }
    } finally {
      pending.current = false;
      if (alive.current && epoch.current === version) setBusy(false);
    }
  }
  async function submit(action: "quote" | "approve" | "request") {
    if (pending.current || !status?.can_consent || !alive.current) return;
    const body =
      action === "quote"
        ? { profile_id: selected }
        : record
          ? {
              request_id: record.id,
              quote_digest: record.quote_digest,
            }
          : null;
    if (
      !body ||
      (action !== "quote" && (!record || record.quote.expires_at <= now))
    )
      return;
    const fingerprint = JSON.stringify([
      action,
      body,
      action === "quote" ? record?.id : null,
    ]);
    if (!keys.current.has(fingerprint))
      keys.current.set(fingerprint, crypto.randomUUID());
    pending.current = true;
    const version = epoch.current;
    setBusy(true);
    setError("");
    try {
      const value = await mutation<RequestRecord>(
        path + "/" + action,
        csrf,
        keys.current.get(fingerprint)!,
        body,
      );
      if (alive.current && epoch.current === version) setRecord(value);
    } catch (err) {
      if (alive.current && epoch.current === version) {
        setError(message(err));
        lost(err);
      }
    } finally {
      pending.current = false;
      if (alive.current && epoch.current === version) setBusy(false);
    }
  }
  const quote = record?.quote;
  const expired =
    !quote ||
    quote.expires_at <= now ||
    quote.generation !== generation ||
    record?.state === "STALE";
  const money = (value: number) => `USD ${(value / 1_000_000).toFixed(6)}`;
  return (
    <section className="panel" aria-labelledby="paid-review-title">
      <p className="eyebrow">{t("PAID REVIEW / OPERATOR SETUP PENDING")}</p>
      <h2 id="paid-review-title">{t("Approve one bounded model review")}</h2>
      <p className="muted">
        {t(
          "Each execution needs a fresh approval. This screen records consent and one request; it does not start a model or supply credentials.",
        )}
      </p>
      <div className="notice">
        <span>
          {t(
            "Live model: NOTRUN. Signed controls, verified Linux runtime and separate credential confirmation are still required.",
          )}
        </span>
      </div>
      {error && <p role="alert">{t(error)}</p>}
      {status && !status.profiles.length && (
        <p>
          {t(
            "An operator must provision an existing model profile and budget. Model names, pricing and credentials are never guessed.",
          )}
        </p>
      )}
      {!!status?.profiles.length && (
        <label className="field">
          {t("Operator model profile")}
          <select
            value={selected}
            disabled={busy || !!record}
            onChange={(e) => setSelected(e.target.value)}
          >
            {status.profiles.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} · {item.model} · {item.effort} ·{" "}
                {money(item.cost_ceiling_microusd)}
              </option>
            ))}
          </select>
        </label>
      )}
      {quote && (
        <dl className="binding-list">
          <div>
            <dt>{t("Actor")}</dt>
            <dd>
              <code>{quote.actor_id}</code>
            </dd>
          </div>
          <div>
            <dt>{t("Project / task")}</dt>
            <dd>
              <code>
                {quote.project_id} / {quote.task_id}
              </code>
            </dd>
          </div>
          <div>
            <dt>{t("Generation")}</dt>
            <dd>{quote.generation}</dd>
          </div>
          <div>
            <dt>{t("Provider / model / effort")}</dt>
            <dd>
              {quote.provider} / {quote.model} / {quote.effort}
            </dd>
          </div>
          <div>
            <dt>{t("Maximum calls")}</dt>
            <dd>{quote.max_calls}</dd>
          </div>
          <div>
            <dt>{t("Maximum cost")}</dt>
            <dd>{money(quote.cost_ceiling_microusd)}</dd>
          </div>
          <div>
            <dt>{t("Candidate")}</dt>
            <dd>
              <code>{quote.candidate_digest}</code>
            </dd>
          </div>
          <div>
            <dt>{t("Evidence")}</dt>
            <dd>
              <code>{quote.evidence_digest}</code>
            </dd>
          </div>
          <div>
            <dt>{t("Policy")}</dt>
            <dd>
              <code>{quote.policy_digest}</code>
            </dd>
          </div>
          <div>
            <dt>{t("Destination")}</dt>
            <dd>{quote.destination_id}</dd>
          </div>
          <div>
            <dt>{t("Expires")}</dt>
            <dd>{formatDate(quote.expires_at)}</dd>
          </div>
        </dl>
      )}
      {record && (
        <p role="status">
          {t(
            record.state === "REQUESTED"
              ? "One execution request recorded. Provider NOTRUN; operator admission is pending."
              : expired
                ? "This paid intent expired. Refresh before preparing a new approval."
                : record.state === "APPROVED"
                  ? "Consent recorded for this exact quote. No model has started."
                  : "Review this fixed quote before approving its cost ceiling.",
          )}
        </p>
      )}
      <div className="button-row">
        <button
          className="button secondary"
          disabled={
            busy || !status?.can_consent || !selected || (!!record && !expired)
          }
          onClick={() => void submit("quote")}
        >
          {t("Prepare paid review quote")}
        </button>
        <button
          className="button secondary"
          disabled={
            busy ||
            !status?.can_consent ||
            expired ||
            record?.state !== "QUOTED"
          }
          onClick={() => void submit("approve")}
        >
          {t("Approve this cost ceiling")}
        </button>
        <button
          className="button primary"
          disabled={
            busy ||
            !status?.can_consent ||
            expired ||
            record?.state !== "APPROVED"
          }
          onClick={() => void submit("request")}
        >
          {t("Request this review once")}
        </button>
        <button
          className="button secondary"
          disabled={busy}
          onClick={() => void refresh()}
        >
          {t("Check saved paid request")}
        </button>
      </div>
      <p className="muted">
        {t(
          "If a response is interrupted, check saved state or retry the same request. Navigation never sends an approval. Cancellation and recovery invalidate the current task binding.",
        )}
      </p>
    </section>
  );
}
