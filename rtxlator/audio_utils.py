"""Utilitários de processamento de sinal de áudio."""
from __future__ import annotations

from math import gcd

import numpy as np

from .constants import SILENCE_RMS_TH, WHISPER_SR


def to_mono(audio: np.ndarray, channels: int) -> np.ndarray:
    if channels == 1:
        return audio
    return audio.reshape(-1, channels).mean(axis=1).astype(np.float32)


def to_16k(audio: np.ndarray, orig_sr: int) -> np.ndarray:
    if orig_sr == WHISPER_SR:
        return audio
    from scipy.signal import resample_poly

    g = gcd(orig_sr, WHISPER_SR)
    return resample_poly(audio, WHISPER_SR // g, orig_sr // g).astype(np.float32)


def rms(chunk: np.ndarray) -> float:
    return float(np.sqrt(np.mean(chunk ** 2) + 1e-10))


def is_speech(chunk: np.ndarray) -> bool:
    return rms(chunk) > SILENCE_RMS_TH
