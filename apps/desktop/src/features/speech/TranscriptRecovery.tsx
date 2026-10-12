import { useAutosave, AutosaveStatus } from "../../hooks/useAutosave";
import { useEditorSave } from "../../app/commands/EditorCommands";
import {
  DocumentHistory,
  type SavedDocument,
} from "../../components/history/DocumentHistory";
import { useRecoveryDraft } from "../../hooks/useRecoveryDraft";
import { RecoveryNotice } from "../../components/recovery/RecoveryNotice";
import type { Key } from "../../app/i18n";
type Segment = {
  start: number;
  end: number;
  text: string;
  speaker?: string | null;
};
export function TranscriptRecovery({
  id,
  revision,
  segments,
  dirty,
  saving,
  save,
  recover,
  t,
  onError,
  onBusy,
  restored,
}: {
  onError: (error: string) => void;
  onBusy: (busy: boolean) => void;
  restored: (document: SavedDocument) => void;
  id: string;
  revision: number;
  segments: Segment[];
  dirty: boolean;
  saving: boolean;
  save: () => Promise<boolean>;
  recover: (segments: Segment[]) => void;
  t: (key: Key) => string;
}) {
  const draft = useRecoveryDraft({
    scope: `transcript.${id}`,
    loaded: true,
    dirty,
    revision,
    content: segments,
    apply: recover,
    validate: (value) =>
      Array.isArray(value) &&
      value.length <= 10000 &&
      value.every(
        (segment) =>
          segment &&
          Number.isFinite(segment.start) &&
          Number.isFinite(segment.end) &&
          segment.start >= 0 &&
          segment.end > segment.start &&
          typeof segment.text === "string" &&
          segment.text.length <= 10000 &&
          (segment.speaker == null ||
            (typeof segment.speaker === "string" &&
              segment.speaker.length <= 80 &&
              !/[\x00-\x1f]/.test(segment.speaker))),
      ),
  });
  async function persist() {
    const ok = await save();
    if (ok) draft.clear();
    return ok;
  }
  useEditorSave(dirty && !saving && !draft.pending, persist);
  const autosave = useAutosave(dirty, saving || !!draft.pending, persist);
  return (
    <div>
      <AutosaveStatus state={autosave} t={t} />
      <DocumentHistory
        projectId={id}
        kind="transcript"
        revision={revision}
        disabled={dirty || saving || !!draft.pending}
        t={t}
        onBusy={onBusy}
        onError={onError}
        onRestore={(document) => {
          restored(document);
          draft.clear();
        }}
      />
      <RecoveryNotice
        pending={draft.pending}
        status={draft.status}
        revision={revision}
        recover={draft.recover}
        discard={draft.clear}
        t={t}
      />
      <button
        disabled={!dirty || saving || !!draft.pending}
        onClick={async () => {
          if (await save()) draft.clear();
        }}
      >
        {t("save")}
      </button>
    </div>
  );
}
