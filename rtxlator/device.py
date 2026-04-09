"""Detecção de hardware e listagem de dispositivos de áudio."""
from __future__ import annotations

import pyaudiowpatch as pyaudio

from .constants import console


def detect_device() -> tuple[str, str, str]:
    """Retorna (device, compute_type, info_str). Prefere CUDA int8_float16; fallback CPU int8."""
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "int8_float16", "CUDA GPU detectada"
    except Exception:
        pass

    try:
        import subprocess
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip():
            gpu_info = r.stdout.strip().splitlines()[0]
            return "cpu", "int8", f"GPU detectada ({gpu_info}) mas CUDA nao configurado — usando CPU"
    except Exception:
        pass

    return "cpu", "int8", "GPU nao encontrada — usando CPU"


def find_redragon_devices(p: pyaudio.PyAudio) -> dict:
    """Procura dispositivos RedDragon. Retorna {'mic': id|None, 'loopback': id|None}."""
    PATTERNS = ("redragon", "red dragon", "rdg")
    mic_id      = None
    loopback_id = None

    for i in range(p.get_device_count()):
        d    = p.get_device_info_by_index(i)
        name = d["name"].lower()
        is_rd = any(pat in name for pat in PATTERNS)
        if not is_rd:
            continue
        if d.get("isLoopbackDevice", False):
            loopback_id = i
        elif int(d["maxInputChannels"]) > 0 and mic_id is None:
            mic_id = i

    return {"mic": mic_id, "loopback": loopback_id}


def list_all_devices(p: pyaudio.PyAudio) -> None:
    """Imprime todos os dispositivos de áudio no terminal."""
    console.rule("[bold cyan]Dispositivos de Audio Disponiveis")
    console.print(f"\n  {'ID':<4} {'E/S':<7} {'SR':<8} {'Loop':<6} {'Host':<12} Nome")
    console.print("  " + "-" * 88)

    for i in range(p.get_device_count()):
        d     = p.get_device_info_by_index(i)
        host  = p.get_host_api_info_by_index(int(d["hostApi"]))["name"]
        ch_in = int(d["maxInputChannels"])
        ch_out= int(d["maxOutputChannels"])
        loop  = d.get("isLoopbackDevice", False)
        sr    = int(d["defaultSampleRate"])

        io_parts = []
        if ch_in  > 0: io_parts.append("IN")
        if ch_out > 0: io_parts.append("OUT")
        io_str = "/".join(io_parts) or "-"

        is_rd  = any(x in d["name"].lower() for x in ("redragon", "red dragon"))
        marker = " [bold red]<- REDRAGON[/bold red]" if is_rd else ""
        loop_s = "Y" if loop else ""

        console.print(
            f"  {i:<4} {io_str:<7} {sr:<8} {loop_s:<6} {host[:12]:<12} {d['name']}{marker}"
        )

    console.print()
