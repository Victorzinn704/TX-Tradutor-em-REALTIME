"""Estrutura de dados para um resultado de transcrição + tradução."""
from __future__ import annotations

import time


class Result:
    __slots__ = (
        "source",
        "original",
        "translation",
        "provider",
        "lang",
        "latency_ms",
        "transcribe_ms",
        "translate_ms",
        "cache_hit",
        "ts",
        "is_partial",
    )

    def __init__(
        self,
        source: str,
        original: str,
        translation: str,
        lang: str,
        latency_ms: float,
        is_partial: bool = False,
        transcribe_ms: float = 0.0,
        translate_ms: float = 0.0,
        cache_hit: bool = False,
        provider: str = "identity",
    ):
        self.source        = source
        self.original      = original
        self.translation   = translation
        self.provider      = provider
        self.lang          = lang
        self.latency_ms    = latency_ms
        self.transcribe_ms = transcribe_ms
        self.translate_ms  = translate_ms
        self.cache_hit     = cache_hit
        self.ts            = time.strftime("%H:%M:%S")
        self.is_partial    = is_partial
