import { invoke, isTauri } from "@tauri-apps/api/core";
export const native = isTauri();
export async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  if (!native) throw new Error("desktop_required");
  return invoke<T>("runtime_request", { method, path, body: body ?? null });
}
export async function importAudio(projectId: string): Promise<boolean> {
  if (!native) throw new Error("desktop_required");
  return invoke<boolean>("import_audio", { projectId });
}
export async function audioUrl(assetId: string): Promise<string> {
  const bytes = await invoke<ArrayBuffer>("read_audio", { assetId });
  return URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
}
export async function exportAudio(assetId: string): Promise<boolean> {
  return invoke<boolean>("export_audio", { assetId });
}
export async function exportDiagnostics(): Promise<boolean> {
  return invoke<boolean>("export_diagnostics");
}

export async function exportTranscript(
  transcriptId: string,
  format: "srt" | "vtt" | "txt" | "json",
): Promise<boolean> {
  return invoke("export_transcript", { transcriptId, format });
}

export async function backupProject(projectId: string): Promise<boolean> {
  return invoke("backup_project", { projectId });
}
export async function restoreProject(): Promise<boolean> {
  return invoke("restore_project");
}

export async function restartRuntime(): Promise<void> {
  if (!native) throw new Error("desktop_required");
  return invoke<void>("restart_runtime");
}
export async function runtimeLog(): Promise<string> {
  if (!native) throw new Error("desktop_required");
  return invoke<string>("runtime_log");
}

export async function saveRecording(
  projectId: string,
  wav: ArrayBuffer,
  requestId: string,
): Promise<{ id: string }> {
  if (!native) throw new Error("desktop_required");
  return invoke("save_recording", wav, {
    headers: { "x-project-id": projectId, "x-request-id": requestId },
  });
}

export async function microphonePermission(enabled: boolean): Promise<void> {
  if (native) await invoke("microphone_permission", { enabled });
}
