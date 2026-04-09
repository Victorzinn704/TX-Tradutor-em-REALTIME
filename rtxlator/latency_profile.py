"""Perfis de latência para tuning do pipeline de áudio."""
from __future__ import annotations

from dataclasses import dataclass, replace

from .constants import DEFAULT_PROFILE


@dataclass(frozen=True)
class LatencyProfile:
    name: str
    chunk_seconds: float
    buffer_min_s: float
    buffer_flush_s: float
    partial_flush_s: float
    silence_chunks: int
    queue_seconds: float
    whisper_vad: bool
    min_speech_duration_ms: int
    min_silence_duration_ms: int
    speech_pad_ms: int
    without_timestamps: bool = True
    # Se definido, o pipeline trava _locked_lang nesse idioma desde o início —
    # sem nenhum round de autodetect. Útil para perfis EN-only (Distil-Whisper).
    force_language: str | None = None


LATENCY_PROFILES: dict[str, LatencyProfile] = {
    "ultra": LatencyProfile(
        name="ultra",
        chunk_seconds=0.12,
        buffer_min_s=0.24,
        buffer_flush_s=1.0,
        partial_flush_s=0.80,
        silence_chunks=2,
        queue_seconds=1.2,
        whisper_vad=False,
        min_speech_duration_ms=100,
        min_silence_duration_ms=140,
        speech_pad_ms=60,
    ),
    "balanced": LatencyProfile(
        name="balanced",
        chunk_seconds=0.20,
        buffer_min_s=0.50,
        buffer_flush_s=3.0,
        partial_flush_s=1.40,
        silence_chunks=3,
        queue_seconds=3.0,
        whisper_vad=True,
        min_speech_duration_ms=150,
        min_silence_duration_ms=300,
        speech_pad_ms=150,
    ),
    "quality": LatencyProfile(
        name="quality",
        chunk_seconds=0.25,
        buffer_min_s=0.70,
        buffer_flush_s=4.0,
        partial_flush_s=2.20,
        silence_chunks=4,
        queue_seconds=4.0,
        whisper_vad=True,
        min_speech_duration_ms=200,
        min_silence_duration_ms=350,
        speech_pad_ms=180,
    ),
}


def resolve_latency_profile(
    name: str,
    *,
    chunk_seconds: float | None = None,
    buffer_min_s: float | None = None,
    buffer_flush_s: float | None = None,
    partial_flush_s: float | None = None,
    silence_chunks: int | None = None,
) -> LatencyProfile:
    base = LATENCY_PROFILES.get(name, LATENCY_PROFILES[DEFAULT_PROFILE])
    return replace(
        base,
        chunk_seconds=chunk_seconds if chunk_seconds is not None else base.chunk_seconds,
        buffer_min_s=buffer_min_s if buffer_min_s is not None else base.buffer_min_s,
        buffer_flush_s=buffer_flush_s if buffer_flush_s is not None else base.buffer_flush_s,
        partial_flush_s=partial_flush_s if partial_flush_s is not None else base.partial_flush_s,
        silence_chunks=silence_chunks if silence_chunks is not None else base.silence_chunks,
    )
