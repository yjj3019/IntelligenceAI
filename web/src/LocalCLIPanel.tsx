import { useEffect, useRef, useState } from "react";
import { api, ApiError, message, mutation } from "./api";
import { useLocale } from "./i18n";
import type { Artifact } from "./types";

type Usage = {
  measured_at: number | null;
  source?: string;
  unit?: string;
  completeness?: string;
  values?: Record<string, number | null>;
  status?: string;
  limits?: {
    limit_id: string | null;
    windows: Record<
      string,
      {
        usedPercent: number | null;
        windowDurationMins: number | null;
        resetsAt: number | null;
      }
    >;
  }[];
};
type Profile = {
  id: string;
  provider: string;
  version: string;
  scope: string;
  transport?: string;
  installation: string;
  authentication?: string;
  availability: string;
  can_execute: boolean;
  restriction?: string;
  quota?: Usage;
};
type RecordValue = {
  id: string;
  profile_id: string;
  generation: number;
  state: string;
  binding_digest: string;
  binding: {
    provider: string;
    candidate_digest: string;
    evidence_digest: string;
    policy_digest: string;
    expires_at: number;
    max_cli_invocations: number;
    wall_seconds: number;
    result_destination: string;
    payload?: {
      payload_bytes: number;
      payload_chars: number;
      candidate_files: number;
      unique_contents: number;
      payload_sha256: string;
      truncated: boolean;
    };
  };
  result: null | {
    availability: string;
    scope: string;
    live_model: string;
    local_termination_confirmed: boolean;
    remote_cancellation: string;
    device_cleanup_reported?: boolean;
    usage?: Usage;
  };
};
type Status = {
  profiles: Profile[];
  requests: RecordValue[];
  generation: number;
  can_consent: boolean;
};

export function LocalCLIPanel({
  projectId,
  taskId,
  generation,
  csrf,
  artifacts = [],
  onAuthorityLost,
}: {
  projectId: string;
  taskId: string;
  generation: number;
  csrf: string;
  artifacts?: Artifact[];
  onAuthorityLost: (status: number) => void;
}) {
  const { t, formatDate } = useLocale();
  const [status, setStatus] = useState<Status | null>(null);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [resultText, setResultText] = useState("");
  const [resultError, setResultError] = useState("");
  const [resultId, setResultId] = useState("");
  const resultEpoch = useRef(0);
  const alive = useRef(false);
  const epoch = useRef(0);
  const pending = useRef(false);
  const keys = useRef(new Map<string, string>());
  const authority = useRef(onAuthorityLost);
  authority.current = onAuthorityLost;
  const path = `/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/local-cli`;
  const lost = (err: unknown) => {
    if (err instanceof ApiError && [401, 403, 404].includes(err.status)) {
      setStatus(null);
      setResultText("");
      setResultId("");
      ++resultEpoch.current;
      setSelected("");
      keys.current.clear();
      authority.current(err.status);
    }
  };
  const checked = (value: Status) => {
    if (
      !value ||
      !Array.isArray(value.profiles) ||
      !Array.isArray(value.requests) ||
      value.generation !== generation
    )
      throw new ApiError(409, "cli_status_changed");
    return value;
  };
  useEffect(() => {
    alive.current = true;
    setResultText("");
    setResultId("");
    setResultError("");
    const version = ++epoch.current;
    const controller = new AbortController();
    void api<Status>(path, { signal: controller.signal })
      .then((value) => {
        if (alive.current && epoch.current === version)
          setStatus(checked(value));
      })
      .catch((err) => {
        if (
          alive.current &&
          epoch.current === version &&
          !controller.signal.aborted
        ) {
          lost(err);
          setError(message(err));
        }
      });
    return () => {
      alive.current = false;
      ++epoch.current;
      ++resultEpoch.current;
      controller.abort();
      keys.current.clear();
    };
    // The parent key includes session, policy, role, task and generation.
  }, [path, generation, csrf]);
  const perform = async (
    action: "refresh" | "prepare" | "approve",
    body: unknown = {},
  ) => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    const version = epoch.current;
    try {
      if (action !== "refresh") {
        const intent = JSON.stringify([action, body]);
        const key = keys.current.get(intent) || crypto.randomUUID();
        keys.current.set(intent, key);
        await mutation(path + "/" + action, csrf, key, body);
      }
      if (!alive.current || version !== epoch.current) return;
      const value = checked(await api<Status>(path));
      if (alive.current && version === epoch.current) setStatus(value);
    } catch (err) {
      if (alive.current && version === epoch.current) {
        lost(err);
        setError(message(err));
      }
    } finally {
      if (alive.current && version === epoch.current) {
        pending.current = false;
        setBusy(false);
      }
    }
  };
  const record = status?.requests.find(
    (value) => value.generation === generation,
  );
  const openResult = async (id: string) => {
    if (
      !artifacts.some((value) => value.id === id && value.kind === "cli-result")
    )
      return;
    const version = epoch.current;
    const resultVersion = ++resultEpoch.current;
    setResultText("");
    setResultError("");
    setResultId(id);
    try {
      const response = await fetch(
        `/api/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/artifacts/${encodeURIComponent(id)}`,
        { credentials: "same-origin", cache: "no-store" },
      );
      if (!response.ok)
        throw new ApiError(response.status, "artifact_unavailable");
      const text = await response.text();
      if (
        alive.current &&
        epoch.current === version &&
        resultEpoch.current === resultVersion
      )
        setResultText(text);
    } catch (err) {
      if (
        alive.current &&
        epoch.current === version &&
        resultEpoch.current === resultVersion
      ) {
        lost(err);
        setResultError(message(err));
        if (err instanceof ApiError && [401, 403, 404].includes(err.status))
          setError(message(err));
      }
    }
  };
  const stateLabel = (value: string) =>
    t(
      (
        {
          AVAILABLE: "Result received",
          PARTIAL_FAILURE: "Completed with diagnostics",
          REQUEST_FAILED: "Native request failed",
          EXECUTION_ERROR: "Result could not be verified",
          AUTHENTICATION_REQUIRED: "Native login required",
          USAGE_LIMITED: "Provider usage limit reached",
          UNSUPPORTED_ITEM: "Unexpected native item",
          OUTPUT_TRUNCATED: "Output exceeded the limit",
          AUTHORITY_CHANGED: "Execution authority changed",
          AUTHORITY_OR_EXECUTION_CHANGED:
            "Execution authority or launch changed",
          TIMEOUT: "Execution time limit reached",
          NEVER_STARTED: "Confirmed never started",
          UNVERIFIED: "Availability unverified",
          VERSION_UNVERIFIED: "CLI version unverified",
        } as Record<string, string>
      )[value] || value,
    );
  const profile = status?.profiles.find(
    (value) => value.id === (record?.profile_id || selected),
  );
  const showUsage = (usage?: Usage) => (
    <div className="muted">
      <p>
        {usage?.source || t("No official usage snapshot")} ·{" "}
        {t(usage?.status || usage?.completeness || "Not provided")}
        {usage?.measured_at != null && <> · {formatDate(usage.measured_at)}</>}
      </p>
      {usage?.values && (
        <dl className="metadata">
          {Object.entries(usage.values).map(([name, value]) => (
            <div key={name}>
              <dt>{name}</dt>
              <dd>
                {value ?? t("Unknown")} {usage.unit}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {usage?.limits?.map((limit) => (
        <dl className="metadata" key={limit.limit_id || "default"}>
          <dt>{limit.limit_id || t("Unknown")}</dt>
          {Object.entries(limit.windows).map(([name, window]) => (
            <div key={name}>
              <dt>
                {name} · {window.windowDurationMins ?? t("Unknown")} min
              </dt>
              <dd>
                {window.usedPercent == null
                  ? t("Unknown")
                  : `${window.usedPercent}% ${t("used")}`}{" "}
                · {t("Resets")}:{" "}
                {window.resetsAt == null
                  ? t("Unknown")
                  : formatDate(window.resetsAt)}
              </dd>
            </div>
          ))}
        </dl>
      ))}
    </div>
  );
  return (
    <section className="card" aria-labelledby="local-cli-title">
      <p className="eyebrow">{t("YOUR LOCAL CLI")}</p>
      <h2 id="local-cli-title">{t("Local CLI review")}</h2>
      <p>
        {t(
          "Use your own installed CLI and existing login. Installation and login status do not prove a model request will work.",
        )}
      </p>
      <p className="muted">
        {t(
          "One CLI invocation, 60 seconds, one local worker, no automatic retry. Native internal requests and account usage remain provider-managed.",
        )}
      </p>
      {error && <p role="alert">{t(error)}</p>}
      {!status && !error && (
        <p role="status">{t("Loading saved CLI status")}</p>
      )}
      {status && (
        <>
          {status.profiles.length === 0 && (
            <p>
              {t(
                "No owner-bound local CLI is registered. Your credentials stay on your own machine.",
              )}
            </p>
          )}
          <label>
            {t("Your CLI")}
            <select
              value={record?.profile_id || selected}
              disabled={busy || !!record}
              onChange={(event) => setSelected(event.target.value)}
            >
              <option value="">{t("Choose CLI")}</option>
              {status.profiles.map((value) => (
                <option key={value.id} value={value.id}>
                  {value.provider} {value.version} ·{" "}
                  {stateLabel(value.availability)}
                </option>
              ))}
            </select>
          </label>
          {profile && (
            <>
              <p>
                {profile.installation} ·{" "}
                {profile.authentication || t("Authentication not checked")} ·{" "}
                {stateLabel(profile.availability)} · {profile.scope}
              </p>
              {profile.transport === "OUTBOUND_PC" && (
                <p className="notice">
                  {t(
                    "This profile runs on your approved PC over outbound HTTPS. The direct DB worker is separate.",
                  )}
                </p>
              )}
              {profile.restriction && (
                <p role="status">{profile.restriction}</p>
              )}
              <h3>{t("Account usage snapshot")}</h3>
              {showUsage(profile.quota)}
            </>
          )}
          {!record && (
            <button
              disabled={busy || !status.can_consent || !profile?.can_execute}
              onClick={() => void perform("prepare", { profile_id: selected })}
            >
              {t("Prepare CLI approval")}
            </button>
          )}
          {record && (
            <>
              <p role="status">
                {t("Saved CLI request")}: {record.state}
              </p>
              <dl className="metadata">
                <div>
                  <dt>{t("Provider")}</dt>
                  <dd>{record.binding.provider}</dd>
                </div>
                <div>
                  <dt>{t("Candidate / evidence / policy")}</dt>
                  <dd className="digest">
                    {record.binding.candidate_digest}
                    <br />
                    {record.binding.evidence_digest}
                    <br />
                    {record.binding.policy_digest}
                  </dd>
                </div>
                <div>
                  <dt>{t("Approval expires")}</dt>
                  <dd>{formatDate(record.binding.expires_at)}</dd>
                </div>
                <div>
                  <dt>{t("Result destination")}</dt>
                  <dd>{record.binding.result_destination}</dd>
                </div>
                {record.binding.payload && (
                  <div>
                    <dt>{t("Bound input payload")}</dt>
                    <dd>
                      {record.binding.payload.payload_bytes} bytes ·{" "}
                      {record.binding.payload.payload_chars} chars ·{" "}
                      {record.binding.payload.candidate_files} files /{" "}
                      {record.binding.payload.unique_contents} contents
                    </dd>
                  </div>
                )}
              </dl>
              {record.state === "PREPARED" && (
                <button
                  disabled={
                    busy ||
                    !status.can_consent ||
                    record.binding.expires_at <= Date.now() / 1000
                  }
                  onClick={() =>
                    void perform("approve", {
                      request_id: record.id,
                      binding_digest: record.binding_digest,
                    })
                  }
                >
                  {t("Approve and queue once")}
                </button>
              )}
              {record.result && (
                <>
                  <p>
                    {stateLabel(record.result.availability)} ·{" "}
                    <code>{record.result.availability}</code> ·{" "}
                    {t(record.result.scope)} · {record.result.live_model}
                  </p>
                  {record.result.scope === "PC_REPORTED" && (
                    <p className="notice">
                      {t("Device cleanup reported")}:{" "}
                      {String(record.result.device_cleanup_reported)}.{" "}
                      {t("Device results and usage are unverified reports.")}
                    </p>
                  )}
                  {record.result.scope === "PC_REPORTED" && (
                    <p className="muted">
                      {t(
                        "PC usage includes only input/output tokens. Cache, reasoning and measurement time are not provided.",
                      )}
                    </p>
                  )}
                  <p>
                    {t("Local process stopped")}:{" "}
                    {String(record.result.local_termination_confirmed)} ·{" "}
                    {t("Remote cancellation")}:{" "}
                    {record.result.remote_cancellation}
                  </p>
                  <h3>{t("This execution's tokens")}</h3>
                  {showUsage(record.result.usage)}
                  <p>
                    {t(
                      "Results are private project artifacts. Refresh the task to view imported results.",
                    )}
                  </p>
                </>
              )}
            </>
          )}
        </>
      )}
      {status && artifacts.some((value) => value.kind === "cli-result") && (
        <section aria-label={t("Private CLI results")}>
          <h3>{t("Private CLI results")}</h3>
          {artifacts
            .filter((value) => value.kind === "cli-result")
            .map((value) => (
              <button
                key={value.id}
                className="button secondary"
                onClick={() => void openResult(value.id)}
              >
                {t("Open CLI result")}: {value.name}
              </button>
            ))}
          {resultError && <p role="alert">{t(resultError)}</p>}
          {resultId && !resultText && !resultError && (
            <p role="status">{t("Loading private result")}</p>
          )}
          {resultText && (
            <pre aria-label={t("CLI result text")}>{resultText}</pre>
          )}
        </section>
      )}
      <button
        className="button secondary"
        disabled={busy}
        onClick={() => void perform("refresh")}
      >
        {t("Refresh saved CLI status")}
      </button>
      <p className="muted">
        {t(
          "Refreshing saved status never starts a model. Missing usage is unknown, not zero or unlimited.",
        )}
      </p>
      <p className="muted">
        {t(
          "Payload size and reported tokens are separate measurements. Actual token savings have not been measured.",
        )}
      </p>
    </section>
  );
}
