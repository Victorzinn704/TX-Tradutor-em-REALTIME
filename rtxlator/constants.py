"""Constantes globais, console singleton e utilitários de UI."""
from __future__ import annotations

import locale
import os
import sys
from pathlib import Path

from rich import box
from rich.console import Console

# ─── Caminhos ─────────────────────────────────────────────────────────────────

MODELS_DIR   = Path(__file__).resolve().parent.parent / "models"
HF_CACHE_DIR = MODELS_DIR / "hf"

MODELS_DIR.mkdir(parents=True, exist_ok=True)
HF_CACHE_DIR.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("HF_HOME", str(HF_CACHE_DIR))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(HF_CACHE_DIR / "hub"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# Usa MiniSBD (ONNX, sem torch.load) em vez de Stanza para SBD no argostranslate.
# Stanza falha com PyTorch ≥2.6 (weights_only=True) nos modelos bundled.
os.environ.setdefault("ARGOS_CHUNK_TYPE", "MINISBD")

# ─── Parâmetros de áudio / cache ──────────────────────────────────────────────

WHISPER_SR       = 16_000   # Whisper exige 16 kHz
SILENCE_RMS_TH   = 0.006    # RMS abaixo disso = silêncio
TRANS_CACHE_SIZE = 256
DEFAULT_PROFILE  = "ultra"

# ─── Marcadores de contexto (usados pelo GPUTranslator) ───────────────────────

CONTEXT_CURRENT_MARKER = "[[C1]]"
CONTEXT_END_MARKER     = "[[E1]]"

# ─── Console / UI ─────────────────────────────────────────────────────────────

def _is_unicode_capable() -> bool:
    enc = (
        getattr(sys.stdout, "encoding", None)
        or locale.getpreferredencoding(False)
        or ""
    ).lower()
    return "utf" in enc


UNICODE_UI = _is_unicode_capable()
TABLE_BOX  = box.ROUNDED if UNICODE_UI else box.ASCII
console    = Console()


def ui(unicode_text: str, ascii_text: str | None = None) -> str:
    return unicode_text if UNICODE_UI else (ascii_text or unicode_text)


# ─── Utilitários de linguagem ──────────────────────────────────────────────────

def normalize_lang_choice(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in ("", "auto", "detect", "detectar"):
        return None
    return normalized


def extract_contextual_segment(text: str) -> str | None:
    if CONTEXT_CURRENT_MARKER not in text or CONTEXT_END_MARKER not in text:
        return None
    try:
        after_start = text.split(CONTEXT_CURRENT_MARKER, 1)[1]
        current = after_start.split(CONTEXT_END_MARKER, 1)[0].strip()
        return current or None
    except Exception:
        return None
