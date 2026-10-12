import type { Key } from "../i18n";
export interface Command {
  id: string;
  label: Key;
  shortcut?: string;
  run: () => void;
  enabled?: boolean;
}
export function isEditing(target: EventTarget | null) {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable ||
      ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}
export function shortcutMatches(
  event: KeyboardEvent,
  shortcut: string,
): boolean {
  const parts = shortcut.toLowerCase().split("+");
  const mod = event.ctrlKey || event.metaKey;
  return (
    parts.includes("mod") === mod &&
    parts.includes("shift") === event.shiftKey &&
    !event.altKey &&
    event.key.toLowerCase() === parts.at(-1)
  );
}
export function runShortcut(event: KeyboardEvent, commands: Command[]) {
  const command = commands.find(
    (c) =>
      c.enabled !== false && c.shortcut && shortcutMatches(event, c.shortcut),
  );
  if (
    !command ||
    (isEditing(event.target) && !command.shortcut?.startsWith("mod"))
  )
    return;
  event.preventDefault();
  command.run();
}
