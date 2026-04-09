#!/usr/bin/env python3
"""
Script de diagnostico - lista dispositivos de audio e verifica CUDA.
Execute antes do tradutor para confirmar que tudo esta OK.
"""
import subprocess
import sys

print("=" * 60)
print("  DIAGNOSTICO DO SISTEMA")
print("=" * 60)

# ── CUDA ──────────────────────────────────────────────────────────
print("\n[1] CUDA / GPU")
try:
    import ctranslate2
    n = ctranslate2.get_cuda_device_count()
    if n > 0:
        print(f"  [OK] CUDA disponivel - {n} dispositivo(s) encontrado(s)")
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            for i, line in enumerate(result.stdout.strip().splitlines()):
                print(f"    GPU {i}: {line}")
    else:
        print("  [ERRO] Nenhuma GPU CUDA detectada (ctranslate2 instalado, mas sem CUDA)")
except ImportError:
    print("  [ERRO] ctranslate2 nao instalado")
except Exception as e:
    print(f"  [ERRO] Falha ao verificar CUDA: {e}")

try:
    import torch
    print(f"  PyTorch CUDA: {('OK ' + str(torch.version.cuda)) if torch.cuda.is_available() else 'nao disponivel'}")
    if torch.cuda.is_available():
        print(f"  GPU: {torch.cuda.get_device_name(0)}")
        vram = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        print(f"  VRAM: {vram:.1f} GB")
except ImportError:
    pass

# ── Áudio ─────────────────────────────────────────────────────────
print("\n[2] DISPOSITIVOS DE AUDIO")
try:
    import pyaudiowpatch as pyaudio
    p = pyaudio.PyAudio()

    print(f"\n  {'ID':<4} {'E/S':<6} {'SR':<8} {'Ch':<4} {'Loop':<6} {'Host':<12} {'Nome'}")
    print("  " + "-" * 72)

    redragon_found = []

    for i in range(p.get_device_count()):
        d = p.get_device_info_by_index(i)
        name      = d["name"]
        sr        = int(d["defaultSampleRate"])
        ch_in     = int(d["maxInputChannels"])
        ch_out    = int(d["maxOutputChannels"])
        is_loop   = d.get("isLoopbackDevice", False)
        is_input  = ch_in > 0
        is_output = ch_out > 0
        host_name = p.get_host_api_info_by_index(int(d["hostApi"]))["name"]

        io = []
        if is_input:  io.append("IN")
        if is_output: io.append("OUT")
        io_str = "/".join(io) if io else "-"

        loop_str = "YES" if is_loop else ""

        # Destaca RedDragon
        is_rd = "redragon" in name.lower() or "red dragon" in name.lower()
        marker = " <- REDRAGON" if is_rd else ""
        if is_rd:
            redragon_found.append((i, name, io_str, is_loop))

        print(f"  {i:<4} {io_str:<6} {sr:<8} {ch_in:<4} {loop_str:<6} {host_name[:12]:<12} {name}{marker}")

    print()
    if redragon_found:
        print("  [REDRAGON encontrado]")
        for idx, name, io, loop in redragon_found:
            print(f"    ID={idx}  {name}  ({io}){' [LOOPBACK]' if loop else ''}")
    else:
        print("  [AVISO] RedDragon nao encontrado pelo nome.")
        print("          Verifique o ID do microfone e do headset manualmente acima.")

    try:
        def_in  = p.get_default_input_device_info()
        def_out = p.get_default_output_device_info()
        print(f"\n  Padrão INPUT  (ID {int(def_in['index'])}): {def_in['name']}")
        print(f"  Padrão OUTPUT (ID {int(def_out['index'])}): {def_out['name']}")
    except Exception:
        pass

    # Loopbacks
    print("\n  [Dispositivos Loopback (captura de saida)]")
    loops = [(i, p.get_device_info_by_index(i)) for i in range(p.get_device_count())
             if p.get_device_info_by_index(i).get("isLoopbackDevice", False)]
    if loops:
        for i, d in loops:
            print(f"    ID={i}  {d['name']}")
        print("\n  [Recomendacao para video/chamada]")
        print("    - escolha o loopback do mesmo endpoint onde a chamada esta saindo")
        print("    - fixe o ID com --spk-id para evitar o auto-select errado")
        print("    - prefira SOURCE=en/es e perfil balanced quando for loopback")
    else:
        print("    Nenhum loopback encontrado. (Driver WASAPI nao suporta?)")

    p.terminate()

except ImportError:
    print("  pyaudiowpatch não instalado. Execute instalar.bat primeiro.")
except Exception as e:
    print(f"  Erro: {e}")

print("\n" + "=" * 60)
print("  Diagnostico concluido.")
print("=" * 60)
