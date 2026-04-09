"""Testes para o TranslationCache (LRU thread-safe com OrderedDict)."""
from __future__ import annotations

import threading

from rtxlator.cache import TranslationCache


class TestCacheBasic:
    """Operações básicas de get/put."""

    def test_put_and_get(self):
        cache = TranslationCache(max_size=10)
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_missing_returns_none(self):
        cache = TranslationCache(max_size=10)
        assert cache.get("nonexistent") is None

    def test_put_overwrite(self):
        cache = TranslationCache(max_size=10)
        cache.put("key1", "old")
        cache.put("key1", "new")
        assert cache.get("key1") == "new"


class TestCacheEviction:
    """Testa LRU eviction."""

    def test_evicts_oldest_when_full(self):
        cache = TranslationCache(max_size=3)
        cache.put("a", "1")
        cache.put("b", "2")
        cache.put("c", "3")
        cache.put("d", "4")  # should evict "a"
        assert cache.get("a") is None
        assert cache.get("b") == "2"

    def test_access_prevents_eviction(self):
        cache = TranslationCache(max_size=3)
        cache.put("a", "1")
        cache.put("b", "2")
        cache.put("c", "3")
        cache.get("a")  # access "a", making "b" the oldest
        cache.put("d", "4")  # should evict "b", not "a"
        assert cache.get("a") == "1"
        assert cache.get("b") is None

    def test_overwrite_preserves_order(self):
        cache = TranslationCache(max_size=3)
        cache.put("a", "1")
        cache.put("b", "2")
        cache.put("c", "3")
        cache.put("a", "updated")  # re-put "a", making "b" oldest
        cache.put("d", "4")  # should evict "b"
        assert cache.get("a") == "updated"
        assert cache.get("b") is None


class TestCacheThreadSafety:
    """Testa acesso concorrente."""

    def test_concurrent_put_get(self):
        cache = TranslationCache(max_size=100)
        errors = []

        def writer(prefix: str):
            try:
                for i in range(50):
                    cache.put(f"{prefix}_{i}", f"val_{i}")
            except Exception as e:
                errors.append(e)

        def reader(prefix: str):
            try:
                for i in range(50):
                    cache.get(f"{prefix}_{i}")
            except Exception as e:
                errors.append(e)

        threads = []
        for p in ("A", "B", "C", "D"):
            threads.append(threading.Thread(target=writer, args=(p,)))
            threads.append(threading.Thread(target=reader, args=(p,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
