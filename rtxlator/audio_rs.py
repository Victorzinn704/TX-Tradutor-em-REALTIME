"""
Shim de compatibilidade entre o runtime Rust (runtime_rs) e o pipeline Python.

Tenta importar o módulo PyO3 compilado. Se não estiver disponível
(Rust não compilado ou plataforma sem suporte), cai silenciosamente
para o pipeline Python existente — sem quebrar nada.

Uso:
    from rtxlator.audio_rs import RUST_RUNTIME, AudioSegment

    if RUST_RUNTIME:
        # usa AudioSegment nativo do Rust
    else:
        # usa pipeline Python atual (AudioPipeline)
"""
from __future__ import annotations

from dataclasses import dataclass

# ── Tentativa de importar o módulo PyO3 compilado ─────────────────────────────

try:
    # runtime_rs.pyd lives inside the rtxlator package directory
    from .runtime_rs import AudioSegment as _RustAudioSegment  # type: ignore[import]
    AudioSegment = _RustAudioSegment
    RUST_RUNTIME = True
except ImportError:
    RUST_RUNTIME = False

    # Fallback Python — mesma interface que o AudioSegment Rust expõe,
    # construído a partir dos dados já disponíveis no pipeline Python.
    @dataclass
    class AudioSegment:  # type: ignore[no-redef]
        """
        Representa um segmento de áudio pronto para ASR.

        Substituto Python do AudioSegment Rust quando runtime_rs
        não está compilado. Mesmos campos, mesma semântica.
        """
        source_id:      str
        samples:        list[float]
        captured_at_ms: int
        rms:            float
        sample_rate:    int = 16_000

        def duration_ms(self) -> float:
            if self.sample_rate == 0:
                return 0.0
            return (len(self.samples) / self.sample_rate) * 1000.0

        def __repr__(self) -> str:
            return (
                f"AudioSegment(source='{self.source_id}', "
                f"frames={len(self.samples)}, rms={self.rms:.4f}, "
                f"at={self.captured_at_ms}ms) [python-fallback]"
            )


def rust_runtime_status() -> str:
    """Retorna string descritiva do status do runtime Rust — para exibição no startup."""
    if RUST_RUNTIME:
        return "[green]runtime_rs[/green] (PyO3 nativo)"
    return "[yellow]python-fallback[/yellow] (compile runtime-rs/ para ativar Rust)"
