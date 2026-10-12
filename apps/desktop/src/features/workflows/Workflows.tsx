import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Layers,
  Play,
  Plus,
  RefreshCw,
  Workflow,
} from "lucide-react";
import { request } from "../../services/runtime";
import { useUnsavedChanges } from "../../app/UnsavedChanges";
import type { Asset } from "../../types/domain";
import type { Key } from "../../app/i18n";

type Step = {
  kind: "analyze" | "transcribe" | "tts";
  options: Record<string, unknown>;
};
type Definition = { input_kind: "audio" | "text"; steps: Step[] };
interface Template {
  id: string;
  name: string;
  description: string;
  builtin: boolean;
  ready: boolean;
  definition: Definition;
  requirements: {
    model_id: string;
    model_installed: boolean;
    engine_installed: boolean;
  }[];
}
interface Run {
  id: string;
  name: string;
  state:
    "queued" | "running" | "completed" | "failed" | "cancelled" | "interrupted";
  completed: number;
  finished: number;
  total: number;
  progress: number;
  created: string;
  jobs?: {
    id: string;
    kind: Step["kind"];
    state: Run["state"];
    item_index: number;
    step_index: number;
    error: string | null;
  }[];
}
interface Engine {
  id: string;
  name: string;
  installed: boolean;
  operations: string[];
  version: string | null;
}
type Page = { items: Run[]; next_cursor: string | null };
const builtinNames: Record<string, Key> = {
  "audio-review": "wfReview",
  "batch-transcription": "wfTranscription",
  "voice-publish": "wfVoice",
  "voice-transcript": "wfVoiceTranscript",
};

export function Workflows({
  projectId,
  assets,
  t,
  onError,
}: {
  projectId: string;
  assets: Asset[];
  t: (key: Key) => string;
  onError: (error: string) => void;
}) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [engines, setEngines] = useState<Engine[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [templateId, setTemplateId] = useState("audio-review");
  const [selected, setSelected] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<Run | null>(null);
  const [draft, setDraft] = useState(false);
  const [name, setName] = useState("");
  const [inputKind, setInputKind] = useState<"audio" | "text">("audio");
  const [includeAnalysis, setIncludeAnalysis] = useState(true);
  const [includeASR, setIncludeASR] = useState(false);
  const [voice, setVoice] = useState("af_heart");
  const [language, setLanguage] = useState("en-us");
  const clean = useUnsavedChanges(
    text.trim().length > 0 || (draft && name.length > 0),
    busy,
  );
  const pending = useRef<{ fingerprint: string; key: string } | null>(null);
  const actionKeys = useRef(new Map<string, string>());
  const alive = useRef(true);
  const serial = useRef(0);
  const expanded = useRef(false);
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;
  const refresh = useCallback(async () => {
    const version = ++serial.current;
    try {
      const [catalog, adapters, page] = await Promise.all([
        request<Template[]>("GET", "/v1/workflow-templates"),
        request<Engine[]>("GET", "/v1/engines"),
        projectId
          ? request<Page>("POST", "/v1/workflows/search", {
              project_id: projectId,
            })
          : Promise.resolve({ items: [], next_cursor: null }),
      ]);
      if (!alive.current || version !== serial.current) return;
      setTemplates(catalog);
      setEngines(adapters);
      setRuns((previous) =>
        expanded.current
          ? [
              ...page.items,
              ...previous.filter(
                (item) => !page.items.some((fresh) => fresh.id === item.id),
              ),
            ].slice(0, 200)
          : page.items,
      );
      if (!expanded.current) setNext(page.next_cursor);
    } catch (error) {
      if (alive.current && version === serial.current)
        onErrorRef.current(String(error));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [projectId]);
  useEffect(() => {
    alive.current = true;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      await refresh();
      if (active) timer = setTimeout(() => void poll(), 2500);
    }
    void poll();
    return () => {
      active = false;
      alive.current = false;
      serial.current++;
      clearTimeout(timer);
    };
  }, [refresh]);
  const template = templates.find((value) => value.id === templateId);
  const label = (value: Template) =>
    builtinNames[value.id] ? t(builtinNames[value.id]) : value.name;
  async function start() {
    if (!template?.ready || !projectId || busy) return;
    const inputs =
      template.definition.input_kind === "audio"
        ? selected
        : text
            .split(/\n\s*\n/)
            .map((value) => value.trim())
            .filter(Boolean);
    const payload = { project_id: projectId, template_id: template.id, inputs };
    const fingerprint = JSON.stringify(payload);
    if (pending.current?.fingerprint !== fingerprint)
      pending.current = { fingerprint, key: crypto.randomUUID() };
    setBusy(true);
    try {
      const run = await request<Run>("POST", "/v1/workflows", {
        ...payload,
        request_key: pending.current.key,
      });
      pending.current = null;
      setText("");
      setSelected([]);
      setDetail(run);
      clean();
      await refresh();
    } catch (error) {
      onError(String(error));
    } finally {
      setBusy(false);
    }
  }
  async function action(run: Run, kind: "cancel" | "retry") {
    if (busy) return;
    setBusy(true);
    try {
      const key = actionKeys.current.get(run.id) ?? crypto.randomUUID();
      actionKeys.current.set(run.id, key);
      const updated = await request<Run>(
        "POST",
        `/v1/workflows/${run.id}/${kind}`,
        kind === "retry" ? { request_key: key } : undefined,
      );
      actionKeys.current.delete(run.id);
      setDetail(updated);
      await refresh();
    } catch (error) {
      onError(String(error));
    } finally {
      setBusy(false);
    }
  }
  async function saveTemplate() {
    if (busy) return;
    const steps: Step[] = [];
    if (inputKind === "text")
      steps.push({ kind: "tts", options: { voice, language } });
    if (includeAnalysis) steps.push({ kind: "analyze", options: {} });
    if (includeASR) steps.push({ kind: "transcribe", options: {} });
    setBusy(true);
    try {
      const created = await request<Template>(
        "POST",
        "/v1/workflow-templates",
        {
          name,
          description: "",
          definition: { input_kind: inputKind, steps },
        },
      );
      setDraft(false);
      setName("");
      setTemplateId(created.id);
      clean();
      await refresh();
    } catch (error) {
      onError(String(error));
    } finally {
      setBusy(false);
    }
  }
  async function inspect(run: Run) {
    try {
      setDetail(await request<Run>("GET", "/v1/workflows/" + run.id));
    } catch (error) {
      onError(String(error));
    }
  }
  async function loadMore() {
    if (!next || busy) return;
    setBusy(true);
    try {
      const page = await request<Page>("POST", "/v1/workflows/search", {
        project_id: projectId,
        before: next,
      });
      expanded.current = true;
      setRuns((current) =>
        [
          ...current,
          ...page.items.filter(
            (item) => !current.some((old) => old.id === item.id),
          ),
        ].slice(0, 200),
      );
      setNext(page.next_cursor);
    } catch (error) {
      onError(String(error));
    } finally {
      setBusy(false);
    }
  }
  const canStart =
    template?.ready &&
    projectId &&
    !busy &&
    (template.definition.input_kind === "audio"
      ? selected.length > 0 && selected.length <= 64
      : text.trim().length > 0);
  return (
    <div className="workflow-hub">
      <section className="workflow-intro">
        <div>
          <span className="eyebrow">NEXUS WORKFLOWS</span>
          <h2>{t("wfHeading")}</h2>
          <p>{t("wfDescription")}</p>
        </div>
        <Workflow size={42} aria-hidden="true" />
      </section>
      <div className="workflow-metrics">
        <div>
          <strong>{templates.length}</strong>
          <span>{t("wfTemplates")}</span>
        </div>
        <div>
          <strong>
            {engines.filter((engine) => engine.installed).length}/
            {engines.length}
          </strong>
          <span>{t("wfEngines")}</span>
        </div>
        <div>
          <strong>
            {
              runs.filter((run) => ["queued", "running"].includes(run.state))
                .length
            }
          </strong>
          <span>{t("wfActivePage")}</span>
        </div>
      </div>
      <div className="toolbar">
        <h3>{t("wfTemplates")}</h3>
        <button disabled={busy} onClick={() => setDraft(!draft)}>
          <Plus size={15} /> {t("wfNewTemplate")}
        </button>
      </div>
      {draft && (
        <section className="panel workflow-builder">
          <h3>{t("wfNewTemplate")}</h3>
          <label>
            {t("wfTemplateName")}
            <input
              disabled={busy}
              value={name}
              maxLength={120}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            {t("wfInput")}
            <select
              disabled={busy}
              value={inputKind}
              onChange={(event) =>
                setInputKind(event.target.value as "audio" | "text")
              }
            >
              <option value="audio">{t("media")}</option>
              <option value="text">{t("speechText")}</option>
            </select>
          </label>
          {inputKind === "text" && (
            <div className="toolbar">
              <label>
                {t("voice")}
                <input
                  disabled={busy}
                  value={voice}
                  onChange={(event) => setVoice(event.target.value)}
                />
              </label>
              <label>
                {t("language")}
                <select
                  disabled={busy}
                  value={language}
                  onChange={(event) => setLanguage(event.target.value)}
                >
                  {[
                    "en-us",
                    "en-gb",
                    "fr-fr",
                    "ja",
                    "zh",
                    "es",
                    "hi",
                    "it",
                    "pt-br",
                  ].map((code) => (
                    <option key={code}>{code}</option>
                  ))}
                </select>
              </label>
            </div>
          )}
          <label className="workflow-check">
            <input
              type="checkbox"
              disabled={busy}
              checked={includeAnalysis}
              onChange={(event) => setIncludeAnalysis(event.target.checked)}
            />
            {t("analyze")}
          </label>
          <label className="workflow-check">
            <input
              type="checkbox"
              disabled={busy}
              checked={includeASR}
              onChange={(event) => setIncludeASR(event.target.checked)}
            />
            {t("transcribe")}
          </label>
          <button
            className="primary"
            disabled={
              busy ||
              !name.trim() ||
              (inputKind === "audio" && !includeAnalysis && !includeASR)
            }
            onClick={() => void saveTemplate()}
          >
            {t("save")}
          </button>
        </section>
      )}
      <div className="workflow-template-grid">
        {templates.map((item) => (
          <button
            key={item.id}
            className={
              item.id === templateId
                ? "workflow-template selected"
                : "workflow-template"
            }
            disabled={busy}
            aria-pressed={item.id === templateId}
            onClick={() => {
              setTemplateId(item.id);
              setSelected([]);
            }}
          >
            <span className="workflow-template-tag">
              {item.builtin ? t("wfBuiltIn") : t("wfCustom")}
            </span>
            <strong>{label(item)}</strong>
            <span className="workflow-steps">
              {item.definition.steps.map((step, index) => (
                <span key={index}>
                  {index > 0 && <ArrowRight size={12} />}
                  {t(
                    step.kind === "tts"
                      ? "tts"
                      : step.kind === "analyze"
                        ? "analyze"
                        : "transcribe",
                  )}
                </span>
              ))}
            </span>
            <span
              className={item.ready ? "workflow-ready" : "workflow-missing"}
            >
              {item.ready ? t("ready") : t("wfRequirements")}
            </span>
          </button>
        ))}
      </div>
      {loading && <p role="status">{t("wfLoading")}</p>}
      {template && (
        <section className="panel workflow-launch">
          <div className="toolbar">
            <Layers size={20} />
            <h3>{label(template)}</h3>
          </div>
          {!projectId ? (
            <p>{t("selectProject")}</p>
          ) : template.definition.input_kind === "audio" ? (
            <>
              <div className="toolbar">
                <span>
                  {selected.length}/64 · {t("media")}
                </span>
                <button
                  disabled={busy || assets.length === 0}
                  onClick={() =>
                    setSelected(assets.slice(0, 64).map((asset) => asset.id))
                  }
                >
                  {t("wfSelectBatch")}
                </button>
                <button disabled={busy} onClick={() => setSelected([])}>
                  {t("clear")}
                </button>
              </div>
              <div className="workflow-asset-list">
                {assets.map((asset) => (
                  <label key={asset.id} className="workflow-check">
                    <input
                      type="checkbox"
                      disabled={
                        busy ||
                        (!selected.includes(asset.id) && selected.length >= 64)
                      }
                      checked={selected.includes(asset.id)}
                      onChange={(event) =>
                        setSelected(
                          event.target.checked
                            ? [...selected, asset.id]
                            : selected.filter((id) => id !== asset.id),
                        )
                      }
                    />
                    <span>
                      {asset.name}
                      <small>{asset.duration.toFixed(1)} s</small>
                    </span>
                  </label>
                ))}
              </div>
              {!assets.length && <p>{t("wfImportFirst")}</p>}
            </>
          ) : (
            <label>
              {t("wfBatchText")}
              <textarea
                rows={7}
                disabled={busy}
                value={text}
                maxLength={320000}
                onChange={(event) => setText(event.target.value)}
              />
              <small>{t("wfBatchTextHint")}</small>
            </label>
          )}
          {!template.ready && (
            <div className="workflow-requirements" role="status">
              <p>{t("wfRequirements")}</p>
              {template.requirements
                .filter(
                  (item) => !item.model_installed || !item.engine_installed,
                )
                .map((item) => (
                  <p key={item.model_id}>
                    {item.model_id} ·{" "}
                    {!item.model_installed && t("wfMissingModel")}{" "}
                    {!item.engine_installed && t("wfMissingEngine")}
                  </p>
                ))}
            </div>
          )}
          <button
            className="primary"
            disabled={!canStart}
            onClick={() => void start()}
          >
            <Play size={15} />
            {t("wfStart")}
          </button>
        </section>
      )}
      <section className="panel">
        <div className="toolbar">
          <h3>{t("wfHistory")}</h3>
          <button
            disabled={busy}
            onClick={() => void refresh()}
            aria-label={t("runDiagnostics")}
          >
            <RefreshCw size={15} />
          </button>
        </div>
        {!runs.length && <p>{t("wfNoRuns")}</p>}
        {runs.map((run) => (
          <article key={run.id} className="workflow-run">
            <div>
              <button
                className="workflow-run-name"
                onClick={() => void inspect(run)}
              >
                {builtinNames[run.name] ? t(builtinNames[run.name]) : run.name}
              </button>
              <small>
                {new Date(run.created).toLocaleString()} · {run.completed}/
                {run.total} {t("completed")}
              </small>
            </div>
            <div className="workflow-run-progress">
              <span>{t(run.state)}</span>
              <progress max={1} value={run.progress} />
            </div>
            {["queued", "running"].includes(run.state) ? (
              <button
                disabled={busy}
                onClick={() => void action(run, "cancel")}
              >
                {t("cancel")}
              </button>
            ) : ["failed", "cancelled", "interrupted"].includes(run.state) ? (
              <button
                disabled={busy}
                title={t("wfRetryHint")}
                onClick={() => void action(run, "retry")}
              >
                {t("wfRetry")}
              </button>
            ) : null}
          </article>
        ))}
        {next && runs.length < 200 && (
          <button disabled={busy} onClick={() => void loadMore()}>
            {t("wfMore")}
          </button>
        )}
      </section>
      {detail && (
        <section className="panel">
          <div className="toolbar">
            <h3>{detail.name}</h3>
            <button onClick={() => void inspect(detail)}>
              {t("runDiagnostics")}
            </button>
            <button onClick={() => setDetail(null)}>{t("dismiss")}</button>
          </div>
          <p>{t("wfRetryHint")}</p>
          <div className="workflow-step-list">
            {detail.jobs?.map((job) => (
              <div key={job.id}>
                <span>
                  {job.item_index + 1}.{job.step_index + 1}
                </span>
                <strong>{job.kind}</strong>
                <span>{t(job.state)}</span>
                {job.error && (
                  <small>
                    {job.error === "dependency_failed"
                      ? t("wfDependencyFailed")
                      : t("processing_failed")}
                  </small>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
      <section className="panel">
        <h3>{t("wfEngines")}</h3>
        <p>{t("wfEngineHint")}</p>
        <div className="workflow-engine-list">
          {engines.map((engine) => (
            <div key={engine.id}>
              <strong>{engine.name}</strong>
              <span>{engine.operations.join(" · ")}</span>
              <small>
                {engine.installed
                  ? `${t("available")} · ${engine.version ?? "—"}`
                  : t("notDetected")}
              </small>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
