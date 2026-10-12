import { useEffect, useState } from "react";
import { request } from "../../services/runtime";
import { en, type Key } from "../../app/i18n";
import type { Job } from "../../types/domain";
interface Result {
  job: Pick<Job, "id" | "kind" | "state" | "error" | "progress" | "created"> & {
    updated: string;
  };
  items: {
    id: number;
    state: Job["state"];
    error: string | null;
    created: string;
  }[];
  next_cursor: number | null;
}
export function JobEvents({
  id,
  t,
  onAction,
}: {
  id: string;
  t: (k: Key) => string;
  onAction: (id: string, action: "retry" | "cancel") => void;
}) {
  const [before, setBefore] = useState<number | null>(null);
  const [data, setData] = useState<Result | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setData(null);
    async function load() {
      try {
        const result = await request<Result>("POST", `/v1/jobs/${id}/events`, {
          before,
        });
        if (active) {
          setData(result);
          setFailed(false);
        }
      } catch {
        if (active) setFailed(true);
      } finally {
        if (active) timer = setTimeout(load, 3000);
      }
    }
    void load();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [id, before]);
  return (
    <section className="panel" aria-label={t("jobHistory")}>
      <h3>{t("jobHistory")}</h3>
      {failed && <p role="alert">{t("unknownError")}</p>}
      {data && (
        <>
          <p>
            {t(data.job.state)} · {new Date(data.job.updated).toLocaleString()}
          </p>
          <progress max={1} value={data.job.progress ?? undefined} />
          {(["queued", "running"] as string[]).includes(data.job.state) ? (
            <button onClick={() => onAction(id, "cancel")}>
              {t("cancel")}
            </button>
          ) : (["failed", "interrupted", "cancelled"] as string[]).includes(
              data.job.state,
            ) ? (
            <button onClick={() => onAction(id, "retry")}>{t("retry")}</button>
          ) : null}
          <ol>
            {data.items.map((event) => (
              <li key={event.id}>
                <time>{new Date(event.created).toLocaleString()}</time> ·{" "}
                {t(event.state)}
                {event.error && (
                  <span>
                    {" "}
                    ·{" "}
                    {t(
                      event.error in en ? (event.error as Key) : "unknownError",
                    )}{" "}
                    ({event.error})
                  </span>
                )}
              </li>
            ))}
          </ol>
          {data.next_cursor && (
            <button onClick={() => setBefore(data.next_cursor)}>
              {t("olderEvents")}
            </button>
          )}
          {before !== null && (
            <button onClick={() => setBefore(null)}>{t("latestEvents")}</button>
          )}
        </>
      )}
    </section>
  );
}
