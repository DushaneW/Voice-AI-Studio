import type { Key } from "../../app/i18n";
import type { Job } from "../../types/domain";

/** Mean progress (0–1) of running jobs that report it, or null when none do. */
export function activeProgress(jobs: Job[]): number | null {
  const known = jobs.filter(
    (j) => j.state === "running" && typeof j.progress === "number",
  );
  if (!known.length) return null;
  return known.reduce((sum, j) => sum + (j.progress ?? 0), 0) / known.length;
}

export function ActivityIndicator({
  jobs,
  t,
  onOpen,
}: {
  jobs: Job[];
  t: (k: Key) => string;
  onOpen: () => void;
}) {
  const running = jobs.filter((j) => j.state === "running").length;
  const queued = jobs.filter((j) => j.state === "queued").length;
  if (!running && !queued) return null;
  const progress = activeProgress(jobs);
  const label =
    `${t("running")}: ${running} · ${t("queued")}: ${queued}` +
    (progress === null ? "" : ` · ${Math.round(progress * 100)}%`);
  return (
    <button
      className={"activity" + (running ? " is-running" : "")}
      title={label}
      aria-label={t("jobs") + " · " + label}
      onClick={onOpen}
    >
      <span className="activity-bars" aria-hidden="true">
        <i />
        <i />
        <i />
        <i />
      </span>
      {running + queued}
      {progress !== null && (
        <span className="activity-meter" aria-hidden="true">
          <span style={{ transform: `scaleX(${progress})` }} />
        </span>
      )}
    </button>
  );
}
