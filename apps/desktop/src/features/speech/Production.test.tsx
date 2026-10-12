// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Production } from "./Production";
import { translator } from "../../app/i18n";
import { request } from "../../services/runtime";

vi.mock("../../services/runtime", () => ({ request: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

it("restores saved dubbing selections and queues the selected transcript", async () => {
  const queued = vi.fn();
  const error = vi.fn();
  vi.mocked(request).mockImplementation(async (method, path) => {
    if (path === "/v1/voices")
      return [
        { id: "af_heart", language: "en-us", source: "kokoro" },
        { id: "bf_emma", language: "en-gb", source: "kokoro" },
      ];
    if (path === "/v1/transcripts")
      return [
        {
          id: "first",
          project_id: "project",
          language: "en",
          segments: [{ text: "First" }],
        },
        {
          id: "saved",
          project_id: "project",
          language: "en",
          segments: [{ text: "Saved" }],
        },
        {
          id: "other",
          project_id: "another",
          language: "en",
          segments: [{ text: "Private" }],
        },
      ];
    if (method === "GET")
      return {
        revision: 3,
        content: { voice: "bf_emma", transcriptId: "saved" },
      };
    return { revision: 4 };
  });
  render(
    <Production
      mode="dubbing"
      projectId="project"
      t={translator("en")}
      onQueued={queued}
      onError={error}
    />,
  );
  await waitFor(() =>
    expect((screen.getByLabelText("Voice") as HTMLSelectElement).value).toBe(
      "bf_emma",
    ),
  );
  expect((screen.getByLabelText("Transcript") as HTMLSelectElement).value).toBe(
    "saved",
  );
  expect(screen.queryByText(/Private/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Generate speech" }));
  await waitFor(() => expect(queued).toHaveBeenCalledOnce());
  expect(request).toHaveBeenCalledWith("POST", "/v1/dubbing", {
    project_id: "project",
    voice: "bf_emma",
    language: "en-gb",
    transcript_id: "saved",
  });
  expect(error).not.toHaveBeenCalled();
});

it("edits and reorders chapters without an installed voice and preserves the saved voice", async () => {
  vi.mocked(request).mockImplementation(async (method, path) => {
    if (path === "/v1/voices" || path === "/v1/transcripts") return [];
    if (method === "GET")
      return {
        revision: 2,
        content: {
          voice: "missing_voice",
          chapters: [
            { title: "First", text: "One" },
            { title: "Second", text: "Two" },
          ],
          gap: 1,
        },
      };
    return { revision: 3 };
  });
  render(
    <Production
      mode="audiobook"
      projectId="book"
      t={translator("en")}
      onQueued={vi.fn()}
      onError={vi.fn()}
    />,
  );
  await screen.findByDisplayValue("First");
  expect(
    (
      screen.getByRole("button", {
        name: "Generate speech",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.click(
    screen.getAllByRole("button", { name: "Move chapter down" })[0],
  );
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith(
      "PUT",
      "/v1/projects/book/documents/audiobook",
      {
        revision: 2,
        content: {
          voice: "missing_voice",
          chapters: [
            { title: "Second", text: "Two" },
            { title: "First", text: "One" },
          ],
          gap: 1,
          transcriptId: "",
        },
      },
    ),
  );
});

it("restores audiobook history as a new revision without an installed voice", async () => {
  vi.mocked(request).mockImplementation(async (method, path) => {
    if (path === "/v1/voices" || path === "/v1/transcripts") return [];
    if (path.endsWith("/history"))
      return {
        items: [{ revision: 1, created: "2026-10-01T12:00:00Z", bytes: 100 }],
        next_cursor: null,
      };
    if (path.endsWith("/restore"))
      return {
        revision: 3,
        content: {
          chapters: [{ title: "Recovered", text: "Original" }],
          gap: 2,
          voice: "saved_voice",
        },
      };
    if (method === "GET")
      return {
        revision: 2,
        content: {
          chapters: [{ title: "Current", text: "Edited" }],
          gap: 1,
          voice: "saved_voice",
        },
      };
    return {};
  });
  render(
    <Production
      mode="audiobook"
      projectId="history-book"
      t={translator("en")}
      onQueued={vi.fn()}
      onError={vi.fn()}
    />,
  );
  await screen.findByDisplayValue("Current");
  const history = screen.getByRole("button", { name: "Saved revisions" });
  fireEvent.click(history);
  const select = await screen.findByRole("combobox", {
    name: "Saved revisions",
  });
  fireEvent.change(select, { target: { value: "1" } });
  fireEvent.click(
    screen.getByRole("button", { name: "Restore selected revision" }),
  );
  await screen.findByDisplayValue("Recovered");
  expect(request).toHaveBeenCalledWith(
    "POST",
    "/v1/projects/history-book/documents/audiobook/restore",
    { source_revision: 1, expected_revision: 2 },
  );
});
