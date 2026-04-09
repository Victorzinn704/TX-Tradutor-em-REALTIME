"""
Fix Windows: DLLs NVIDIA instaladas via pip não entram no PATH do sistema.

ctranslate2 carrega cublas64_12.dll via LoadLibrary() direto no C++ no
momento da PRIMEIRA INFERÊNCIA (lazy load). Três mecanismos cobrem todos
os caminhos de busca do Windows:

  1. os.environ["PATH"]    → afeta LoadLibrary("nome.dll") no C/C++
  2. os.add_dll_directory() → afeta extensões .pyd carregadas pelo Python
  3. ctypes.CDLL(path)     → pré-carrega a DLL no cache de módulos do processo;
                             qualquer LoadLibrary("cublas64_12.dll") posterior
                             encontra ela já carregada e retorna o handle existente

Sem isso: "Library cublas64_12.dll is not found or cannot be loaded"
"""
from __future__ import annotations

import os
import sys


def preload_nvidia_dlls() -> None:
    """Pré-carrega DLLs NVIDIA conhecidas instaladas via pip. Deve ser chamado ANTES de qualquer import pesado."""
    if sys.platform != "win32":
        return

    import ctypes
    import re
    import site

    # Só carrega DLLs com nomes reconhecidos de bibliotecas NVIDIA
    _KNOWN_PATTERNS = re.compile(
        r"^(cublas|cublasLt|cudnn|cudart|cufft|curand|cusolver|cusparse|nvrtc|nvJitLink)"
        r"(64)?(_\d+)?\.dll$",
        re.IGNORECASE,
    )

    for sp in site.getsitepackages():
        nvidia_root = os.path.join(sp, "nvidia")
        if not os.path.isdir(nvidia_root):
            continue
        for pkg in os.listdir(nvidia_root):
            bin_dir = os.path.join(nvidia_root, pkg, "bin")
            if not os.path.isdir(bin_dir):
                continue
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
            try:
                os.add_dll_directory(bin_dir)
            except Exception:
                pass
            for dll_name in os.listdir(bin_dir):
                if _KNOWN_PATTERNS.match(dll_name):
                    try:
                        ctypes.CDLL(os.path.join(bin_dir, dll_name))
                    except Exception:
                        pass
