use nexus_supervisor::Supervisor;
use serde_json::json;
#[test]
#[ignore = "requires installed nexus-runtime and NEXUS_TEST_PYTHON"]
fn real_runtime_roundtrip() {
    let python = std::env::var_os("NEXUS_TEST_PYTHON").expect("set NEXUS_TEST_PYTHON");
    let root = std::env::temp_dir().join(format!("nexus-supervisor-test-{}", std::process::id()));
    let runtime =
        Supervisor::launch(std::path::Path::new(&python), true, &root).expect("start runtime");
    let project = runtime
        .request("POST", "/v1/projects", Some(json!({"name":"Round trip"})))
        .expect("create project");
    assert_eq!(project["name"], "Round trip");
    let projects = runtime.request("GET", "/v1/projects", None).expect("list");
    assert_eq!(projects.as_array().expect("array").len(), 1);
    assert!(runtime.request("POST", "/v1/assets/import", None).is_err());
    let mut wav = b"RIFF".to_vec();
    wav.extend(38u32.to_le_bytes());
    wav.extend(b"WAVEfmt ");
    wav.extend(16u32.to_le_bytes());
    wav.extend(1u16.to_le_bytes());
    wav.extend(1u16.to_le_bytes());
    wav.extend(24000u32.to_le_bytes());
    wav.extend(48000u32.to_le_bytes());
    wav.extend(2u16.to_le_bytes());
    wav.extend(16u16.to_le_bytes());
    wav.extend(b"data");
    wav.extend(2u32.to_le_bytes());
    wav.extend(1000i16.to_le_bytes());
    assert!(nexus_supervisor::valid_recording(&wav));
    let request_id = "0cc98c61-63ab-4f6f-89ef-c69b9a3c81e0";
    let asset = runtime
        .recording(project["id"].as_str().unwrap(), &wav, request_id)
        .expect("recording import");
    assert_eq!(asset["name"], "Recording.wav");
    let repeated = runtime
        .recording(project["id"].as_str().unwrap(), &wav, request_id)
        .unwrap();
    assert_eq!(asset["id"], repeated["id"]);
    assert_eq!(runtime.audio(asset["id"].as_str().unwrap()).unwrap(), wav);
    assert!(runtime.recording("../../escape", &wav, request_id).is_err());
    wav[22] = 3;
    assert!(!nexus_supervisor::valid_recording(&wav));
    assert!(runtime
        .recording(project["id"].as_str().unwrap(), &wav, request_id)
        .is_err());
    drop(runtime);
    let restarted =
        Supervisor::launch(std::path::Path::new(&python), true, &root).expect("restart");
    assert_eq!(
        restarted
            .request("GET", "/v1/projects", None)
            .expect("list")[0]["id"],
        project["id"]
    );
    drop(restarted);
    std::fs::remove_dir_all(root).expect("cleanup");
}
