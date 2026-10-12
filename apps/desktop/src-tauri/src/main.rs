#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use nexus_supervisor::microphone::{self, MicrophonePermit};
use nexus_supervisor::Supervisor;
use serde_json::Value;
use std::sync::{Arc, Mutex};
use tauri::{Manager, State};
use tauri_plugin_dialog::DialogExt;
type Shared = Arc<Mutex<Result<Arc<Supervisor>, String>>>;
#[derive(Clone)]
struct LaunchConfig {
    program: std::path::PathBuf,
    python: bool,
    root: std::path::PathBuf,
}

#[tauri::command]
fn microphone_permission(
    window: tauri::WebviewWindow,
    permit: State<'_, MicrophonePermit>,
    enabled: bool,
) -> Result<(), String> {
    if window.label() != "main"
        || !microphone::local_origin(
            &window.url().map_err(|_| "microphone_origin")?,
            cfg!(debug_assertions),
        )
    {
        return Err("microphone_origin".into());
    }
    permit.set(enabled)
}
#[tauri::command]
async fn restart_runtime(
    state: State<'_, Shared>,
    config: State<'_, LaunchConfig>,
) -> Result<(), String> {
    let shared = state.inner().clone();
    let config = config.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        {
            let mut guard = shared.lock().map_err(|_| "runtime_lock")?;
            if matches!(&*guard, Err(code) if code == "runtime_restarting") {
                return Err("runtime_restarting".into());
            }
            let previous = std::mem::replace(&mut *guard, Err("runtime_restarting".into()));
            if let Ok(runtime) = previous {
                let mut runtime = match Arc::try_unwrap(runtime) {
                    Ok(runtime) => runtime,
                    Err(runtime) => {
                        *guard = Ok(runtime);
                        return Err("runtime_requests_active".into());
                    }
                };
                match runtime.has_exited() {
                    Ok(true) => drop(runtime),
                    status => {
                        *guard = Ok(Arc::new(runtime));
                        return Err(status
                            .err()
                            .unwrap_or_else(|| "runtime_still_running".into()));
                    }
                }
            }
        }
        let launched =
            Supervisor::launch(&config.program, config.python, &config.root).map(Arc::new);
        let outcome = launched.as_ref().map(|_| ()).map_err(Clone::clone);
        *shared.lock().map_err(|_| "runtime_lock")? = launched;
        outcome
    })
    .await
    .map_err(|_| "runtime_task")?
}

#[tauri::command]
async fn runtime_log(config: State<'_, LaunchConfig>) -> Result<String, String> {
    let path = config.root.join("logs").join("sidecar-stderr.log");
    tauri::async_runtime::spawn_blocking(move || {
        use std::io::{Read, Seek, SeekFrom};
        let mut file = match std::fs::File::open(path) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(String::new()),
            Err(_) => return Err("runtime_log_read".into()),
        };
        let size = file.metadata().map_err(|_| "runtime_log_read")?.len();
        file.seek(SeekFrom::Start(size.saturating_sub(65536)))
            .map_err(|_| "runtime_log_read")?;
        let mut bytes = Vec::new();
        file.take(65536)
            .read_to_end(&mut bytes)
            .map_err(|_| "runtime_log_read")?;
        Ok(String::from_utf8_lossy(&bytes).into_owned())
    })
    .await
    .map_err(|_| "runtime_task")?
}

async fn blocking<T: Send + 'static>(
    state: Shared,
    f: impl FnOnce(&Supervisor) -> Result<T, String> + Send + 'static,
) -> Result<T, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let guard = state.lock().map_err(|_| "runtime_lock")?.clone();
        let runtime = guard.as_ref().map_err(Clone::clone)?;
        f(runtime)
    })
    .await
    .map_err(|_| "runtime_task")?
}
#[tauri::command]
async fn runtime_request(
    state: State<'_, Shared>,
    method: String,
    path: String,
    body: Option<Value>,
) -> Result<Value, String> {
    blocking(state.inner().clone(), move |r| {
        r.request(&method, &path, body)
    })
    .await
}
#[tauri::command]
async fn import_audio(
    app: tauri::AppHandle,
    state: State<'_, Shared>,
    project_id: String,
) -> Result<bool, String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let Some(file) = app
            .dialog()
            .file()
            .add_filter("Audio", &["wav", "mp3", "m4a", "flac", "ogg", "aac"])
            .blocking_pick_file()
        else {
            return Ok(false);
        };
        let path = file.into_path().map_err(|_| "invalid_path")?;
        let guard = state.lock().map_err(|_| "runtime_lock")?.clone();
        guard
            .as_ref()
            .map_err(Clone::clone)?
            .import(&project_id, &path)?;
        Ok(true)
    })
    .await
    .map_err(|_| "runtime_task")?
}
#[tauri::command]
async fn save_recording(
    state: State<'_, Shared>,
    request: tauri::ipc::Request<'_>,
) -> Result<Value, String> {
    let project = request
        .headers()
        .get("x-project-id")
        .and_then(|v| v.to_str().ok())
        .filter(|v| nexus_supervisor::valid_id(v))
        .ok_or("invalid_id")?
        .to_owned();
    let request_id = request
        .headers()
        .get("x-request-id")
        .and_then(|v| v.to_str().ok())
        .filter(|v| nexus_supervisor::valid_id(v))
        .ok_or("invalid_request_id")?
        .to_owned();
    let tauri::ipc::InvokeBody::Raw(bytes) = request.body() else {
        return Err("recording_format".into());
    };
    if !nexus_supervisor::valid_recording(bytes) {
        return Err("recording_format".into());
    }
    let bytes = bytes.clone();
    blocking(state.inner().clone(), move |r| {
        r.recording(&project, &bytes, &request_id)
    })
    .await
}
#[tauri::command]
async fn read_audio(
    state: State<'_, Shared>,
    asset_id: String,
) -> Result<tauri::ipc::Response, String> {
    blocking(state.inner().clone(), move |r| r.audio(&asset_id))
        .await
        .map(tauri::ipc::Response::new)
}
#[tauri::command]
async fn export_audio(
    app: tauri::AppHandle,
    state: State<'_, Shared>,
    asset_id: String,
) -> Result<bool, String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let Some(file) = app
            .dialog()
            .file()
            .set_file_name("audio.wav")
            .blocking_save_file()
        else {
            return Ok(false);
        };
        let path = file.into_path().map_err(|_| "invalid_path")?;
        let guard = state.lock().map_err(|_| "runtime_lock")?.clone();
        guard
            .as_ref()
            .map_err(Clone::clone)?
            .export(&asset_id, &path)?;
        Ok(true)
    })
    .await
    .map_err(|_| "runtime_task")?
}
#[tauri::command]
async fn export_diagnostics(
    app: tauri::AppHandle,
    state: State<'_, Shared>,
) -> Result<bool, String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let Some(file) = app
            .dialog()
            .file()
            .set_file_name("nexus-diagnostics.json")
            .blocking_save_file()
        else {
            return Ok(false);
        };
        let path = file.into_path().map_err(|_| "invalid_path")?;
        let guard = state.lock().map_err(|_| "runtime_lock")?.clone();
        let data = guard
            .as_ref()
            .map_err(Clone::clone)?
            .request("GET", "/v1/diagnostics", None)?;
        std::fs::write(
            path,
            serde_json::to_vec_pretty(&data).map_err(|_| "report_json")?,
        )
        .map_err(|_| "export_write")?;
        Ok(true)
    })
    .await
    .map_err(|_| "runtime_task")?
}
#[tauri::command]
async fn export_transcript(
    app: tauri::AppHandle,
    state: State<'_, Shared>,
    transcript_id: String,
    format: String,
) -> Result<bool, String> {
    if !["srt", "vtt", "txt", "json"].contains(&format.as_str())
        || !nexus_supervisor::valid_id(&transcript_id)
    {
        return Err("invalid_export".into());
    }
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let Some(file) = app
            .dialog()
            .file()
            .set_file_name(format!("transcript.{format}"))
            .blocking_save_file()
        else {
            return Ok(false);
        };
        let path = file.into_path().map_err(|_| "invalid_path")?;
        let guard = state.lock().map_err(|_| "runtime_lock")?.clone();
        let data = guard.as_ref().map_err(Clone::clone)?.request(
            "GET",
            &format!("/v1/transcripts/{transcript_id}/export/{format}"),
            None,
        )?;
        std::fs::write(path, data["text"].as_str().ok_or("invalid_export")?)
            .map_err(|_| "export_write")?;
        Ok(true)
    })
    .await
    .map_err(|_| "runtime_task")?
}
#[tauri::command]
async fn backup_project(
    app: tauri::AppHandle,
    state: State<'_, Shared>,
    project_id: String,
) -> Result<bool, String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let Some(file) = app
            .dialog()
            .file()
            .set_file_name("project.nexus")
            .blocking_save_file()
        else {
            return Ok(false);
        };
        let path = file.into_path().map_err(|_| "invalid_path")?;
        let guard = state.lock().map_err(|_| "runtime_lock")?.clone();
        guard
            .as_ref()
            .map_err(Clone::clone)?
            .backup(&project_id, &path)?;
        Ok(true)
    })
    .await
    .map_err(|_| "runtime_task")?
}
#[tauri::command]
async fn restore_project(app: tauri::AppHandle, state: State<'_, Shared>) -> Result<bool, String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let Some(file) = app
            .dialog()
            .file()
            .add_filter("NEXUS project", &["nexus"])
            .blocking_pick_file()
        else {
            return Ok(false);
        };
        let path = file.into_path().map_err(|_| "invalid_path")?;
        let guard = state.lock().map_err(|_| "runtime_lock")?.clone();
        guard.as_ref().map_err(Clone::clone)?.restore(&path)?;
        Ok(true)
    })
    .await
    .map_err(|_| "runtime_task")?
}
fn main() {
    let result = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .manage(MicrophonePermit::default())
        .on_permission_request(|webview, kind| {
            use tauri::webview::{PermissionKind, PermissionResponse};
            match kind {
                PermissionKind::Microphone => {
                    let local = webview.label() == "main"
                        && webview.url().is_ok_and(|url| {
                            microphone::local_origin(&url, cfg!(debug_assertions))
                        });
                    if local && webview.state::<MicrophonePermit>().consume() {
                        PermissionResponse::Allow
                    } else {
                        PermissionResponse::Deny
                    }
                }
                PermissionKind::Camera | PermissionKind::DisplayCapture => PermissionResponse::Deny,
                _ => PermissionResponse::Default,
            }
        })
        .setup(|app| {
            let root = app.path().app_data_dir()?;
            std::fs::create_dir_all(&root)?;
            let executable = std::env::current_exe()?;
            let parent = executable
                .parent()
                .ok_or("executable directory unavailable")?;
            let sidecar = parent.join(if cfg!(windows) {
                "nexus-runtime.exe"
            } else {
                "nexus-runtime"
            });
            let (program, python) = nexus_supervisor::runtime_program(
                sidecar,
                std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                    .join("../../..")
                    .as_path(),
                cfg!(debug_assertions),
                std::env::var_os("NEXUS_RUNTIME_PYTHON"),
            );
            app.manage(LaunchConfig {
                program: program.clone(),
                python,
                root: root.clone(),
            });
            app.manage(Arc::new(Mutex::new(
                Supervisor::launch(&program, python, &root).map(Arc::new),
            )));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            microphone_permission,
            runtime_request,
            restart_runtime,
            runtime_log,
            import_audio,
            save_recording,
            read_audio,
            export_audio,
            export_diagnostics,
            export_transcript,
            backup_project,
            restore_project
        ])
        .build(tauri::generate_context!());
    match result {
        Ok(app) => app.run(|handle, event| {
            if matches!(event, tauri::RunEvent::Exit) {
                if let Some(state) = handle.try_state::<Shared>() {
                    if let Ok(mut runtime) = state.lock() {
                        *runtime = Err("runtime_stopped".into());
                    }
                }
            }
        }),
        Err(error) => eprintln!("NEXUS startup failed: {error}"),
    }
}
