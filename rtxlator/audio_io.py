"""Abertura e configuração de streams de áudio WASAPI."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pyaudiowpatch as pyaudio

from .constants import WHISPER_SR

if TYPE_CHECKING:
    from .pipeline import AudioPipeline


def make_stream_callback(pipe: "AudioPipeline"):
    """Factory de callback — evita problema de closure em loop."""
    def _cb(in_data, frame_count, time_info, status):
        pipe.feed(in_data)
        return (None, pyaudio.paContinue)
    return _cb


def select_mic_info(
    p:            pyaudio.PyAudio,
    forced_id:    int | None,
    redragon_id:  int | None,
) -> tuple[dict | None, str | None]:
    if forced_id is not None:
        return p.get_device_info_by_index(forced_id), None
    if redragon_id is not None:
        return (
            p.get_device_info_by_index(redragon_id),
            f"Microfone RedDragon detectado (ID {redragon_id})",
        )
    try:
        return p.get_default_input_device_info(), "RedDragon nao encontrado - usando microfone padrao"
    except Exception:
        return None, None


def select_loopback_info(
    p:                pyaudio.PyAudio,
    forced_id:        int | None,
    redragon_loop_id: int | None,
) -> tuple[dict | None, str | None]:
    if forced_id is not None:
        return p.get_device_info_by_index(forced_id), None
    if redragon_loop_id is not None:
        return (
            p.get_device_info_by_index(redragon_loop_id),
            f"Loopback RedDragon detectado (ID {redragon_loop_id})",
        )
    for i in range(p.get_device_count()):
        d = p.get_device_info_by_index(i)
        if d.get("isLoopbackDevice", False) and int(d["maxInputChannels"]) > 0:
            return d, None
    return None, None


def _pick_input_format(
    p:               pyaudio.PyAudio,
    device_index:    int,
    default_sr:      int,
    default_channels: int,
) -> tuple[int, int]:
    channel_candidates: list[int] = []
    if default_channels >= 1:
        channel_candidates.append(1)
    if default_channels not in channel_candidates:
        channel_candidates.append(default_channels)

    for sr in (WHISPER_SR, default_sr):
        for channels in channel_candidates:
            try:
                if p.is_format_supported(
                    sr,
                    input_device=device_index,
                    input_channels=channels,
                    input_format=pyaudio.paFloat32,
                ):
                    return sr, channels
            except Exception:
                continue

    return default_sr, default_channels


def setup_mic(
    p:    pyaudio.PyAudio,
    info: dict,
    pipe: "AudioPipeline",
) -> tuple[pyaudio.Stream, dict, int, int]:
    """Abre stream do microfone (prefere 16k mono)."""
    sr, channels = _pick_input_format(p, int(info["index"]), int(info["defaultSampleRate"]), 1)
    chunk = max(1, int(sr * pipe.tuning.chunk_seconds))
    pipe.orig_sr  = sr
    pipe.channels = channels
    stream = p.open(
        format=pyaudio.paFloat32,
        channels=channels,
        rate=sr,
        input=True,
        input_device_index=int(info["index"]),
        frames_per_buffer=chunk,
        stream_callback=make_stream_callback(pipe),
    )
    return stream, info, sr, channels


def setup_loopback(
    p:    pyaudio.PyAudio,
    info: dict,
    pipe: "AudioPipeline",
) -> tuple[pyaudio.Stream, dict, int, int]:
    """Abre stream de loopback WASAPI."""
    sr, ch = _pick_input_format(
        p, int(info["index"]), int(info["defaultSampleRate"]), int(info["maxInputChannels"])
    )
    chunk = max(1, int(sr * pipe.tuning.chunk_seconds))
    pipe.orig_sr  = sr
    pipe.channels = ch
    stream = p.open(
        format=pyaudio.paFloat32,
        channels=ch,
        rate=sr,
        input=True,
        input_device_index=int(info["index"]),
        frames_per_buffer=chunk,
        stream_callback=make_stream_callback(pipe),
    )
    return stream, info, sr, ch
