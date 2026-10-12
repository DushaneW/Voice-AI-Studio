"""Project templates create editable, empty documents; never synthetic media."""

from .errors import DomainError
from .timeline import validate_tracks


def documents(template):
    names = {
        "empty": [],
        "podcast": ["Host", "Guest", "Music"],
        "multitrack": ["Dialogue", "Music", "Effects", "Ambience"],
        "audiobook": ["Narration", "Music"],
    }
    if template not in names:
        raise DomainError("invalid_project_template")
    if not names[template]:
        return {}
    tracks = [
        {"id": f"track-{i}", "name": name} for i, name in enumerate(names[template])
    ]
    result = {
        "timeline": {
            "clips": [],
            "tracks": list(validate_tracks(tracks, []).values()),
            "sample_rate": 48000,
            "channels": 2,
        }
    }
    if template == "audiobook":
        result["audiobook"] = {
            "chapters": [{"title": "Chapter 1", "text": ""}],
            "gap": 1,
            "voice": "",
            "transcriptId": "",
        }
    return result
