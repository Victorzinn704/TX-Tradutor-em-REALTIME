"""Cache LRU thread-safe para traduções."""
from __future__ import annotations

import threading
from collections import deque

from .constants import TRANS_CACHE_SIZE


class TranslationCache:
    def __init__(self, max_size: int = TRANS_CACHE_SIZE):
        self._cache: dict[str, str] = {}
        self._order: deque[str]     = deque(maxlen=max_size)
        self._max   = max_size
        self._lock  = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            value = self._cache.get(key)
            if value is None:
                return None
            try:
                self._order.remove(key)
            except ValueError:
                pass
            self._order.append(key)
            return value

    def put(self, key: str, value: str) -> None:
        with self._lock:
            if key in self._cache:
                try:
                    self._order.remove(key)
                except ValueError:
                    pass
            elif len(self._order) >= self._max:
                oldest = self._order.popleft()
                self._cache.pop(oldest, None)
            self._order.append(key)
            self._cache[key] = value
