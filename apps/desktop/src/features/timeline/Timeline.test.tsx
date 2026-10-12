// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Timeline } from "./Timeline";
import { request } from "../../services/runtime";
import { translator } from "../../app/i18n";
vi.mock("../../services/runtime", () => ({ request: vi.fn(), native: false }));
afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.resetAllMocks();
});
const clip = {
  asset_id: "a",
  offset: 0,
  trim_start: 0,
  trim_end: 1,
  gain: 1,
  fade_in: 0,
  fade_out: 0,
};
function mount() {
  const queued = vi.fn(),
    error = vi.fn();
  render(
    <Timeline
      projectId="p"
      assets={[]}
      t={translator("en")}
      onError={error}
      onQueued={queued}
    />,
  );
  return { queued, error };
}
it("saves the edited document before queuing render and navigating", async () => {
  const calls: string[] = [];
  let saved: ((value: unknown) => void) | undefined;
  vi.mocked(request).mockImplementation(async (method) => {
    calls.push(method);
    if (method === "GET") return { revision: 2, content: { clips: [clip] } };
    if (method === "PUT")
      return new Promise((resolve) => {
        saved = resolve;
      });
    return {};
  });
  const { queued } = mount();
  await waitFor(() =>
    expect(screen.getAllByRole("spinbutton")).toHaveLength(6),
  );
  fireEvent.change(screen.getAllByRole("spinbutton")[0], {
    target: { value: "2" },
  });
  fireEvent.click(screen.getByRole("button", { name: /render/i }));
  await waitFor(() => expect(saved).toBeDefined());
  expect(calls).toEqual(["GET", "PUT"]);
  expect(queued).not.toHaveBeenCalled();
  expect(screen.getAllByRole("spinbutton")[0].hasAttribute("disabled")).toBe(
    true,
  );
  saved!({ revision: 3 });
  await waitFor(() => expect(queued).toHaveBeenCalledOnce());
  expect(calls).toEqual(["GET", "PUT", "POST"]);
  expect(request).toHaveBeenCalledWith(
    "PUT",
    "/v1/projects/p/documents/timeline",
    {
      revision: 2,
      content: {
        clips: [{ ...clip, offset: 2 }],
        sample_rate: 48000,
        channels: 2,
        tracks: [
          {
            id: "main",
            name: "Main",
            volume: 1,
            pan: 0,
            muted: false,
            solo: false,
            locked: false,
            visible: true,
          },
        ],
      },
    },
  );
});
it("keeps edits and does not queue rendering when a revision conflict occurs", async () => {
  vi.mocked(request).mockImplementation(async (method) => {
    if (method === "GET") return { revision: 2, content: { clips: [clip] } };
    throw new Error("document_revision_conflict");
  });
  const { queued, error } = mount();
  await waitFor(() =>
    expect(screen.getAllByRole("spinbutton")).toHaveLength(6),
  );
  fireEvent.change(screen.getAllByRole("spinbutton")[0], {
    target: { value: "2" },
  });
  fireEvent.click(screen.getByRole("button", { name: /render/i }));
  await waitFor(() => expect(error).toHaveBeenCalled());
  expect(queued).not.toHaveBeenCalled();
  expect(
    vi.mocked(request).mock.calls.some(([method]) => method === "POST"),
  ).toBe(false);
  expect((screen.getAllByRole("spinbutton")[0] as HTMLInputElement).value).toBe(
    "2",
  );
  expect(
    screen.getByRole("button", { name: "Save" }).hasAttribute("disabled"),
  ).toBe(false);
});

it("restores a saved revision with the current revision guard and updates the editor", async () => {
  vi.mocked(request).mockImplementation(async (method, path) => {
    if (method === "GET") return { revision: 4, content: { clips: [clip] } };
    if (path.endsWith("/history"))
      return {
        items: [{ revision: 2, created: "2026-10-01T10:00:00Z", bytes: 400 }],
        next_cursor: null,
      };
    if (path.endsWith("/restore"))
      return {
        revision: 5,
        content: {
          clips: [{ ...clip, offset: 3 }],
          sample_rate: 44100,
          channels: 1,
        },
      };
    return {};
  });
  mount();
  const history = screen.getByRole("button", { name: "Saved revisions" });
  await waitFor(() => expect(history.hasAttribute("disabled")).toBe(false));
  fireEvent.click(history);
  await screen.findByRole("option", { name: /2 ·/ });
  fireEvent.change(screen.getByRole("combobox", { name: "Saved revisions" }), {
    target: { value: "2" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Restore selected revision" }),
  );
  await waitFor(() =>
    expect(
      (screen.getAllByRole("spinbutton")[0] as HTMLInputElement).value,
    ).toBe("3"),
  );
  expect(request).toHaveBeenCalledWith(
    "POST",
    "/v1/projects/p/documents/timeline/restore",
    { source_revision: 2, expected_revision: 4 },
  );
  expect(
    (screen.getByRole("combobox", { name: "Sample rate" }) as HTMLSelectElement)
      .value,
  ).toBe("44100");
});

it("blocks restoring history while local edits are unsaved", async () => {
  vi.mocked(request).mockResolvedValue({
    revision: 2,
    content: { clips: [clip] },
  });
  mount();
  await waitFor(() =>
    expect(screen.getAllByRole("spinbutton")).toHaveLength(6),
  );
  fireEvent.change(screen.getAllByRole("spinbutton")[0], {
    target: { value: "2" },
  });
  expect(
    screen
      .getByRole("button", { name: "Saved revisions" })
      .hasAttribute("disabled"),
  ).toBe(true);
});
