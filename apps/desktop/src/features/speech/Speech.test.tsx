import {
  EditorCommandsProvider,
  useEditorCommands,
} from "../../app/commands/EditorCommands";
import type { Command } from "../../app/commands/registry";
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
import { Speech } from "./Speech";
vi.mock("../../services/runtime", () => ({ native: false, request: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
it("queues persisted voice and speed, leaving the studio text available until success", async () => {
  vi.mocked(request).mockImplementation(async (_method, path) => {
    if (path === "/v1/voices")
      return [
        { id: "af_first", language: "en-us" },
        { id: "bf_saved", language: "en-gb" },
      ];
    if (path === "/v1/models") return [{ id: "kokoro-v1", state: "installed" }];
    return {};
  });
  render(
    <Speech
      projectId="p"
      defaults={{
        language: "en",
        workspace: "tts",
        inspector: true,
        tts_voice: "bf_saved",
        tts_speed: 1.4,
      }}
      t={translator("en")}
      onError={vi.fn()}
      onQueued={vi.fn()}
    />,
  );
  fireEvent.change(await screen.findByRole("textbox"), {
    target: { value: "Hello" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Generate speech" }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith("POST", "/v1/tts", {
      project_id: "p",
      text: "Hello",
      voice: "bf_saved",
      speed: 1.4,
      language: "en-gb",
    }),
  );
});

it("speech command submits current text to the real persistent queue contract", async () => {
  let commands: Command[] = [];
  function Reader() {
    commands = useEditorCommands();
    return null;
  }
  vi.mocked(request).mockImplementation(async (_method, path) =>
    path === "/v1/voices"
      ? [{ id: "af_heart", language: "en-us" }]
      : path === "/v1/models"
        ? [{ id: "kokoro-v1", state: "installed" }]
        : {},
  );
  render(
    <EditorCommandsProvider>
      <Reader />
      <Speech
        projectId="p"
        t={translator("en")}
        onError={vi.fn()}
        onQueued={vi.fn()}
      />
    </EditorCommandsProvider>,
  );
  fireEvent.change(await screen.findByRole("textbox"), {
    target: { value: "From palette" },
  });
  const command = commands.find((c) => c.id === "generateActiveSpeech")!;
  expect(command.enabled).toBe(true);
  command.run();
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith(
      "POST",
      "/v1/tts",
      expect.objectContaining({ text: "From palette", project_id: "p" }),
    ),
  );
});
