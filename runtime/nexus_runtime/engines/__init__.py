"""Optional inference adapters; imports do not trigger network/model loading."""

from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata, util

from ..errors import DomainError

ENGINES = [
    {
        "id": "faster-whisper",
        "module": "faster_whisper",
        "name": "Faster Whisper",
        "license": "MIT",
        "capabilities": ["ASR"],
        "devices": ["cpu", "cuda"],
        "platforms": ["Windows", "Linux", "Darwin"],
    },
    {
        "id": "kokoro-onnx",
        "module": "kokoro_onnx",
        "name": "Kokoro ONNX",
        "license": "MIT",
        "capabilities": ["TTS"],
        "devices": ["cpu"],
        "platforms": ["Windows", "Linux", "Darwin"],
    },
]


@dataclass(frozen=True)
class EngineAdapter:
    """Developer SDK v1: optional imports belong inside the supplied callables."""

    descriptor: dict
    synthesize: Callable | None = None
    transcribe: Callable | None = None
    protocol_version: int = 1


_adapters: dict[str, EngineAdapter] = {}


def register_engine(adapter: EngineAdapter):
    import re

    identifier = adapter.descriptor.get("id", "")
    if not isinstance(identifier, str) or not re.fullmatch(
        r"[a-z][a-z0-9-]{1,63}", identifier
    ):
        raise DomainError("invalid_engine_id")
    if adapter.protocol_version != 1 or not (adapter.synthesize or adapter.transcribe):
        raise DomainError("invalid_engine_adapter")
    if not all(
        key in adapter.descriptor
        for key in ("module", "name", "license", "capabilities", "devices", "platforms")
    ):
        raise DomainError("invalid_engine_descriptor")
    if identifier in _adapters:
        raise DomainError("engine_already_registered")
    _adapters[identifier] = adapter


def require_engine(identifier, operation):
    adapter = _adapters.get(identifier)
    callback = {"tts": "synthesize", "transcribe": "transcribe"}.get(operation)
    if adapter is None or callback is None or getattr(adapter, callback) is None:
        raise DomainError("invalid_engine")
    return adapter


def _synthesize(*args, **kwargs):
    from .kokoro import synthesize

    return synthesize(*args, **kwargs)


def _transcribe(*args, **kwargs):
    from .whisper import transcribe

    return transcribe(*args, **kwargs)


register_engine(EngineAdapter(ENGINES[0], transcribe=_transcribe))
register_engine(EngineAdapter(ENGINES[1], synthesize=_synthesize))


def registry():
    result = []
    for adapter in _adapters.values():
        engine = adapter.descriptor
        try:
            installed = util.find_spec(engine["module"]) is not None
        except (ImportError, ValueError):
            installed = False
        try:
            version = metadata.version(engine["id"]) if installed else None
        except metadata.PackageNotFoundError:
            version = None
        result.append(
            {
                **engine,
                "installed": installed,
                "version": version,
                "protocol_version": adapter.protocol_version,
                "operations": [
                    operation
                    for operation in ("tts", "transcribe")
                    if getattr(
                        adapter, "synthesize" if operation == "tts" else "transcribe"
                    )
                    is not None
                ],
            }
        )
    return result


def hardware():
    try:
        import ctranslate2

        count = ctranslate2.get_cuda_device_count()
        return {
            "state": "available" if count else "unavailable",
            "cuda_devices": count,
            "reason": None if count else "No CUDA device detected",
        }
    except (ImportError, RuntimeError, OSError):
        return {
            "state": "unavailable",
            "cuda_devices": 0,
            "reason": "CUDA probe unavailable",
        }
