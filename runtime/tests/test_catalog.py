import re

from nexus_runtime.models import CATALOG

WHISPER = ["whisper-tiny", "whisper-base", "whisper-small", "whisper-medium"]


def test_catalog_ids_are_unique():
    ids = [m["id"] for m in CATALOG]
    assert len(ids) == len(set(ids))


def test_whisper_sizes_are_listed_smallest_first():
    whisper = [m for m in CATALOG if m["engine"] == "faster-whisper"]
    assert [m["id"] for m in whisper] == WHISPER
    sizes = [sum(f["size"] for f in m["files"]) for m in whisper]
    assert sizes == sorted(sizes)


def test_whisper_files_are_pinned_to_the_catalog_revision():
    for model in (m for m in CATALOG if m["engine"] == "faster-whisper"):
        assert re.fullmatch(r"[0-9a-f]{40}", model["revision"])
        assert {f["name"] for f in model["files"]} == {
            "config.json",
            "model.bin",
            "tokenizer.json",
            "vocabulary.txt",
        }
        repo = "https://huggingface.co/Systran/faster-" + model["id"]
        for f in model["files"]:
            assert f["url"] == f"{repo}/resolve/{model['revision']}/{f['name']}"
            assert re.fullmatch(r"[0-9a-f]{64}", f["sha256"])
            assert f["size"] > 0
