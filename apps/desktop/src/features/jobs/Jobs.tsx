import { JobEvents } from "./JobEvents";
import { request } from "../../services/runtime";
import { useEffect, useState } from "react";
import type { Job, Asset } from "../../types/domain";
import { en, type Key } from "../../app/i18n";
export function Jobs({
  jobs,
  targetId,
  assets,
  onAction,
  t,
  onOpenAsset,
  onOpenProject,
  onChanged,
  onError,
}: {
  onChanged: () => void;
  onError: (error: string) => void;
  jobs: Job[];
  targetId?: string | null;
  assets: Asset[];
  onAction: (id: string, action: "cancel" | "retry") => void;
  t: (k: Key) => string;
  onOpenProject?: (id: string) => void;
  onOpenAsset?: (id: string) => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    if (targetId) setSelected(targetId);
  }, [targetId]);
  const [archived, setArchived] = useState<Job[] | null>(null);
  const [busy, setBusy] = useState(false);
  async function archiveAction(action: "show" | "archive" | "restore") {
    if (busy) return;
    setBusy(true);
    try {
      if (action !== "show") {
        await request(
          "POST",
          "/v1/jobs/archive" + (action === "restore" ? "/restore" : ""),
        );
        onChanged();
      }
      setArchived(await request<Job[]>("GET", "/v1/jobs/archive"));
      setSelected(null);
    } catch (error) {
      onError(String(error));
    } finally {
      setBusy(false);
    }
  }
  const displayed = archived ?? jobs;
  const current = displayed.find((j) => j.id === selected);
  return (
    <>
      <div className="toolbar">
        <button
          disabled={busy || !jobs.some((j) => j.state === "completed")}
          onClick={() => void archiveAction("archive")}
        >
          {t("archiveCompleted")}
        </button>
        <button
          disabled={busy}
          onClick={() =>
            archived === null
              ? void archiveAction("show")
              : (setArchived(null), setSelected(null))
          }
        >
          {t(archived === null ? "showJobArchive" : "showCurrentJobs")}
        </button>
        {archived !== null && (
          <button
            disabled={busy || !archived.length}
            onClick={() => void archiveAction("restore")}
          >
            {t("restoreJobArchive")}
          </button>
        )}
      </div>
      {archived !== null && <p>{t("jobArchiveNotice")}</p>}
      {selected && (
        <JobEvents key={selected} id={selected} t={t} onAction={onAction} />
      )}
      {displayed.length ? (
        <div>
          <table>
            <thead>
              <tr>
                <th>{t("task")}</th>
                <th>{t("status")}</th>
                <th>{t("progress")}</th>
                <th>{t("choose")}</th>
              </tr>
            </thead>
            <tbody>
              {displayed.map((j) => (
                <tr key={j.id}>
                  <td>
                    <button
                      onClick={() =>
                        setSelected(selected === j.id ? null : j.id)
                      }
                    >
                      {t("open")}
                    </button>
                    {assets.find((a) => a.id === j.asset_id)?.name ??
                      t(
                        j.kind === "transcribe"
                          ? "transcription"
                          : j.kind === "analyze"
                            ? "analyze"
                            : j.kind,
                      )}
                    {j.kind === "model_operation" && (
                      <small>
                        {j.model_id ?? j.result?.model_id} ·{" "}
                        {j.operation ? t(j.operation) : ""}
                      </small>
                    )}
                    <small>
                      {t(
                        j.kind === "transcribe"
                          ? "transcription"
                          : j.kind === "analyze"
                            ? "analyze"
                            : j.kind,
                      )}
                    </small>
                  </td>
                  <td>
                    {t(j.state)}
                    {j.error && (
                      <small>
                        {t(j.error in en ? (j.error as Key) : "unknownError")}
                      </small>
                    )}
                  </td>
                  <td>
                    <progress max={1} value={j.progress ?? undefined} />
                    <span>
                      {j.progress === null
                        ? "—"
                        : Math.round(j.progress * 100) + "%"}
                    </span>
                  </td>
                  <td>
                    {j.kind === "duplicate_project" && j.result && (
                      <button
                        onClick={() => onOpenProject?.(j.result!.project_id)}
                      >
                        {t("openProject")}
                      </button>
                    )}
                    {j.result && "asset_id" in j.result && (
                      <button
                        onClick={() => {
                          if (j.result && "asset_id" in j.result)
                            onOpenAsset?.(j.result.asset_id);
                        }}
                      >
                        {t("media")}
                      </button>
                    )}
                    {["queued", "running"].includes(j.state) ? (
                      <button onClick={() => onAction(j.id, "cancel")}>
                        {t("cancel")}
                      </button>
                    ) : ["failed", "cancelled", "interrupted"].includes(
                        j.state,
                      ) ? (
                      <button onClick={() => onAction(j.id, "retry")}>
                        {t("retry")}
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {current && (
            <section className="panel">
              <h3>{t("task")}</h3>
              <p>{t(current.state)}</p>
              {current.result && "duration" in current.result && (
                <p>
                  {t("duration")}: {current.result.duration.toFixed(2)} s
                </p>
              )}
              {current.result && "sample_rate" in current.result && (
                <p>
                  {t("sampleRate")}: {current.result.sample_rate} Hz
                </p>
              )}
              {current.kind === "validate_project" && current.result && (
                <section aria-label={t("validationResult")}>
                  <h4>{t("validationResult")}</h4>
                  <p>
                    {current.result.checked_assets} {t("assets")} ·{" "}
                    {current.result.issue_count} {t("validationIssues")}
                  </p>
                  <ul>
                    {current.result.issues.map((issue, index) => (
                      <li key={index}>
                        {issue.kind}: {issue.id} — {issue.code}
                      </li>
                    ))}
                  </ul>
                  {current.result.omitted_issues > 0 && (
                    <p>+{current.result.omitted_issues}</p>
                  )}
                </section>
              )}
              {current.kind === "plan_repair" && current.result && (
                <section>
                  <h4>{t("plan_repair")}</h4>
                  <p>{t("repairScope")}</p>
                  <ul>
                    {current.result.actions.map((a) => (
                      <li key={a.category + a.id}>
                        {a.category}: {a.id} · {a.expected_revision} →{" "}
                        {a.source_revision}
                      </li>
                    ))}
                  </ul>
                  {current.result.unresolved.length > 0 && (
                    <p>
                      {t("repairUnresolved")}:{" "}
                      {current.result.unresolved_count ??
                        current.result.unresolved.length}
                    </p>
                  )}
                  {current.result.limited && <p>{t("repairLimited")}</p>}
                  <button
                    disabled={busy || current.result.actions.length === 0}
                    onClick={async () => {
                      setBusy(true);
                      try {
                        await request(
                          "POST",
                          `/v1/jobs/${current.id}/apply-repair`,
                          { confirmed: true },
                        );
                        onChanged();
                        setSelected(null);
                      } catch (error) {
                        onError(String(error));
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    {t("apply_repair")}
                  </button>
                </section>
              )}
              {current.kind === "apply_repair" && current.result && (
                <p>
                  {t("repairedRecords")}: {current.result.restored}
                </p>
              )}
              <details>
                <summary>{t("technicalDetails")}</summary>
                <pre className="job-details">
                  {JSON.stringify(current, null, 2)}
                </pre>
              </details>
            </section>
          )}
        </div>
      ) : (
        <div className="empty">
          <h3>{t("noJobs")}</h3>
          <p>{t("noJobsDetail")}</p>
        </div>
      )}
    </>
  );
}
