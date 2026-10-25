export type Workspace =
  | "home"
  | "projects"
  | "media"
  | "jobs"
  | "settings"
  | "diagnostics"
  | "models"
  | "tts"
  | "voices"
  | "transcription"
  | "timeline"
  | "audiobook"
  | "dubbing"
  | "workflows";
export interface Project {
  id: string;
  name: string;
  modified: string;
  favorite: number;
  asset_count: number;
  duration: number;
  schema_version: number;
}
export interface Asset {
  id: string;
  project_id: string;
  name: string;
  duration: number;
  sample_rate: number;
  channels: number;
  size: number;
  sha256: string;
}
export interface Analysis {
  peaks: number[];
  peak_dbfs: number | null;
  rms_dbfs: number | null;
}
export interface TranscriptSegment {
  speaker?: string | null;
  start: number;
  end: number;
  text: string;
  words?: { start: number; end: number; text: string; probability?: number }[];
  word_timestamps_valid?: boolean;
}
interface JobBase {
  id: string;
  project_id: string | null;
  asset_id: string | null;
  state:
    "queued" | "running" | "completed" | "failed" | "cancelled" | "interrupted";
  progress: number | null;
  error: string | null;
  created: string;
}
interface AudioResult {
  asset_id: string;
  duration: number;
  sample_rate: number;
}
export type Job = JobBase &
  (
    | {
        kind: "model_operation";
        model_id?: string;
        operation?: "install" | "resume" | "repair" | "verify";
        result: {
          model_id: string;
          action: string;
          bytes: number;
          verified: boolean;
        } | null;
      }
    | {
        kind: "plan_repair";
        result: {
          actions: {
            category: string;
            id: string;
            expected_revision: number;
            source_revision: number;
          }[];
          unresolved: { category: string; id: string; reason: string }[];
          limited: boolean;
          repairable_count?: number;
          unresolved_count?: number;
          remaining_repairs?: number;
          omitted_findings?: number;
          history_limit: number;
          checked: number;
        } | null;
      }
    | {
        kind: "apply_repair";
        result: { restored: number; plan_id: string } | null;
      }
    | {
        kind: "validate_project";
        result: {
          checked_assets: number;
          checked_documents: number;
          checked_transcripts: number;
          issue_count: number;
          omitted_issues: number;
          issues: { kind: string; id: string; code: string }[];
          started: string;
          finished: string;
        } | null;
      }
    | {
        kind: "duplicate_project";
        result: { project_id: string; copied_assets: number } | null;
      }
    | { kind: "analyze"; result: Analysis | null }
    | {
        kind: "transcribe";
        result: {
          transcript_id: string;
          language: string;
          duration: number;
          model: string;
          device: string;
        } | null;
      }
    | {
        kind: "tts";
        result: (AudioResult & { voice: string; model: string }) | null;
      }
    | {
        kind: "timeline";
        result:
          (AudioResult & { channels: number; clipped_samples: number }) | null;
      }
    | {
        kind: "audiobook";
        result:
          | (AudioResult & {
              chapters: { title: string; start: number; end: number }[];
            })
          | null;
      }
    | {
        kind: "dubbing";
        result:
          | (AudioResult & {
              overruns: { segment: number; excess_seconds: number }[];
              source_transcript_revision: number;
            })
          | null;
      }
  );
export interface Settings {
  recording_sample_rate?: 24000 | 44100 | 48000;
  recording_channels?: 1 | 2;
  recording_gain?: number;
  recording_preroll?: 0 | 1 | 2 | 3 | 5;
  recording_countdown?: 0 | 3 | 5;
  playback_volume?: number;
  playback_muted?: boolean;
  transcription_model?: string | null;
  transcription_language?: string | null;
  transcription_device?: "cpu" | "cuda";
  tts_voice?: string | null;
  tts_speed?: number;
  model_downloads_allowed?: boolean;
  waveform_cache_enabled?: boolean;
  waveform_cache_mb?: 0 | 128 | 512 | 1024;
  last_project_id?: string | null;
  recent_project_ids?: string[];
  autosave_seconds?: 0 | 5 | 15 | 30 | 60;
  theme?: "dark" | "light" | "system";
  motion?: "system" | "full" | "reduced";
  sidebar_collapsed?: boolean;
  language: "en" | "pl";
  workspace: Workspace;
  inspector: boolean;
}
export interface Diagnostics {
  host?: {
    architecture: string;
    cpu_model: string | null;
    cpu_physical: number | null;
    ram_total: number | null;
    ram_available: number | null;
    process_rss: number | null;
  };
  gpu_inventory?: {
    state: string;
    reason: string | null;
    devices: {
      index: number;
      name: string;
      vram_total: number;
      vram_free: number;
      vendor: string;
    }[];
  };
  engines?: { id: string; installed: boolean; version: string | null }[];
  application_version: string;
  python: string;
  os: string;
  cpu_logical: number | null;
  storage_free: number;
  storage_total: number;
  ffmpeg_available: boolean;
  runtime: string;
  gpu: { state: string; reason: string };
  database_schema: number;
  packaged: boolean;
}
