from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol


def make_translation_cache_key(text: str, lang: str, *, direction: str = "audio", state: str = "raw") -> str:
    return f"{direction}::{state}::{lang or 'auto'}::{text.strip()}"


class CacheProtocol(Protocol):
    def get(self, key: str) -> str | None: ...
    def put(self, key: str, value: str) -> None: ...


class TranslatorProtocol(Protocol):
    interpretation_mode: str
    target_lang: str

    def normalize_lookup_text(self, text: str, source_lang: str | None) -> str: ...
    def translate(
        self,
        text: str,
        src_lang: str = "auto",
        *,
        prefer_context: bool = False,
        context_segments: list[str] | None = None,
    ) -> tuple[str, str]: ...


@dataclass(frozen=True)
class TextEnvelope:
    source: str
    raw_text: str
    source_lang: str | None
    target_lang: str
    direction: str = "audio"
    translation_state: str = "raw"
    is_partial: bool = False
    prefer_context: bool = False
    context_segments: tuple[str, ...] = field(default_factory=tuple)
    conversation_id: str = "default"


@dataclass(frozen=True)
class TextResolution:
    original: str
    translated: str
    provider: str
    cache_hit: bool
    translate_ms: float
    send_text: str


class TextProcessor:
    def __init__(self, translator: TranslatorProtocol, cache: CacheProtocol):
        self.translator = translator
        self.cache = cache

    def resolve(self, envelope: TextEnvelope) -> TextResolution:
        lookup_text = self.translator.normalize_lookup_text(envelope.raw_text, envelope.source_lang)
        if not lookup_text:
            return TextResolution("", "", "identity", False, 0.0, "")

        if envelope.translation_state == "translated_upstream":
            return TextResolution(
                original=lookup_text,
                translated=lookup_text,
                provider="upstream",
                cache_hit=False,
                translate_ms=0.0,
                send_text=lookup_text,
            )

        translate_t0 = time.perf_counter()
        if envelope.prefer_context:
            translated, provider = self.translator.translate(
                lookup_text,
                src_lang=envelope.source_lang or "auto",
                prefer_context=True,
                context_segments=list(envelope.context_segments),
                allow_remote_fallback=not envelope.is_partial,
            )
            translated = translated or lookup_text
            return TextResolution(
                original=lookup_text,
                translated=translated,
                provider=provider,
                cache_hit=False,
                translate_ms=(time.perf_counter() - translate_t0) * 1000,
                send_text=translated,
            )

        cache_key = make_translation_cache_key(
            lookup_text,
            envelope.source_lang or "auto",
            direction=envelope.direction,
            state=envelope.translation_state,
        )
        cached = self.cache.get(cache_key)
        if cached is not None:
            return TextResolution(
                original=lookup_text,
                translated=cached,
                provider="cache",
                cache_hit=True,
                translate_ms=(time.perf_counter() - translate_t0) * 1000,
                send_text=cached,
            )

        translated, provider = self.translator.translate(
            lookup_text,
            src_lang=envelope.source_lang or "auto",
            prefer_context=False,
            allow_remote_fallback=not envelope.is_partial,
        )
        translated = translated or lookup_text
        self.cache.put(cache_key, translated)
        return TextResolution(
            original=lookup_text,
            translated=translated,
            provider=provider,
            cache_hit=False,
            translate_ms=(time.perf_counter() - translate_t0) * 1000,
            send_text=translated,
        )
