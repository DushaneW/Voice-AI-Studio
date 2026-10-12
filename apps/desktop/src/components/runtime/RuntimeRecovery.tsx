import { useState } from "react";
import { restartRuntime, runtimeLog } from "../../services/runtime";
import type { Key } from "../../app/i18n";
export function RuntimeRecovery({
  code,
  t,
  onRestart,
}: {
  code: string;
  t: (key: Key) => string;
  onRestart: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState<string | null>(null);
  const [error, setError] = useState("");
  async function run(action: "restart" | "log") {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      if (action === "restart") {
        await restartRuntime();
        await onRestart();
      } else setLog(await runtimeLog());
    } catch (cause) {
      setError(String(cause instanceof Error ? cause.message : cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="runtime-banner" role="status">
      <p>{t("runtime_unavailable")}</p>
      <p>
        {t("runtimeFailureCode")}: <code>{code || "runtime_unavailable"}</code>
      </p>
      <p>
        {t(
          ([
            "runtime_executable_missing",
            "runtime_executable_denied",
            "runtime_executable_invalid",
            "runtime_launch_failed",
          ].includes(code)
            ? code
            : "runtimeRestartHint") as Key,
        )}
      </p>
      <div className="toolbar">
        <button disabled={busy} onClick={() => void run("restart")}>
          {t("restartRuntime")}
        </button>
        <button disabled={busy} onClick={() => void run("log")}>
          {t("showRuntimeLog")}
        </button>
      </div>
      {error && (
        <p role="alert">
          {t("runtimeRecoveryFailed")}: <code>{error}</code>
        </p>
      )}
      {log !== null && (
        <details open>
          <summary>{t("showRuntimeLog")}</summary>
          <pre className="job-details">{log || t("runtimeLogEmpty")}</pre>
        </details>
      )}
    </section>
  );
}
