import { PcmTake, MAX_RECORDING_BYTES } from "./capture";
export type TakeDraft = {
  id: string;
  projectId: string;
  rate: number;
  channels: number;
  created: string;
  samples: number;
  chunks: number;
};
async function transact<T>(
  mode: IDBTransactionMode,
  action: (tx: IDBTransaction, result: (value: T) => void) => void,
): Promise<T> {
  if (!globalThis.indexedDB) throw new Error("recording_storage_failed");
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open("nexus.recordings.v1", 1);
    let expired = false;
    const timer = setTimeout(() => {
      expired = true;
      reject(new Error("recording_storage_failed"));
    }, 5000);
    request.onupgradeneeded = () => {
      request.result
        .createObjectStore("takes", { keyPath: "id" })
        .createIndex("project", "projectId");
      request.result.createObjectStore("chunks", { keyPath: ["id", "index"] });
    };
    request.onerror = () => {
      clearTimeout(timer);
      reject(request.error);
    };
    request.onsuccess = () => {
      clearTimeout(timer);
      if (expired) request.result.close();
      else resolve(request.result);
    };
  });
  try {
    return await new Promise<T>((resolve, reject) => {
      const tx = db.transaction(["takes", "chunks"], mode, {
        durability: "strict",
      });
      let value: T;
      tx.oncomplete = () => resolve(value);
      tx.onabort = () =>
        reject(tx.error ?? new Error("recording_storage_failed"));
      try {
        action(tx, (result) => {
          value = result;
        });
      } catch (error) {
        tx.abort();
        reject(error);
      }
    });
  } finally {
    db.close();
  }
}
function range(id: string) {
  return IDBKeyRange.bound([id, 0], [id, Number.MAX_SAFE_INTEGER]);
}
function isPcm(value: unknown): value is Int16Array {
  return (
    ArrayBuffer.isView(value) &&
    Object.prototype.toString.call(value) === "[object Int16Array]"
  );
}
export async function listTakes(projectId: string): Promise<TakeDraft[]> {
  return transact("readonly", (tx, result) => {
    const rows: TakeDraft[] = [];
    result(rows);
    const request = tx
      .objectStore("takes")
      .index("project")
      .openCursor(IDBKeyRange.only(projectId));
    request.onsuccess = () => {
      const cursor = request.result;
      if (cursor) {
        rows.push(cursor.value);
        cursor.continue();
      }
    };
  });
}
export async function createTake(
  projectId: string,
  rate: number,
  channels: number,
): Promise<TakeDraft> {
  new PcmTake(rate, channels);
  const draft = {
    id: crypto.randomUUID(),
    projectId,
    rate,
    channels,
    created: new Date().toISOString(),
    samples: 0,
    chunks: 0,
  };
  await transact<void>("readwrite", (tx) => {
    tx.objectStore("takes").add(draft);
  });
  return draft;
}
export async function appendTake(
  draft: TakeDraft,
  from: number,
  blocks: readonly Int16Array[],
): Promise<void> {
  if (!blocks.length) return;
  await transact<void>("readwrite", (tx) => {
    const store = tx.objectStore("takes");
    const get = store.get(draft.id);
    get.onsuccess = () => {
      const row = get.result as TakeDraft | undefined;
      const count = blocks.reduce((n, b) => n + b.length, 0);
      if (
        !row ||
        row.projectId !== draft.projectId ||
        row.chunks !== from ||
        row.rate !== draft.rate ||
        row.channels !== draft.channels ||
        blocks.some((b) => !isPcm(b) || !b.length || b.length % row.channels) ||
        44 + (row.samples + count) * 2 > MAX_RECORDING_BYTES
      ) {
        tx.abort();
        return;
      }
      blocks.forEach((pcm, index) =>
        tx.objectStore("chunks").add({ id: row.id, index: from + index, pcm }),
      );
      store.put({
        ...row,
        chunks: from + blocks.length,
        samples: row.samples + count,
      });
    };
  });
}
export async function recoverTake(
  projectId: string,
  id: string,
): Promise<PcmTake> {
  return transact("readonly", (tx, result) => {
    const get = tx.objectStore("takes").get(id);
    get.onsuccess = () => {
      const row = get.result as TakeDraft | undefined;
      if (
        !row ||
        row.projectId !== projectId ||
        !Number.isSafeInteger(row.samples) ||
        row.samples <= 0 ||
        row.samples * 2 + 44 > MAX_RECORDING_BYTES
      ) {
        tx.abort();
        return;
      }
      let take: PcmTake;
      try {
        take = new PcmTake(row.rate, row.channels);
      } catch {
        tx.abort();
        return;
      }
      let index = 0;
      const request = tx.objectStore("chunks").openCursor(range(id));
      request.onsuccess = () => {
        const cursor = request.result;
        if (!cursor) {
          if (index !== row.chunks || take.samples !== row.samples) tx.abort();
          else result(take);
          return;
        }
        try {
          if (cursor.value.index !== index++ || !isPcm(cursor.value.pcm))
            throw new Error("recording_format");
          take.appendPcm(cursor.value.pcm);
          cursor.continue();
        } catch {
          tx.abort();
        }
      };
    };
  });
}
export async function removeTake(projectId: string, id: string): Promise<void> {
  await transact<void>("readwrite", (tx) => {
    const get = tx.objectStore("takes").get(id);
    get.onsuccess = () => {
      if (!get.result || get.result.projectId !== projectId) {
        tx.abort();
        return;
      }
      tx.objectStore("chunks").delete(range(id));
      tx.objectStore("takes").delete(id);
    };
  });
}
export class TakeWriter {
  private count = 0;
  private pendingBytes = 0;
  private tail: Promise<void> = Promise.resolve();
  private failed = false;
  constructor(
    readonly draft: TakeDraft,
    private onError: () => void,
  ) {}
  sync(take: PcmTake) {
    if (this.failed) return;
    const blocks = take.chunksFrom(this.count);
    if (!blocks.length) return;
    const bytes = blocks.reduce((n, b) => n + b.byteLength, 0);
    if (this.pendingBytes + bytes > 1048576) {
      this.failed = true;
      this.onError();
      return;
    }
    const from = this.count;
    this.count += blocks.length;
    this.pendingBytes += bytes;
    this.tail = this.tail
      .then(() => appendTake(this.draft, from, blocks))
      .catch(() => {
        if (!this.failed) {
          this.failed = true;
          this.onError();
        }
      })
      .finally(() => {
        this.pendingBytes -= bytes;
      });
  }
  async flush() {
    await this.tail;
    if (this.failed) throw new Error("recording_storage_failed");
  }
}
