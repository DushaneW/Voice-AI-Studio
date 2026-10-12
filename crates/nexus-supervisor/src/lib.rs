//! Owns a single authenticated loopback runtime. Secrets never cross frontend IPC.
pub mod microphone;
use rand::RngCore;
use reqwest::blocking::Client;
use serde_json::Value;
use std::{
    io::{BufRead, BufReader, Read, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    sync::mpsc,
    time::{Duration, Instant},
};

pub struct Supervisor {
    child: Child,
    _parent_pipe: ChildStdin,
    client: Client,
    base: String,
    token: String,
}
pub fn valid_id(id: &str) -> bool {
    uuid::Uuid::parse_str(id).is_ok() && id.len() == 36
}
/// Only canonical bounded PCM16 WAV produced by the recorder crosses this boundary.
pub fn valid_recording(bytes: &[u8]) -> bool {
    if bytes.len() < 46 || bytes.len() > 32 * 1024 * 1024 {
        return false;
    }
    let u16_at = |i| u16::from_le_bytes([bytes[i], bytes[i + 1]]);
    let u32_at = |i| u32::from_le_bytes(bytes[i..i + 4].try_into().unwrap());
    let channels = u16_at(22);
    let rate = u32_at(24);
    &bytes[0..4] == b"RIFF"
        && &bytes[8..16] == b"WAVEfmt "
        && &bytes[36..40] == b"data"
        && u32_at(4) as usize == bytes.len() - 8
        && u32_at(16) == 16
        && u16_at(20) == 1
        && [1, 2].contains(&channels)
        && [24000, 44100, 48000].contains(&rate)
        && u16_at(34) == 16
        && u16_at(32) == channels * 2
        && u32_at(28) == rate * channels as u32 * 2
        && u32_at(40) as usize == bytes.len() - 44
        && (bytes.len() - 44) % (channels as usize * 2) == 0
}
fn valid_model_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 80
        && id
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-' || b == b'_')
}
pub fn allowed(method: &str, path: &str) -> bool {
    let segments: Vec<_> = path.split('/').collect();
    match (method, segments.as_slice()) {
        ("GET", ["", "health"]) => true,
        ("POST", ["", "v1", "search"]) => true,
        ("POST", ["", "v1", "notifications", "search"]) => true,
        ("POST", ["", "v1", "notifications", id, "read"]) => id.parse::<i64>().is_ok_and(|n| n > 0),
        ("GET", ["", "v1", "storage" | "privacy" | "security"]) => true,
        ("POST", ["", "v1", "storage", "waveforms", "clear"]) => true,
        (
            "GET",
            ["", "v1", "projects" | "assets" | "jobs" | "settings" | "diagnostics" | "models" | "engines"
            | "voices" | "transcripts"],
        ) => true,
        (
            "POST",
            ["", "v1", "projects" | "jobs" | "tts" | "transcribe" | "audiobook" | "dubbing"],
        ) => true,
        ("PUT", ["", "v1", "settings"]) => true,
        ("GET" | "POST", ["", "v1", "jobs", "archive"]) => true,
        ("POST", ["", "v1", "jobs", "archive", "restore"]) => true,
        ("GET", ["", "v1", "assets", id, "waveform"]) => valid_id(id),
        ("DELETE", ["", "v1", "assets", id]) => valid_id(id),
        ("POST", ["", "v1", "trash", "search"]) => true,
        ("POST", ["", "v1", "trash", "project" | "asset", id, "restore"]) => valid_id(id),
        ("POST", ["", "v1", "projects", id, "duplicate" | "validate" | "repair-plan"]) => valid_id(id),
        ("PATCH" | "DELETE", ["", "v1", "projects", id]) => valid_id(id),
        ("POST", ["", "v1", "jobs", id, "cancel" | "retry" | "events" | "apply-repair"]) => valid_id(id),
        ("GET", ["", "v1", "jobs", id, "status"]) => valid_id(id),
        ("POST", ["", "v1", "transcripts", "import"]) => true,
        ("PUT", ["", "v1", "transcripts", id]) => valid_id(id),
        ("POST", ["", "v1", "transcripts", id, "history" | "restore"]) => valid_id(id),
        (
            "POST",
            ["", "v1", "models", id, "install" | "pause" | "resume" | "cancel" | "verify" | "repair" | "uninstall"],
        ) => valid_model_id(id),
        ("GET", ["", "v1", "transcripts", id, "export", "srt" | "vtt" | "txt" | "json"]) => {
            valid_id(id)
        }
        (
            "GET" | "PUT",
            ["", "v1", "projects", id, "documents", "timeline" | "audiobook" | "dubbing" | "project"],
        ) => valid_id(id),
        (
            "POST",
            ["", "v1", "projects", id, "documents", "timeline" | "audiobook" | "dubbing" | "project", "history" | "restore"],
        ) => valid_id(id),
        ("POST", ["", "v1", "timeline", "render"]) => true,
        ("GET" | "POST", ["", "v1", "workflow-templates"]) => true,
        ("DELETE", ["", "v1", "workflow-templates", id]) => {
            id.strip_prefix("custom-").is_some_and(valid_id)
        }
        ("POST", ["", "v1", "workflows"]) => true,
        ("POST", ["", "v1", "workflows", "search"]) => true,
        ("GET", ["", "v1", "workflows", id]) => valid_id(id),
        ("POST", ["", "v1", "workflows", id, "cancel" | "retry" | "events" | "apply-repair"]) => valid_id(id),
        _ => false,
    }
}
/// A local source interpreter is permitted in development builds only.
pub fn runtime_program(
    sidecar: PathBuf,
    source: &Path,
    development: bool,
    override_python: Option<std::ffi::OsString>,
) -> (PathBuf, bool) {
    if development {
        if let Some(python) = override_python {
            return (PathBuf::from(python), true);
        }
        if !sidecar.is_file() {
            let python = source.join(if cfg!(windows) {
                ".venv/Scripts/python.exe"
            } else {
                ".venv/bin/python"
            });
            if python.is_file() {
                return (python, true);
            }
        }
    }
    (sidecar, false)
}
fn append_runtime_log(directory: &Path, text: &str) {
    let path = directory.join("sidecar-stderr.log");
    if std::fs::metadata(&path).map(|m| m.len()).unwrap_or(0) + text.len() as u64 > 1_048_576 {
        let _ = std::fs::remove_file(directory.join("sidecar-stderr.log.1"));
        let _ = std::fs::rename(&path, directory.join("sidecar-stderr.log.1"));
    }
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
    {
        let _ = file.write_all(text.as_bytes());
    }
}
fn spawn_error_code(error: &std::io::Error) -> &'static str {
    match error.kind() {
        std::io::ErrorKind::NotFound => "runtime_executable_missing",
        std::io::ErrorKind::PermissionDenied => "runtime_executable_denied",
        _ => match error.raw_os_error() {
            Some(8) if cfg!(unix) => "runtime_executable_invalid",
            Some(193 | 216) if cfg!(windows) => "runtime_executable_invalid",
            _ => "runtime_launch_failed",
        },
    }
}
fn capture_stderr(mut stderr: impl Read + Send + 'static, directory: PathBuf, token: String) {
    std::thread::spawn(move || {
        let path = directory.join("sidecar-stderr.log");
        let mut reader = BufReader::new(&mut stderr);
        loop {
            let mut bytes = Vec::new();
            let count = Read::by_ref(&mut reader)
                .take(8192)
                .read_until(b'\n', &mut bytes);
            match count {
                Ok(0) | Err(_) => break,
                _ => {}
            }
            let text = String::from_utf8_lossy(&bytes).replace(&token, "[redacted]");
            if std::fs::metadata(&path).map(|m| m.len()).unwrap_or(0) + text.len() as u64
                > 1_048_576
            {
                let _ = std::fs::remove_file(directory.join("sidecar-stderr.log.1"));
                let _ = std::fs::rename(&path, directory.join("sidecar-stderr.log.1"));
            }
            if let Ok(mut file) = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(&path)
            {
                let _ = file.write_all(text.as_bytes());
            }
        }
    });
}
impl Supervisor {
    /// A restart may only replace a child that has actually exited.
    pub fn has_exited(&mut self) -> Result<bool, String> {
        self.child
            .try_wait()
            .map(|status| status.is_some())
            .map_err(|_| "runtime_process_status".into())
    }
    pub fn launch(executable: &Path, python: bool, root: &Path) -> Result<Self, String> {
        let mut secret = [0u8; 32];
        rand::rngs::OsRng.fill_bytes(&mut secret);
        let token = secret
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<String>();
        let log_directory = root.join("logs");
        std::fs::create_dir_all(&log_directory).map_err(|_| "runtime_log_directory")?;
        let mut cmd = Command::new(executable);
        if python {
            cmd.args(["-m", "nexus_runtime"]);
        }
        // The stdin pipe is also the lifetime contract with Python.
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }
        let mut child = cmd
            .env("NEXUS_DATA_DIR", root)
            .env("ORT_DISABLE_TELEMETRY", "1")
            .env("HF_HUB_DISABLE_TELEMETRY", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| {
                let code = spawn_error_code(&error);
                append_runtime_log(&log_directory, &format!(
                    "{code}: executable={executable:?}; python_module={python}; os_error={:?}; {error}\n",
                    error.raw_os_error()
                ));
                code.to_owned()
            })?;
        if let Some(stderr) = child.stderr.take() {
            capture_stderr(stderr, log_directory, token.clone());
        }
        let result = (|| -> Result<(Client, String, ChildStdin), String> {
            let mut input = child.stdin.take().ok_or("runtime_stdin")?;
            writeln!(input, "{token}").map_err(|_| "runtime_stdin")?;
            input.flush().map_err(|_| "runtime_stdin")?;
            let output = child.stdout.take().ok_or("runtime_stdout")?;
            let (tx, rx) = mpsc::channel();
            std::thread::spawn(move || {
                let mut reader = BufReader::new(output);
                let mut line = String::new();
                let result = Read::by_ref(&mut reader)
                    .take(4096)
                    .read_line(&mut line)
                    .map(|_| line);
                let _ = tx.send(result);
                let _ = std::io::copy(&mut reader, &mut std::io::sink());
            });
            let line = rx
                .recv_timeout(Duration::from_secs(15))
                .map_err(|_| "runtime_start_timeout")?
                .map_err(|_| "runtime_handshake")?;
            let hello: Value = serde_json::from_str(&line).map_err(|_| "runtime_handshake")?;
            let port = hello["port"]
                .as_u64()
                .filter(|p| *p > 0 && *p <= 65535)
                .ok_or("runtime_port")?;
            if hello["api_version"] != "1" {
                return Err("runtime_version".into());
            }
            let client = Client::builder()
                .no_proxy()
                .timeout(Duration::from_secs(30))
                .build()
                .map_err(|_| "runtime_client")?;
            let base = format!("http://127.0.0.1:{port}");
            let start = Instant::now();
            loop {
                if let Ok(response) = client
                    .get(format!("{base}/health"))
                    .bearer_auth(&token)
                    .timeout(Duration::from_millis(500))
                    .send()
                {
                    if response.status().is_success() {
                        if let Ok(v) = response.json::<Value>() {
                            if v["status"] == "ready" && v["api_version"] == "1" {
                                break;
                            }
                        }
                    }
                }
                if start.elapsed() > Duration::from_secs(15) {
                    return Err("runtime_start_timeout".into());
                }
                std::thread::sleep(Duration::from_millis(80));
            }
            Ok((client, base, input))
        })();
        match result {
            Ok((client, base, input)) => Ok(Self {
                child,
                _parent_pipe: input,
                client,
                base,
                token,
            }),
            Err(e) => {
                let _ = child.kill();
                let _ = child.wait();
                Err(e)
            }
        }
    }
    fn response(
        &self,
        method: &str,
        path: &str,
        body: Option<Value>,
    ) -> Result<reqwest::blocking::Response, String> {
        let method =
            reqwest::Method::from_bytes(method.as_bytes()).map_err(|_| "invalid_method")?;
        let mut req = self
            .client
            .request(method, format!("{}{path}", self.base))
            .bearer_auth(&self.token);
        if path == "/v1/assets/import"
            || path == "/v1/backups/restore"
            || path.ends_with("/backup")
            || path.ends_with("/file")
            || path.ends_with("/audio")
        {
            req = req.timeout(Duration::from_secs(600));
        }
        if let Some(body) = body {
            req = req.json(&body)
        }
        let response = req.send().map_err(|_| "runtime_unavailable")?;
        if !response.status().is_success() {
            let detail = response
                .json::<Value>()
                .ok()
                .and_then(|v| v["detail"].as_str().map(str::to_owned));
            return Err(detail.unwrap_or_else(|| "runtime_request_failed".into()));
        }
        Ok(response)
    }
    pub fn request(&self, method: &str, path: &str, body: Option<Value>) -> Result<Value, String> {
        if !allowed(method, path) {
            return Err("forbidden_route".into());
        }
        self.json(method, path, body)
    }
    fn json(&self, method: &str, path: &str, body: Option<Value>) -> Result<Value, String> {
        let response = self.response(method, path, body)?;
        if response.status().as_u16() == 204 {
            return Ok(Value::Null);
        }
        let mut bytes = Vec::new();
        response
            .take(4 * 1024 * 1024 + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| "runtime_read")?;
        if bytes.len() > 4 * 1024 * 1024 {
            return Err("response_too_large".into());
        }
        serde_json::from_slice(&bytes).map_err(|_| "runtime_json".into())
    }
    pub fn import(&self, project: &str, path: &Path) -> Result<Value, String> {
        if !valid_id(project) {
            return Err("invalid_id".into());
        }
        self.json("POST","/v1/assets/import",Some(serde_json::json!({"project_id":project,"path":path.to_str().ok_or("invalid_path")?})))
    }
    pub fn recording(
        &self,
        project: &str,
        bytes: &[u8],
        request_id: &str,
    ) -> Result<Value, String> {
        if !valid_id(project) || !valid_id(request_id) || !valid_recording(bytes) {
            return Err("recording_format".into());
        }
        let directory = tempfile::tempdir().map_err(|_| "recording_write")?;
        let path = directory.path().join("Recording.wav");
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
            .map_err(|_| "recording_write")?;
        file.write_all(bytes).map_err(|_| "recording_write")?;
        file.sync_all().map_err(|_| "recording_write")?;
        drop(file);
        self.json(
            "POST",
            "/v1/assets/import",
            Some(serde_json::json!({
                "project_id": project, "path": path.to_str().ok_or("invalid_path")?,
                "request_id": request_id
            })),
        )
    }
    pub fn audio(&self, id: &str) -> Result<Vec<u8>, String> {
        if !valid_id(id) {
            return Err("invalid_id".into());
        }
        let mut out = Vec::new();
        self.response("GET", &format!("/v1/assets/{id}/audio"), None)?
            .take(32 * 1024 * 1024 + 1)
            .read_to_end(&mut out)
            .map_err(|_| "runtime_read")?;
        if out.len() > 32 * 1024 * 1024 {
            return Err("audioTooLarge".into());
        }
        Ok(out)
    }
    pub fn backup(&self, project: &str, target: &Path) -> Result<(), String> {
        if !valid_id(project) {
            return Err("invalid_id".into());
        }
        let result = self.json("POST", &format!("/v1/projects/{project}/backup"), None)?;
        let id = result["id"]
            .as_str()
            .filter(|id| valid_id(id))
            .ok_or("invalid_backup")?;
        let mut response = self.response("GET", &format!("/v1/backups/{id}/file"), None)?;
        let mut file = tempfile::NamedTempFile::new_in(target.parent().ok_or("invalid_path")?)
            .map_err(|_| "export_write")?;
        std::io::copy(&mut response, &mut file).map_err(|_| "export_write")?;
        file.as_file().sync_all().map_err(|_| "export_write")?;
        file.persist(target).map_err(|_| "export_write")?;
        Ok(())
    }
    pub fn restore(&self, source: &Path) -> Result<Value, String> {
        self.json(
            "POST",
            "/v1/backups/restore",
            Some(serde_json::json!({"path":source.to_str().ok_or("invalid_path")?})),
        )
    }
    pub fn export(&self, id: &str, path: &Path) -> Result<(), String> {
        if !valid_id(id) {
            return Err("invalid_id".into());
        }
        let mut response = self.response("GET", &format!("/v1/assets/{id}/audio"), None)?;
        let parent = path.parent().ok_or("invalid_path")?;
        let mut file = tempfile::NamedTempFile::new_in(parent).map_err(|_| "export_write")?;
        std::io::copy(&mut response, &mut file).map_err(|_| "export_write")?;
        file.as_file().sync_all().map_err(|_| "export_write")?;
        file.persist(path).map_err(|_| "export_write")?;
        Ok(())
    }
}
impl Drop for Supervisor {
    fn drop(&mut self) {
        let _ = self
            .client
            .post(format!("{}/shutdown", self.base))
            .bearer_auth(&self.token)
            .timeout(Duration::from_secs(1))
            .send();
        // Worker and downloader have bounded 10 s + 35 s shutdown waits.
        let deadline = Instant::now() + Duration::from_secs(50);
        while Instant::now() < deadline {
            if matches!(self.child.try_wait(), Ok(Some(_))) {
                return;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn development_resolution_never_leaks_into_release() {
        let dir = tempfile::tempdir().unwrap();
        let source = dir.path();
        let python = source.join(if cfg!(windows) {
            ".venv/Scripts/python.exe"
        } else {
            ".venv/bin/python"
        });
        std::fs::create_dir_all(python.parent().unwrap()).unwrap();
        std::fs::write(&python, b"test").unwrap();
        let sidecar = source.join("missing-runtime");
        assert_eq!(
            runtime_program(sidecar.clone(), source, true, None),
            (python, true)
        );
        assert_eq!(
            runtime_program(sidecar.clone(), source, false, Some("evil".into())),
            (sidecar.clone(), false)
        );
        std::fs::write(&sidecar, b"test").unwrap();
        assert_eq!(
            runtime_program(sidecar.clone(), source, true, None),
            (sidecar, false)
        );
    }
    #[test]
    fn failed_spawn_records_actionable_system_error() {
        let root = tempfile::tempdir().unwrap();
        let missing = root.path().join("missing-runtime");
        let error = match Supervisor::launch(&missing, false, root.path()) {
            Ok(_) => panic!("missing executable started"),
            Err(error) => error,
        };
        assert_eq!(error, "runtime_executable_missing");
        let log = std::fs::read_to_string(root.path().join("logs/sidecar-stderr.log")).unwrap();
        assert!(log.contains("missing-runtime") && log.contains("os_error="));
    }
    #[cfg(unix)]
    #[test]
    fn denied_spawn_is_distinguished_from_missing_file() {
        use std::os::unix::fs::PermissionsExt;
        let root = tempfile::tempdir().unwrap();
        let program = root.path().join("denied-runtime");
        std::fs::write(&program, b"#!/bin/sh\nexit 0\n").unwrap();
        std::fs::set_permissions(&program, std::fs::Permissions::from_mode(0o600)).unwrap();
        let error = match Supervisor::launch(&program, false, root.path()) {
            Ok(_) => panic!("non-executable file started"),
            Err(error) => error,
        };
        assert_eq!(error, "runtime_executable_denied");
    }
    #[test]
    fn routes() {
        assert!(allowed("POST", "/v1/search"));
        assert!(!allowed("GET", "/v1/search"));
        assert!(!allowed("POST", "/v1/search/../storage"));
        assert!(allowed("GET", "/health"));
        assert!(allowed("GET", "/v1/storage"));
        assert!(allowed("POST", "/v1/storage/waveforms/clear"));
        assert!(!allowed("DELETE", "/v1/storage"));
        assert!(!allowed("POST", "/v1/storage/models/clear"));
        assert!(allowed("POST", "/v1/transcripts/import"));
        assert!(!allowed("GET", "/v1/transcripts/import"));
        assert!(allowed(
            "GET",
            "/v1/assets/11111111-1111-4111-8111-111111111111/waveform"
        ));
        assert!(!allowed("GET", "/v1/assets/../waveform"));
        let id = "11111111-1111-4111-8111-111111111111";
        assert!(allowed(
            "POST",
            &format!("/v1/projects/{id}/documents/timeline/history")
        ));
        assert!(allowed(
            "POST",
            &format!("/v1/projects/{id}/documents/timeline/restore")
        ));
        assert!(!allowed(
            "GET",
            &format!("/v1/projects/{id}/documents/timeline/restore")
        ));
        assert!(!allowed(
            "POST",
            "/v1/projects/no/documents/timeline/restore"
        ));
        assert!(allowed("POST", "/v1/jobs"));
        assert!(allowed("GET", &format!("/v1/jobs/{id}/status")));
        assert!(!allowed("GET", "/v1/jobs/no/status"));
        assert!(allowed("POST", "/v1/models/whisper-small/install"));
        assert!(!allowed("POST", "/v1/models/../install"));
        assert!(!allowed("POST", "/v1/models/%2e%2e/install"));
        assert!(!allowed("POST", "/v1/models/model?x=1/install"));
        assert!(!allowed("POST", "/v1/models/model/execute"));
        assert!(allowed("GET", "/v1/jobs/archive"));
        assert!(allowed("POST", "/v1/jobs/archive/restore"));
        for p in [
            "http://evil.test",
            "/v1/assets/import",
            "/v1/projects/../../settings",
            "/v1/jobs?x=1",
        ] {
            assert!(!allowed("POST", p))
        }
        assert!(!allowed("DELETE", "/v1/projects/no"));
    }
}
