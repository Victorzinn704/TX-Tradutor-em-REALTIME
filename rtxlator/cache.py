"""Cache LRU thread-safe para traduções.

Usa OrderedDict para operações O(1) em get/put (move_to_end + popitem).
"""
from __future__ import annotations

import threading
from collections import OrderedDict

from .constants import TRANS_CACHE_SIZE


class TranslationCache:
    def __init__(self, max_size: int = TRANS_CACHE_SIZE):
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._max  = max_size
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)
            return self._cache[key]

    def put(self, key: str, value: str) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            elif len(self._cache) >= self._max:
                self._cache.popitem(last=False)
            self._cache[key] = value
