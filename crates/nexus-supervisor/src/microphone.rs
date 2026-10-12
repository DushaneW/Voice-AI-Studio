use std::{
    sync::Mutex,
    time::{Duration, Instant},
};
#[derive(Default)]
pub struct MicrophonePermit(Mutex<Option<Instant>>);
impl MicrophonePermit {
    pub fn set(&self, enabled: bool) -> Result<(), String> {
        *self.0.lock().map_err(|_| "microphone_permission_lock")? = enabled.then(Instant::now);
        Ok(())
    }
    pub fn consume(&self) -> bool {
        self.0
            .lock()
            .ok()
            .and_then(|mut value| value.take())
            .is_some_and(|issued| issued.elapsed() < Duration::from_secs(30))
    }
}
pub fn local_origin(url: &reqwest::Url, development: bool) -> bool {
    if !url.username().is_empty() || url.password().is_some() {
        return false;
    }
    match (url.scheme(), url.host_str(), url.port()) {
        ("tauri", Some("localhost"), None) => true,
        ("http" | "https", Some("tauri.localhost"), None) => true,
        ("http", Some("localhost" | "127.0.0.1"), Some(1420)) => development,
        _ => false,
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn permission_is_one_shot_and_revocable() {
        let permit = MicrophonePermit::default();
        assert!(!permit.consume());
        permit.set(true).unwrap();
        assert!(permit.consume());
        assert!(!permit.consume());
        permit.set(true).unwrap();
        permit.set(false).unwrap();
        assert!(!permit.consume());
    }
    #[test]
    fn only_local_origins() {
        for url in [
            "https://example.com",
            "http://localhost:1420",
            "https://tauri.localhost.evil.test",
        ] {
            assert!(!local_origin(&reqwest::Url::parse(url).unwrap(), false));
        }
        assert!(local_origin(
            &reqwest::Url::parse("tauri://localhost/").unwrap(),
            false
        ));
        assert!(local_origin(
            &reqwest::Url::parse("http://localhost:1420/").unwrap(),
            true
        ));
    }
}
