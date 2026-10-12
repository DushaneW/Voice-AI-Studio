import { useEffect, useRef, useState } from "react";
import type { PcmTake } from "./capture";
import {
  createTake,
  listTakes,
  recoverTake,
  removeTake,
  TakeWriter,
  type TakeDraft,
} from "./journal";
export function useTakeJournal(projectId: string) {
  const live = useRef(true),
    writer = useRef<TakeWriter | null>(null),
    active = useRef<TakeDraft | null>(null),
    requestId = useRef<string>(crypto.randomUUID());
  const [drafts, setDrafts] = useState<TakeDraft[]>([]),
    [failed, setFailed] = useState(false),
    [loading, setLoading] = useState(true);
  async function refresh() {
    try {
      const rows = await listTakes(projectId);
      if (live.current)
        setDrafts(rows.sort((a, b) => b.created.localeCompare(a.created)));
    } catch {
      if (live.current) setFailed(true);
    } finally {
      if (live.current) setLoading(false);
    }
  }
  useEffect(() => {
    live.current = true;
    void refresh();
    return () => {
      live.current = false;
    };
  }, [projectId]);
  return {
    requestId: () => requestId.current,
    drafts,
    failed,
    loading,
    async begin(rate: number, channels: number) {
      writer.current = null;
      active.current = null;
      requestId.current = crypto.randomUUID();
      try {
        const draft = await createTake(projectId, rate, channels);
        active.current = draft;
        requestId.current = draft.id;
        writer.current = new TakeWriter(draft, () => {
          if (live.current) setFailed(true);
        });
        if (live.current) setFailed(false);
      } catch {
        if (live.current) setFailed(true);
      }
    },
    sync(take: PcmTake) {
      writer.current?.sync(take);
    },
    async flush() {
      try {
        await writer.current?.flush();
      } catch {
        if (live.current) setFailed(true);
      }
    },
    async recover(id: string) {
      const take = await recoverTake(projectId, id);
      requestId.current = id;
      active.current = drafts.find((d) => d.id === id) ?? null;
      writer.current = null;
      return take;
    },
    async remove(id = active.current?.id) {
      if (!id) return true;
      try {
        try {
          await writer.current?.flush();
        } catch {
          /* Preserve committed blocks until explicit removal. */
        }
        await removeTake(projectId, id);
        if (active.current?.id === id) {
          active.current = null;
          writer.current = null;
        }
        await refresh();
        return true;
      } catch {
        if (live.current) setFailed(true);
        return false;
      }
    },
  };
}
