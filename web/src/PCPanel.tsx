import { useEffect, useRef, useState } from "react";
import { api, ApiError, message, mutation } from "./api";
import { useLocale } from "./i18n";

type Device = {
  id: string;
  provider: string;
  state: string;
  expires_at: number;
  manifest_digest: string | null;
  manifest: null | {
    version: string;
    scope: string;
    binary_digest: string;
    runtime_digest: string;
  };
  pairing_code?: string | null;
};

export function PCPanel({
  projectId,
  csrf,
  onAuthorityLost,
}: {
  projectId: string;
  csrf: string;
  onAuthorityLost: (status: number) => void;
}) {
  const { t, formatDate } = useLocale();
  const [devices, setDevices] = useState<Device[]>([]);
  const [provider, setProvider] = useState("codex");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState("");
  const [reviewed, setReviewed] = useState("");
  const epoch = useRef(0);
  const pending = useRef(false);
  const reads = useRef(0);
  const readPending = useRef(false);
  const keys = useRef(new Map<string, string>());
  const lost = useRef(onAuthorityLost);
  lost.current = onAuthorityLost;
  const path = `/projects/${encodeURIComponent(projectId)}/pcs`;

  useEffect(() => {
    const generation = ++epoch.current;
    const sequence = ++reads.current;
    readPending.current = true;
    setReading(true);
    api<Device[]>(path)
      .then((value) => {
        if (!Array.isArray(value)) throw new Error("invalid device response");
        if (epoch.current === generation && reads.current === sequence)
          setDevices(value);
      })
      .catch((err: unknown) => {
        if (epoch.current !== generation || reads.current !== sequence) return;
        setError(message(err));
        if (err instanceof ApiError && [401, 403, 404].includes(err.status))
          lost.current(err.status);
      })
      .finally(() => {
        if (epoch.current === generation && reads.current === sequence) {
          readPending.current = false;
          setReading(false);
        }
      });
    return () => {
      epoch.current++;
      reads.current++;
    };
  }, [path]);

  async function act(action: string, body: unknown) {
    if (pending.current) return;
    const generation = epoch.current;
    // A mutation supersedes every earlier read without delaying explicit revocation.
    reads.current++;
    readPending.current = false;
    setReading(false);
    pending.current = true;
    setBusy(true);
    setError("");
    if (!keys.current.has(action))
      keys.current.set(action, crypto.randomUUID());
    try {
      const result = await mutation<Device>(
        path + "/" + action,
        csrf,
        keys.current.get(action)!,
        body,
      );
      if (epoch.current !== generation) return;
      keys.current.delete(action);
      setCode(result.pairing_code || "");
      setReviewed("");
      const sequence = ++reads.current;
      const latest = await api<Device[]>(path);
      if (!Array.isArray(latest)) throw new Error("invalid device response");
      if (epoch.current === generation && reads.current === sequence)
        setDevices(latest);
    } catch (err) {
      if (epoch.current !== generation) return;
      setError(message(err));
      if (err instanceof ApiError && [401, 403, 404].includes(err.status)) {
        setDevices([]);
        setCode("");
        setReviewed("");
        lost.current(err.status);
      }
    } finally {
      pending.current = false;
      if (epoch.current === generation) setBusy(false);
    }
  }

  async function refresh() {
    if (pending.current || readPending.current) return;
    const generation = epoch.current;
    const sequence = ++reads.current;
    readPending.current = true;
    setReading(true);
    try {
      const latest = await api<Device[]>(path);
      if (!Array.isArray(latest)) throw new Error("invalid device response");
      if (epoch.current === generation && reads.current === sequence) {
        setDevices(latest);
        setError("");
        setReviewed("");
      }
    } catch (err) {
      if (epoch.current !== generation || reads.current !== sequence) return;
      setError(message(err));
      if (err instanceof ApiError && [401, 403, 404].includes(err.status)) {
        setDevices([]);
        setCode("");
        lost.current(err.status);
      }
    } finally {
      if (epoch.current === generation && reads.current === sequence) {
        readPending.current = false;
        setReading(false);
      }
    }
  }

  return (
    <section className="panel pc-panel">
      <h2>{t("Your PC connections")}</h2>
      <p>
        {t(
          "Pair your own PC, then verify its provider and fingerprints before granting access. Each task still needs separate approval.",
        )}
      </p>
      <p className="muted">
        {t(
          "Your PC uses outbound HTTPS. No server DB or OIDC secret is shared. Device results, usage and cleanup are reports, not server-verified isolation.",
        )}
      </p>
      <label>
        {t("Provider")}{" "}
        <select
          value={provider}
          disabled={busy}
          onChange={(event) => {
            setProvider(event.target.value);
            keys.current.delete("pair");
          }}
        >
          <option value="codex">Codex</option>
          <option value="claude">Claude</option>
        </select>
      </label>
      <button disabled={busy} onClick={() => void act("pair", { provider })}>
        {t("Create one-time pairing code")}
      </button>
      <button disabled={busy || reading} onClick={() => void refresh()}>
        {t("Refresh devices")}
      </button>
      {code && (
        <div className="notice" role="status">
          <p>
            {t(
              "Enter this code only in your own PC client within five minutes. It is shown once and is not stored in browser storage.",
            )}
          </p>
          <code>{code}</code>
          <button onClick={() => setCode("")}>{t("Hide pairing code")}</button>
        </div>
      )}
      {error && <p role="alert">{t(error)}</p>}
      <div className="connection-grid">
        {devices.map((device) => (
          <article key={device.id}>
            <h3>
              {device.provider} · {t(device.state)}
            </h3>
            <p>
              <code>{device.id}</code>
            </p>
            <p>
              {t("Expires")}: {formatDate(device.expires_at)}
            </p>
            {device.manifest && (
              <details>
                <summary>{t("Device fingerprints")}</summary>
                <p>
                  {device.manifest.version} · {device.manifest.scope}
                </p>
                <p>
                  {t("Binary digest")}:{" "}
                  <code>{device.manifest.binary_digest}</code>
                </p>
                <p>
                  {t("Runtime digest")}:{" "}
                  <code>{device.manifest.runtime_digest}</code>
                </p>
              </details>
            )}
            {device.state === "PENDING" && (
              <>
                <label>
                  <input
                    type="checkbox"
                    checked={reviewed === device.id}
                    disabled={busy}
                    onChange={(event) =>
                      setReviewed(event.target.checked ? device.id : "")
                    }
                  />
                  {t("I verified this device and its fingerprints on my PC.")}
                </label>
                <button
                  disabled={
                    busy ||
                    reviewed !== device.id ||
                    device.expires_at * 1000 <= Date.now()
                  }
                  onClick={() =>
                    void act(device.id + "/confirm", {
                      manifest_digest: device.manifest_digest,
                    })
                  }
                >
                  {t("Approve this PC")}
                </button>
              </>
            )}
            {device.state !== "REVOKED" && (
              <>
                <button
                  disabled={busy}
                  onClick={() => setReviewed("revoke:" + device.id)}
                >
                  {t("Review disconnect")}
                </button>
                {reviewed === "revoke:" + device.id && (
                  <div className="notice">
                    <p>
                      {t(
                        "Disconnecting blocks new starts. An already authorized call stops best effort; unresolved work is never replayed automatically.",
                      )}
                    </p>
                    <button
                      disabled={busy}
                      onClick={() => void act(device.id + "/revoke", {})}
                    >
                      {t("Disconnect this PC")}
                    </button>
                    <button disabled={busy} onClick={() => setReviewed("")}>
                      {t("Keep connected")}
                    </button>
                  </div>
                )}
              </>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
