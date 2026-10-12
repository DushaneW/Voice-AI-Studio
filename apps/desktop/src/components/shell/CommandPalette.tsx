import { useState } from "react";
import { Modal } from "../dialogs/Modal";
import type { Command } from "../../app/commands/registry";
import type { Key } from "../../app/i18n";
export function CommandPalette({
  commands,
  t,
  onClose,
}: {
  commands: Command[];
  t: (k: Key) => string;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const matches = commands.filter((c) =>
    t(c.label).toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <Modal closeLabel={t("close")} title={t("palette")} onClose={onClose}>
      <input
        autoFocus
        aria-label={t("commandSearch")}
        placeholder={t("commandSearch")}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="command-list">
        {matches.map((c) => (
          <button
            key={c.id}
            disabled={c.enabled === false}
            onClick={() => {
              onClose();
              c.run();
            }}
          >
            <span>{t(c.label)}</span>
            <kbd>{c.shortcut?.replace("mod", "Ctrl / ⌘")}</kbd>
          </button>
        ))}
        {!matches.length && <p>{t("noCommands")}</p>}
      </div>
    </Modal>
  );
}
