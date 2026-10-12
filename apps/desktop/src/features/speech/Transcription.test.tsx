// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { request } from "../../services/runtime";
import { translator } from "../../app/i18n";
import { Transcription } from "./Transcription";
import type { Asset } from "../../types/domain";
vi.mock("../../services/runtime", () => ({
  native: false,
  request: vi.fn(),
  audioUrl: vi.fn(async () => ""),
  exportTranscript: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
const asset = { id: "a", name: "Recording", size: 1000 } as Asset;
function mount(
  options: Partial<React.ComponentProps<typeof Transcription>> = {},
) {
  vi.mocked(request).mockImplementation(async (method, path, body) => {
    if (method === "PUT" && path === "/v1/transcripts/tr")
      return {
        id: "tr",
        asset_id: "a",
        language: "en",
        revision: 2,
        segments: (body as { segments: unknown[] }).segments,
      };
    if (path === "/v1/models")
      return [
        {
          id: "test-asr-catalog-entry",
          name: "ASR fixture",
          engine: "faster-whisper",
          state: "installed",
          devices: ["cpu", "cuda"],
        },
      ];
    if (path === "/v1/diagnostics") return { gpu: { cuda_devices: 0 } };
    if (path === "/v1/transcripts")
      return [
        {
          id: "tr",
          asset_id: "a",
          revision: 1,
          language: "en",
          segments: Array.from({ length: 1005 }, (_, i) => ({
            start: i,
            end: i + 1,
            text: `Sentence ${i}`,
          })),
        },
      ];
    return {};
  });
  return render(
    <Transcription
      assets={[asset]}
      t={translator("en")}
      onError={vi.fn()}
      onQueued={vi.fn()}
      {...options}
    />,
  );
}
it("bounds transcript rendering and searches across all segments", async () => {
  mount();
  await waitFor(() =>
    expect(screen.getAllByRole("textbox", { name: /^Segment / })).toHaveLength(
      100,
    ),
  );
  fireEvent.change(screen.getByRole("textbox", { name: "Search transcript" }), {
    target: { value: "Sentence 1004" },
  });
  expect(screen.getAllByRole("textbox", { name: /^Segment / })).toHaveLength(1);
  expect(
    (
      screen.getByRole("textbox", {
        name: "Segment 1005",
      }) as HTMLTextAreaElement
    ).value,
  ).toBe("Sentence 1004");
});
it("uses the selected catalog model and entered language instead of hardcoded defaults", async () => {
  mount();
  const button = screen.getByRole("button", { name: "Transcribe" });
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
  fireEvent.change(screen.getByRole("combobox", { name: "Language code" }), {
    target: { value: "ja" },
  });
  fireEvent.click(button);
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith("POST", "/v1/transcribe", {
      asset_id: "a",
      language: "ja",
      model_id: "test-asr-catalog-entry",
      device: "cpu",
    }),
  );
  expect(
    screen.getByRole("option", { name: "CUDA" }).hasAttribute("disabled"),
  ).toBe(true);
});

it("saves manual speaker assignments through transcript revisions", async () => {
  mount();
  const input = await screen.findByLabelText("Speaker 1");
  fireEvent.change(input, { target: { value: "Alice" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith(
      "PUT",
      "/v1/transcripts/tr",
      expect.objectContaining({
        revision: 1,
        segments: expect.arrayContaining([
          expect.objectContaining({ speaker: "Alice", text: "Sentence 0" }),
        ]),
      }),
    ),
  );
});
it("imports subtitles as a separate selectable transcript", async () => {
  const old = {
    id: "old",
    asset_id: "a",
    revision: 1,
    language: "en",
    segments: [{ start: 0, end: 1, text: "Original" }],
  };
  const imported = {
    id: "imported",
    asset_id: "a",
    revision: 1,
    language: "und",
    segments: [{ start: 0, end: 1, text: "Hello imported" }],
  };
  vi.mocked(request).mockImplementation(async (method, path) => {
    if (path === "/v1/transcripts") return [old];
    if (path === "/v1/models") return [];
    if (path === "/v1/diagnostics") return { gpu: {} };
    if (path === "/v1/transcripts/import") return imported;
    return {};
  });
  render(
    <Transcription
      assets={[asset]}
      t={translator("en")}
      onError={vi.fn()}
      onQueued={vi.fn()}
    />,
  );
  await screen.findByDisplayValue("Original");
  const file = new File([], "captions.srt", { type: "text/plain" });
  Object.defineProperty(file, "arrayBuffer", {
    value: async () =>
      new TextEncoder().encode(
        "1\n00:00:00,000 --> 00:00:01,000\nHello imported",
      ).buffer,
  });
  fireEvent.change(screen.getByLabelText("Import SRT / VTT"), {
    target: { files: [file] },
  });
  await screen.findByDisplayValue("Hello imported");
  expect(request).toHaveBeenCalledWith(
    "POST",
    "/v1/transcripts/import",
    expect.objectContaining({
      asset_id: "a",
      format: "srt",
      language: "und",
      request_id: expect.any(String),
    }),
  );
  fireEvent.change(screen.getByLabelText("Selected transcript"), {
    target: { value: "old" },
  });
  await screen.findByDisplayValue("Original");
});

it("opens the exact asset and segment page requested by workspace search", async () => {
  mount({
    assets: [{ ...asset, id: "other" }, asset],
    initialAssetId: "a",
    initialTranscriptId: "tr",
    initialSegment: 150,
  });
  await screen.findByLabelText("Segment 151");
  expect((screen.getByLabelText("Media") as HTMLSelectElement).value).toBe("a");
  expect(
    screen.getByLabelText("Segment 151").closest(".active-segment"),
  ).not.toBeNull();
});

it("uses persisted transcription preferences in the queued job", async () => {
  mount({
    defaults: {
      language: "en",
      workspace: "transcription",
      inspector: true,
      transcription_model: "test-asr-catalog-entry",
      transcription_language: "pl",
      transcription_device: "cpu",
    },
  });
  const button = screen.getByRole("button", { name: "Transcribe" });
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
  fireEvent.click(button);
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith("POST", "/v1/transcribe", {
      asset_id: "a",
      language: "pl",
      model_id: "test-asr-catalog-entry",
      device: "cpu",
    }),
  );
});

it("splits and retimes segments, supports undo/redo and persists the edited structure", async () => {
  mount();
  const text = (await screen.findByLabelText(
    "Segment 1",
  )) as HTMLTextAreaElement;
  text.focus();
  text.setSelectionRange(9, 9);
  fireEvent.select(text);
  fireEvent.click(screen.getAllByRole("button", { name: "Split segment" })[0]);
  expect(
    (screen.getByLabelText("Segment 1") as HTMLTextAreaElement).value,
  ).toBe("Sentence");
  expect(
    (screen.getByLabelText("Segment 2") as HTMLTextAreaElement).value,
  ).toBe("0");
  fireEvent.click(screen.getByRole("button", { name: "Undo" }));
  expect(
    (screen.getByLabelText("Segment 1") as HTMLTextAreaElement).value,
  ).toBe("Sentence 0");
  fireEvent.click(screen.getByRole("button", { name: "Redo" }));
  fireEvent.change(screen.getByLabelText("Segment end 1"), {
    target: { value: "0.4" },
  });
  fireEvent.click(screen.getAllByRole("button", { name: "Apply timing" })[0]);
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith(
      "PUT",
      "/v1/transcripts/tr",
      expect.objectContaining({
        segments: expect.arrayContaining([
          {
            start: 0,
            end: 0.4,
            text: "Sentence",
            words: [],
            word_timestamps_valid: false,
          },
          {
            start: 0.5,
            end: 1,
            text: "0",
            words: [],
            word_timestamps_valid: false,
          },
        ]),
      }),
    ),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Undo" }).hasAttribute("disabled"),
    ).toBe(true),
  );
});
