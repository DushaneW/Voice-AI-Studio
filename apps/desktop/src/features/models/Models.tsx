import { useEffect, useRef, useState } from "react";
import { request } from "../../services/runtime";
import { en, type Key } from "../../app/i18n";
export interface Model {
  job_id?: string | null;
  job_state?: string | null;
  id: string;
  name: string;
  engine: string;
  provider: string;
  revision: string;
  license: string;
  size: number;
  downloaded: number;
  state: string;
  error: string | null;
  languages: string[];
  devices: string[];
  files: { name: string; sha256: string; size: number }[];
}
export function Models({
  onOpenJob,
  t,
  onError,
}: {
  onOpenJob?: (id: string) => void;
  t: (k: Key) => string;
  onError: (s: string) => void;
}) {
  const [items, setItems] = useState<Model[]>([]);
  const [online, setOnline] = useState(false);
  const [tab, setTab] = useState("all");
  const version = useRef(0);
  const live = useRef(false);
  async function refresh() {
    const current = ++version.current;
    try {
      const result = await request<Model[]>("GET", "/v1/models");
      if (live.current && current === version.current) {
        setItems(result);
        setOnline(true);
      }
    } catch {
      if (live.current && current === version.current) setOnline(false);
    }
  }
  useEffect(() => {
    live.current = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let active = true;
    async function poll() {
      await refresh();
      if (active) timer = setTimeout(() => void poll(), 1500);
    }
    void poll();
    return () => {
      active = false;
      live.current = false;
      version.current++;
      clearTimeout(timer);
    };
  }, []);
  async function action(id: string, name: string) {
    try {
      await request("POST", "/v1/models/" + id + "/" + name);
      await refresh();
    } catch (e) {
      onError(String(e));
    }
  }
  const shown = items.filter(
    (m) =>
      tab === "all" ||
      (tab === "installed"
        ? m.state === "installed"
        : ["downloading", "paused", "failed", "verifying"].includes(m.state)),
  );
  return (
    <>
      <div className="toolbar">
        {(["all", "installedModels", "downloads"] as const).map((label, i) => (
          <button
            key={label}
            aria-pressed={tab === ["all", "installed", "downloads"][i]}
            onClick={() => setTab(["all", "installed", "downloads"][i])}
          >
            {t(label)}
          </button>
        ))}
      </div>
      {!online ? (
        <p>{t("runtime_unavailable")}</p>
      ) : !shown.length ? (
        <div className="empty">{t("noModels")}</div>
      ) : (
        shown.map((m) => (
          <article className="panel model-card" key={m.id}>
            <div className="toolbar">
              <h3>{m.name}</h3>
              <span>{m.state}</span>
            </div>
            <p>
              {m.provider} · {m.license} · {(m.size / 1048576).toFixed(1)} MiB ·{" "}
              {m.devices.join(" / ")}
            </p>
            <p>
              {t("language")}: {m.languages.join(", ")}
            </p>
            {m.state === "downloading" && (
              <progress max={m.size} value={m.downloaded} />
            )}
            {m.job_id && (
              <p>
                {t("modelOperationJob")} ·{" "}
                {m.job_state && m.job_state in en
                  ? t(m.job_state as Key)
                  : m.job_state}{" "}
                <button
                  disabled={!onOpenJob}
                  onClick={() => onOpenJob?.(m.job_id!)}
                >
                  {t("openJob")}
                </button>
              </p>
            )}
            <div className="toolbar">
              {(m.job_state === "queued"
                ? ["cancel"]
                : m.state === "installed"
                  ? ["verify", "uninstall"]
                  : m.state === "downloading"
                    ? ["pause", "cancel"]
                    : m.state === "paused"
                      ? ["resume", "cancel"]
                      : m.state === "verifying"
                        ? ["cancel"]
                        : ["install"]
              ).map((a) => (
                <button key={a} onClick={() => void action(m.id, a)}>
                  {t(a as Key)}
                </button>
              ))}
            </div>
            {m.error && (
              <p role="alert">
                {t(m.error in en ? (m.error as Key) : "unknownError")}
              </p>
            )}
            <details>
              <summary>SHA-256 · {t("version")}</summary>
              <code className="hash">{m.revision}</code>
              {m.files.map((f) => (
                <p key={f.name}>
                  {f.name}
                  <code className="hash">{f.sha256}</code>
                </p>
              ))}
            </details>
          </article>
        ))
      )}
    </>
  );
}
