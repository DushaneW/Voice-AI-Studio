import { request } from "../../services/runtime";
// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { TranscriptRecovery } from "./TranscriptRecovery";
import { translator } from "../../app/i18n";
vi.mock("../../services/runtime", () => ({ request: vi.fn() }));
afterEach(() => {
  cleanup();
  localStorage.clear();
});
it("keeps a recovery copy after a rejected server save and clears only after success", async () => {
  const save = vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true);
  render(
    <TranscriptRecovery
      onError={vi.fn()}
      onBusy={vi.fn()}
      restored={vi.fn()}
      id="transcript"
      revision={2}
      segments={[{ start: 0, end: 1, text: "Edited" }]}
      dirty
      saving={false}
      save={save}
      recover={vi.fn()}
      t={translator("en")}
    />,
  );
  await waitFor(() => expect(localStorage.length).toBe(1));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  expect(localStorage.length).toBe(1);
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(localStorage.length).toBe(0));
});
it("offers stored edits and blocks save until recovery is resolved", async () => {
  const segments = [{ start: 0, end: 1, text: "Recovered" }];
  localStorage.setItem(
    "nexus.recovery.v1.transcript.transcript.previous",
    JSON.stringify({
      schema: 1,
      revision: 1,
      content: segments,
      updated: new Date().toISOString(),
    }),
  );
  const recover = vi.fn();
  render(
    <TranscriptRecovery
      onError={vi.fn()}
      onBusy={vi.fn()}
      restored={vi.fn()}
      id="transcript"
      revision={2}
      segments={[{ start: 0, end: 1, text: "Server" }]}
      dirty={false}
      saving={false}
      save={vi.fn()}
      recover={recover}
      t={translator("en")}
    />,
  );
  expect(
    screen.getByRole("button", { name: "Save" }).hasAttribute("disabled"),
  ).toBe(true);
  fireEvent.click(
    screen.getByRole("button", { name: "Recover unsaved edits" }),
  );
  expect(recover).toHaveBeenCalledWith(segments);
  expect(localStorage.length).toBe(1);
});

it("restores a saved transcript revision with its optimistic revision guard", async () => {
  const restored = vi.fn();
  vi.mocked(request).mockImplementation(async (_method, path) =>
    path.endsWith("/history")
      ? {
          items: [{ revision: 1, created: "2026-10-01T12:00:00Z", bytes: 100 }],
          next_cursor: null,
        }
      : {
          revision: 3,
          content: {
            language: "en",
            segments: [{ start: 0, end: 1, text: "Old text" }],
          },
        },
  );
  render(
    <TranscriptRecovery
      id="transcript"
      revision={2}
      segments={[{ start: 0, end: 1, text: "Current" }]}
      dirty={false}
      saving={false}
      save={vi.fn()}
      recover={vi.fn()}
      onError={vi.fn()}
      onBusy={vi.fn()}
      restored={restored}
      t={translator("en")}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Saved revisions" }));
  const select = await screen.findByRole("combobox", {
    name: "Saved revisions",
  });
  fireEvent.change(select, { target: { value: "1" } });
  fireEvent.click(
    screen.getByRole("button", { name: "Restore selected revision" }),
  );
  await waitFor(() =>
    expect(restored).toHaveBeenCalledWith({
      revision: 3,
      content: {
        language: "en",
        segments: [{ start: 0, end: 1, text: "Old text" }],
      },
    }),
  );
  expect(request).toHaveBeenCalledWith(
    "POST",
    "/v1/transcripts/transcript/restore",
    { source_revision: 1, expected_revision: 2 },
  );
});
