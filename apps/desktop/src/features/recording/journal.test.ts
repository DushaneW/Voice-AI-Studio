import "fake-indexeddb/auto";
import { expect, it, vi } from "vitest";
import { PcmTake } from "./capture";
import {
  appendTake,
  createTake,
  listTakes,
  recoverTake,
  removeTake,
  TakeWriter,
} from "./journal";
it("recovers exact PCM and prevents cross-project read or deletion", async () => {
  const draft = await createTake("journal-a", 48000, 2);
  const take = new PcmTake(48000, 2);
  take.append(new Float32Array([-1, 1, 0.25, -0.25]));
  const writer = new TakeWriter(draft, vi.fn());
  writer.sync(take);
  take.append(new Float32Array([0, 0]));
  writer.sync(take);
  await writer.flush();
  expect((await recoverTake(draft.projectId, draft.id)).wav()).toEqual(
    take.wav(),
  );
  expect((await listTakes(draft.projectId))[0].samples).toBe(6);
  expect(await listTakes("journal-b")).toEqual([]);
  await expect(recoverTake("journal-b", draft.id)).rejects.toThrow();
  await expect(removeTake("journal-b", draft.id)).rejects.toThrow();
  await removeTake(draft.projectId, draft.id);
  expect(await listTakes(draft.projectId)).toEqual([]);
});
it("rolls back duplicate or malformed chunks without damaging prior data", async () => {
  const draft = await createTake("conflict", 24000, 2);
  await appendTake(draft, 0, [new Int16Array([1, 2])]);
  await expect(
    appendTake(draft, 0, [new Int16Array([3, 4])]),
  ).rejects.toThrow();
  await expect(
    appendTake(draft, 1, [new Int16Array([5, 6]), new Int16Array([7])]),
  ).rejects.toThrow();
  expect((await recoverTake(draft.projectId, draft.id)).samples).toBe(2);
  expect((await listTakes(draft.projectId))[0].chunks).toBe(1);
  await removeTake(draft.projectId, draft.id);
});
it("signals persistence failure but preserves the memory take", async () => {
  const draft = await createTake("failed", 48000, 1);
  await removeTake(draft.projectId, draft.id);
  const error = vi.fn();
  const writer = new TakeWriter(draft, error);
  const take = new PcmTake(48000, 1);
  take.append(new Float32Array([0.5]));
  writer.sync(take);
  await expect(writer.flush()).rejects.toThrow("recording_storage_failed");
  expect(error).toHaveBeenCalledOnce();
  expect(new DataView(take.wav()).getInt16(44, true)).toBe(16384);
});
