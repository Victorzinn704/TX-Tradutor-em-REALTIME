from __future__ import annotations

from dataclasses import replace

import numpy as np

SOURCE_PROFILE_OVERRIDES = {
    "mic": {},
    "system": {
        "buffer_min_s": 0.34,
        "buffer_flush_s": 1.35,
        "partial_flush_s": 1.0,
        "silence_chunks": 3,
        "queue_seconds": 1.8,
        "whisper_vad": True,
        "min_speech_duration_ms": 130,
        "min_silence_duration_ms": 180,
        "speech_pad_ms": 90,
    },
    # Perfil para saída do sistema em inglês com Distil-Whisper EN-only.
    # Flush mais agressivo: conteúdo de sistema tende a ser mais limpo
    # (sem ruído de fundo), então buffers menores são seguros.
    # force_language trava o pipeline em EN imediatamente — sem autodetect.
    "system_en": {
        "buffer_min_s": 0.25,
        "buffer_flush_s": 1.0,
        "partial_flush_s": 0.65,
        "silence_chunks": 2,
        "queue_seconds": 1.2,
        "whisper_vad": True,
        "min_speech_duration_ms": 100,
        "min_silence_duration_ms": 150,
        "speech_pad_ms": 60,
        "force_language": "en",
    },
}


def apply_source_profile(tuning, source_kind: str):
    overrides = SOURCE_PROFILE_OVERRIDES.get(source_kind, {})
    if not overrides:
        return tuning
    return replace(tuning, **overrides)


def prepare_audio_for_asr(audio: np.ndarray, source_kind: str) -> np.ndarray:
    if audio.size == 0:
        return audio

    normalized = np.asarray(audio, dtype=np.float32).copy()
    peak = float(np.max(np.abs(normalized)))
    if peak > 0:
        target_peak = 0.88 if source_kind == "mic" else 0.82
        peak_gain_cap = 2.2 if source_kind == "mic" else 4.0
        peak_gain = min(peak_gain_cap, target_peak / peak)
        if peak_gain > 1.05:
            normalized *= peak_gain

    if source_kind in ("system", "system_en"):
        rms = float(np.sqrt(np.mean(np.square(normalized)))) if normalized.size else 0.0
        if 0.0 < rms < 0.09:
            rms_gain = min(3.2, 0.09 / max(rms, 1e-6))
            if rms_gain > 1.05:
                normalized *= rms_gain

    return np.clip(normalized, -1.0, 1.0)
