import { useEffect, useState } from "react";
import { request } from "../../services/runtime";
import type { Key } from "../../app/i18n";
import type { Job } from "../../types/domain";
import { Modal } from "../../components/dialogs/Modal";
interface Notification {
  id: number;
  job_id: string;
  state: Job["state"];
  kind: string;
  created: string;
  read: number;
}
interface Result {
  items: Notification[];
  next_cursor: number | null;
  unread: number;
}
export function Notifications({
  ready,
  t,
  onOpenJob,
}: {
  ready: boolean;
  t: (k: Key) => string;
  onOpenJob: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [before, setBefore] = useState<number | null>(null);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [data, setData] = useState<Result | null>(null);
  const [failed, setFailed] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!ready) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setData(null);
    async function load() {
      try {
        const value = await request<Result>(
          "POST",
          "/v1/notifications/search",
          { before, unread_only: unreadOnly },
        );
        if (active) {
          setData(value);
          setFailed(false);
        }
      } catch {
        if (active) setFailed(true);
      } finally {
        if (active) timer = setTimeout(load, 5000);
      }
    }
    void load();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [ready, before, unreadOnly, refresh]);
  async function markRead(id: number) {
    if (busy) return;
    setBusy(true);
    try {
      await request("POST", `/v1/notifications/${id}/read`);
      setRefresh((n) => n + 1);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <button disabled={!ready} onClick={() => setOpen(true)}>
        {t("notifications")} {data ? `(${data.unread})` : ""}
      </button>
      {open && (
        <Modal
          title={t("notifications")}
          closeLabel={t("close")}
          onClose={() => setOpen(false)}
        >
          {failed && <p role="alert">{t("unknownError")}</p>}
          <label>
            <input
              type="checkbox"
              checked={unreadOnly}
              onChange={(e) => {
                setUnreadOnly(e.target.checked);
                setBefore(null);
              }}
            />
            {t("unreadOnly")}
          </label>
          <ul>
            {data?.items.map((item) => (
              <li key={item.id}>
                <time>{new Date(item.created).toLocaleString()}</time> ·{" "}
                {t(item.state)}
                <button
                  onClick={() => {
                    onOpenJob(item.job_id);
                    setOpen(false);
                  }}
                >
                  {t("openJob")}
                </button>
                {!item.read && (
                  <button
                    disabled={busy}
                    onClick={() => void markRead(item.id)}
                  >
                    {t("markRead")}
                  </button>
                )}
              </li>
            ))}
          </ul>
          {data?.next_cursor && (
            <button onClick={() => setBefore(data.next_cursor)}>
              {t("olderEvents")}
            </button>
          )}
          {before !== null && (
            <button onClick={() => setBefore(null)}>{t("latestEvents")}</button>
          )}
        </Modal>
      )}
    </>
  );
}
