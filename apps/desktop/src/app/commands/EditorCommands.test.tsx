// @vitest-environment jsdom
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import {
  EditorCommandsProvider,
  useEditorCommands,
  useEditorSave,
  useEditorAction,
} from "./EditorCommands";
import type { Command } from "./registry";
afterEach(cleanup);
it("save command follows latest editor content and unregisters on unmount", () => {
  let commands: Command[] = [];
  const save = vi.fn().mockResolvedValue(true);
  function Reader() {
    commands = useEditorCommands();
    return null;
  }
  function Editor({ value }: { value: string }) {
    useEditorSave(true, () => save(value));
    return null;
  }
  const { rerender } = render(
    <EditorCommandsProvider>
      <Reader />
      <Editor value="old" />
    </EditorCommandsProvider>,
  );
  expect(commands[0].shortcut).toBe("mod+s");
  rerender(
    <EditorCommandsProvider>
      <Reader />
      <Editor value="latest" />
    </EditorCommandsProvider>,
  );
  act(() => commands[0].run());
  expect(save).toHaveBeenCalledWith("latest");
  rerender(
    <EditorCommandsProvider>
      <Reader />
    </EditorCommandsProvider>,
  );
  expect(commands).toHaveLength(0);
});

it("scoped actions reject disabled execution and unregister with the editor", () => {
  let commands: Command[] = [];
  const run = vi.fn();
  function Reader() {
    commands = useEditorCommands();
    return null;
  }
  function Editor({ enabled }: { enabled: boolean }) {
    useEditorAction("tts", "generateSpeech", enabled, run);
    return null;
  }
  const { rerender } = render(
    <EditorCommandsProvider>
      <Reader />
      <Editor enabled={false} />
    </EditorCommandsProvider>,
  );
  act(() => commands[0].run());
  expect(run).not.toHaveBeenCalled();
  rerender(
    <EditorCommandsProvider>
      <Reader />
      <Editor enabled={true} />
    </EditorCommandsProvider>,
  );
  act(() => commands[0].run());
  expect(run).toHaveBeenCalledOnce();
  rerender(
    <EditorCommandsProvider>
      <Reader />
    </EditorCommandsProvider>,
  );
  expect(commands).toEqual([]);
});
