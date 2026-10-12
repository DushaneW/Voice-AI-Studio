import { useEffect, useRef, useState } from "react";
import { request } from "../../services/runtime";
import type { Key } from "../../app/i18n";
type Category = "assets" | "models" | "cache" | "backups" | "logs";
type Report = {
  categories: Record<
    Category,
    { bytes: number; files: number; complete: boolean }
  >;
  database_bytes: number;
  disk_free: number;
  disk_total: number;
  trash_audio_bytes: number;
};
const labels: Record<Category, Key> = {
  assets: "storageAudio",
  models: "models",
  cache: "storageCache",
  backups: "storageBackups",
  logs: "storageLogs",
};
const bytes = (value: number) =>
  `${(value / 1048576).toLocaleString(undefined, { maximumFractionDigits: 2 })} MiB`;
export function Storage({ t }: { t: (key: Key) => string }) {
  const [report, setReport] = useState<Report | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(false),
    [confirm, setConfirm] = useState(false),
    [done, setDone] = useState(false);
  const live = useRef(true);
  async function refresh() {
    setBusy(true);
    setError(false);
    try {
      const value = await request<Report>("GET", "/v1/storage");
      if (live.current) setReport(value);
    } catch {
      if (live.current) setError(true);
    } finally {
      if (live.current) setBusy(false);
    }
  }
  useEffect(() => {
    live.current = true;
    void refresh();
    return () => {
      live.current = false;
    };
  }, []);
  return (
    <section>
      <h3>{t("storageUsage")}</h3>
      <p>{t("storageMeasuredHint")}</p>
      <button disabled={busy} onClick={() => void refresh()}>
        {t("storageRefresh")}
      </button>
      {busy && <p role="status">{t("recordingWorking")}</p>}
      {error && <p role="alert">{t("storageFailed")}</p>}
      {report && (
        <>
          {report.disk_free <
            Math.max(1073741824, report.disk_total * 0.05) && (
            <p role="alert">{t("lowStorageWarning")}</p>
          )}
          <table>
            <thead>
              <tr>
                <th>{t("storageCategory")}</th>
                <th>{t("storageSize")}</th>
              </tr>
            </thead>
            <tbody>
              {(Object.keys(labels) as Category[]).map((key) => (
                <tr key={key}>
                  <td>{t(labels[key])}</td>
                  <td>
                    {bytes(report.categories[key].bytes)}
                    {!report.categories[key].complete &&
                      ` · ${t("storagePartial")}`}
                  </td>
                </tr>
              ))}
              <tr>
                <td>{t("storageDatabase")}</td>
                <td>{bytes(report.database_bytes)}</td>
              </tr>
            </tbody>
          </table>
          <p>
            {t("storageTrash")}: {bytes(report.trash_audio_bytes)}
          </p>
          <p>
            {t("storageFree")}: {bytes(report.disk_free)} /{" "}
            {bytes(report.disk_total)}
          </p>
        </>
      )}
      <p>{t("storageClearHint")}</p>
      <label>
        <input
          type="checkbox"
          checked={confirm}
          disabled={busy}
          onChange={(e) => {
            setConfirm(e.target.checked);
            setDone(false);
          }}
        />
        {t("storageConfirm")}
      </label>
      <button
        disabled={busy || !confirm}
        onClick={async () => {
          setBusy(true);
          setError(false);
          setDone(false);
          try {
            const result = await request<{ complete: boolean }>(
              "POST",
              "/v1/storage/waveforms/clear",
              { confirmed: true },
            );
            if (live.current) {
              setConfirm(false);
              await refresh();
              if (live.current) {
                setDone(result.complete);
                if (!result.complete) setError(true);
              }
            }
          } catch {
            if (live.current) setError(true);
          } finally {
            if (live.current) setBusy(false);
          }
        }}
      >
        {t("storageClear")}
      </button>
      {done && <p role="status">{t("storageCleared")}</p>}
    </section>
  );
}
