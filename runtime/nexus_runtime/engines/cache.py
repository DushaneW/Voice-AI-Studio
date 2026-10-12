"""Process-wide cache of loaded inference engines.

Loading a Whisper or Kokoro session costs seconds and hundreds of MB, so it is
done once per (engine, model directory, options) and reused by later jobs. The
job worker runs one inference at a time; the lock only protects the dictionary.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable


class EngineCache:
    def __init__(self, max_entries: int = 2):
        self.max_entries = max_entries
        self._entries: OrderedDict[tuple[Hashable, ...], object] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple[Hashable, ...], factory: Callable[[], object]):
        """Return the cached engine for key, building it with factory on a miss."""
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                return self._entries[key]
        engine = factory()  # outside the lock: loading is slow
        with self._lock:
            self._entries[key] = engine
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
        return engine

    def invalidate(self, model_path: object) -> int:
        """Drop every engine loaded from model_path (second key element)."""
        target = str(model_path)
        with self._lock:
            stale = [key for key in self._entries if str(key[1]) == target]
            for key in stale:
                del self._entries[key]
        return len(stale)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


CACHE = EngineCache()
