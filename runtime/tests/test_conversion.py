import shutil
import subprocess
import wave

import numpy as np
import pytest
from nexus_runtime.core import Core


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is optional")
@pytest.mark.parametrize("extension", ["mp3", "m4a", "flac", "ogg", "aac"])
def test_real_compressed_import_preserves_rate_channels_and_cleans_temp(
    tmp_path, extension
):
    core = Core(tmp_path / "data")
    project = core.create_project("Decode")
    source = tmp_path / "source.wav"
    with wave.open(str(source), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(np.full((4800, 2), 3000, dtype="<i2").tobytes())
    compressed = tmp_path / f"music.{extension}"
    subprocess.run(
        [shutil.which("ffmpeg"), "-v", "error", "-i", str(source), str(compressed)],
        check=True,
    )
    asset = core.import_file(project["id"], compressed)
    assert asset["name"] == compressed.name
    assert asset["sample_rate"] == 48000 and asset["channels"] == 2
    assert asset["duration"] >= 0.09
    assert not list(core.db.root.glob("decode-*"))


def test_missing_decoder_and_invalid_input_create_no_asset(tmp_path, monkeypatch):
    core = Core(tmp_path / "data")
    project = core.create_project("Decode")
    source = tmp_path / "bad.mp3"
    source.write_bytes(b"not audio")
    monkeypatch.setattr("nexus_runtime.conversion.shutil.which", lambda _: None)
    with pytest.raises(ValueError, match="ffmpeg_required"):
        core.import_file(project["id"], source)
    assert not list(core.assets.iterdir())
