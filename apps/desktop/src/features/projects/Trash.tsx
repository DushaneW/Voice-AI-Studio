import { useState } from "react";
import { request } from "../../services/runtime";
import type { Key } from "../../app/i18n";
interface Item {
  id: string;
  name: string;
  kind: "project" | "asset";
  deleted_at: string;
  bytes: number;
}
export function Trash({
  t,
  onChanged,
  onError,
}: {
  t: (key: Key) => string;
  onChanged: () => Promise<void>;
  onError: (error: string) => void;
}) {
  const [items, setItems] = useState<Item[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [next, setNext] = useState<number | null>(null);
  async function load(more = false) {
    const result = await request<{ items: Item[]; next_offset: number | null }>(
      "POST",
      "/v1/trash/search",
      { offset: more ? next : 0 },
    );
    setItems((previous) =>
      more ? [...previous, ...result.items] : result.items,
    );
    setNext(result.next_offset);
    setOpen(true);
  }
  async function action(work: () => Promise<void>) {
    setBusy(true);
    try {
      await work();
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel">
      <button disabled={busy} onClick={() => void action(() => load())}>
        {t("trash")}
      </button>
      {open && (
        <>
          <p>{t("trashHint")}</p>
          {!items.length && <p>{t("trashEmpty")}</p>}
          {items.map((item) => (
            <div className="toolbar" key={`${item.kind}-${item.id}`}>
              <span>
                {item.name} · {(item.bytes / 1048576).toFixed(1)} MiB ·{" "}
                {new Date(item.deleted_at).toLocaleString()}
              </span>
              <button
                disabled={busy}
                onClick={() =>
                  void action(async () => {
                    await request(
                      "POST",
                      `/v1/trash/${item.kind}/${item.id}/restore`,
                    );
                    await onChanged();
                    await load();
                  })
                }
              >
                {t("restoreFromTrash")}
              </button>
            </div>
          ))}
          {next !== null && (
            <button
              disabled={busy}
              onClick={() => void action(() => load(true))}
            >
              {t("wfMore")}
            </button>
          )}
        </>
      )}
    </section>
  );
}
