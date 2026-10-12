// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { VoiceLibrary } from "./VoiceLibrary";
import { translator } from "../../app/i18n";
import { request, audioUrl } from "../../services/runtime";
vi.mock("../../services/runtime", () => ({
  native: false,
  request: vi.fn(),
  audioUrl: vi.fn(),
}));
afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.resetAllMocks();
});
function server(engine = true) {
  vi.mocked(request).mockImplementation(async (method, path) => {
    if (path === "/v1/voices")
      return [
        { id: "af_heart", language: "en-us", source: "Kokoro v1.0" },
        { id: "bf_emma", language: "en-gb", source: "Kokoro v1.0" },
      ];
    if (path === "/v1/models") return [{ id: "kokoro-v1", state: "installed" }];
    if (path === "/v1/engines")
      return [{ id: "kokoro-onnx", installed: engine }];
    if (path === "/v1/tts") return { id: "job" };
    if (path === "/v1/jobs/job/status")
      return { id: "job", state: "completed", error: null, asset_id: "asset" };
    throw new Error(`unexpected ${path}`);
  });
}
it("persists favorites and filters by language and tags", async () => {
  server();
  render(<VoiceLibrary projectId="project" t={translator("en")} />);
  fireEvent.click(await screen.findByLabelText("Favorite af_heart"));
  fireEvent.click(screen.getByLabelText("Favorites only"));
  expect(screen.queryByText("Emma")).toBeNull();
  fireEvent.change(screen.getByLabelText("Tags / categories"), {
    target: { value: "narration" },
  });
  fireEvent.change(screen.getByLabelText("Search voices and tags"), {
    target: { value: "narration" },
  });
  expect(screen.getByText("Heart")).toBeTruthy();
  expect(
    JSON.parse(localStorage.getItem("nexus.voice-presets.v1")!).af_heart
      .favorite,
  ).toBe(true);
});
it("generates a real job and loads only its completed audio", async () => {
  server();
  URL.revokeObjectURL = vi.fn();
  vi.mocked(audioUrl).mockResolvedValue("blob:sample");
  const view = render(
    <VoiceLibrary projectId="project" t={translator("en")} />,
  );
  await screen.findByText("Heart");
  fireEvent.change(
    screen.getByLabelText("Sample text (up to 500 characters)"),
    { target: { value: "Hello" } },
  );
  fireEvent.click(screen.getByText("Generate voice preview"));
  await waitFor(() => expect(audioUrl).toHaveBeenCalledWith("asset"));
  expect(request).toHaveBeenCalledWith(
    "POST",
    "/v1/tts",
    expect.objectContaining({
      project_id: "project",
      voice: "af_heart",
      text: "Hello",
      model_id: "kokoro-v1",
    }),
  );
  fireEvent.click(screen.getAllByRole("button", { name: "Select voice" })[1]);
  await waitFor(() => expect(view.container.querySelector("audio")).toBeNull());
  view.unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:sample");
});
it("disables generation when the engine is absent and preserves corrupt preferences", async () => {
  server(false);
  localStorage.setItem("nexus.voice-presets.v1", "broken");
  render(<VoiceLibrary projectId="project" t={translator("en")} />);
  await screen.findByText("Heart");
  expect(
    (screen.getByText("Generate voice preview") as HTMLButtonElement).disabled,
  ).toBe(true);
  expect(localStorage.getItem("nexus.voice-presets.v1")).toBe("broken");
  expect(screen.getByRole("alert")).toBeTruthy();
});
it("imports missing preferences without replacing local values and exports them", async () => {
  server();
  const p = {
    favorite: true,
    tags: "imported",
    speed: 1.3,
    created: "2026-10-03T00:00:00Z",
    modified: "2026-10-04T00:00:00Z",
  };
  localStorage.setItem(
    "nexus.voice-presets.v1",
    JSON.stringify({ af_heart: { ...p, tags: "local" } }),
  );
  render(<VoiceLibrary projectId="project" t={translator("en")} />);
  await screen.findByText("Heart");
  const file = new File([""], "presets.json", { type: "application/json" });
  Object.defineProperty(file, "text", {
    value: async () =>
      JSON.stringify({
        format: "nexus-voice-presets",
        version: 1,
        presets: { af_heart: p, bf_emma: p },
      }),
  });
  fireEvent.change(screen.getByLabelText("Import preferences from JSON"), {
    target: { files: [file] },
  });
  await screen.findByText(
    "Preferences imported. Existing presets were preserved.",
  );
  fireEvent.click(screen.getByText("Export preferences as JSON"));
  const exported = JSON.parse(
    (
      screen.getByLabelText(
        "Exported JSON (select and copy)",
      ) as HTMLTextAreaElement
    ).value,
  );
  expect(exported.presets.af_heart.tags).toBe("local");
  expect(exported.presets.bf_emma.tags).toBe("imported");
  const before = localStorage.getItem("nexus.voice-presets.v1");
  Object.defineProperty(file, "size", { value: 1048577 });
  fireEvent.change(screen.getByLabelText("Import preferences from JSON"), {
    target: { files: [file] },
  });
  await screen.findByRole("alert");
  expect(localStorage.getItem("nexus.voice-presets.v1")).toBe(before);
});
