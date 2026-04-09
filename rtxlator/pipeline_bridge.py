"""Bridge entre o runtime Rust e o AudioPipeline Python.

Quando o runtime Rust está compilado (runtime_rs.pyd), este módulo fornece
um adaptador que consome AudioSegments do Rust e os alimenta diretamente
ao pipeline de ASR, bypassing o pyaudiowpatch e o DSP Python.

Sem Rust compilado: fallback transparente para o pipeline Python existente.

Uso:
    from rtxlator.pipeline_bridge import create_pipeline_source

    source = create_pipeline_source(pipeline, source_kind="mic")
    source.start()  # Inicia captura via Rust ou Python callback
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import numpy as np

from .audio_rs import RUST_RUNTIME, AudioSegment, rust_runtime_status
from .constants import WHISPER_SR, console

if TYPE_CHECKING:
    from .pipeline import AudioPipeline


class RustPipelineSource:
    """Alimenta um AudioPipeline a partir de AudioSegments do runtime Rust.

    Substitui o callback do pyaudiowpatch quando o Rust está disponível.
    O DSP (mono, resample, gain) já foi feito no Rust — os samples chegam
    em 16kHz mono f32, prontos para o VAD e Whisper.
    """

    def __init__(
        self,
        pipeline: "AudioPipeline",
        segment_queue: "object",  # SegmentQueue do Rust ou mock
        source_kind: str = "mic",
    ):
        self.pipeline = pipeline
        self.segment_queue = segment_queue
        self.source_kind = source_kind
        self._running = False
        self._thread: threading.Thread | None = None
        self._segments_consumed = 0

    def start(self) -> None:
        """Inicia a thread de consumo de segmentos."""
        self._running = True
        self._thread = threading.Thread(
            target=self._consume_loop,
            daemon=True,
            name=f"rust-bridge-{self.source_kind}",
        )
        self._thread.start()
        console.print(f"[green]RustPipelineSource ({self.source_kind}): consumindo segmentos do runtime Rust[/green]")

    def stop(self) -> None:
        """Para a thread de consumo."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)

    @property
    def segments_consumed(self) -> int:
        return self._segments_consumed

    def _consume_loop(self) -> None:
        """Loop principal: consome segmentos do Rust e alimenta o pipeline."""
        while self._running:
            try:
                # SegmentQueue.drain() retorna segmentos prontos
                segment = self._try_drain_segment()
                if segment is None:
                    time.sleep(0.01)  # Evita busy-wait
                    continue

                # Converte AudioSegment para bytes compatíveis com pipeline.feed()
                samples = np.array(segment.samples, dtype=np.float32)
                self.pipeline.feed(samples.tobytes())
                self._segments_consumed += 1

            except Exception as e:
                console.print(f"[red]RustPipelineSource erro: {e}[/red]")
                time.sleep(0.1)

    def _try_drain_segment(self) -> "AudioSegment | None":
        """Tenta obter um segmento da fila Rust."""
        if hasattr(self.segment_queue, "drain_one"):
            return self.segment_queue.drain_one()
        elif hasattr(self.segment_queue, "try_recv"):
            return self.segment_queue.try_recv()
        elif hasattr(self.segment_queue, "get_nowait"):
            try:
                return self.segment_queue.get_nowait()
            except Exception:
                return None
        return None


class PythonPipelineSource:
    """Wrapper para o pipeline Python existente via pyaudiowpatch callback.

    Mantém a mesma interface que RustPipelineSource para que o código
    de bootstrap não precise saber qual backend está ativo.
    """

    def __init__(
        self,
        pipeline: "AudioPipeline",
        stream: "object",  # pyaudiowpatch stream
        source_kind: str = "mic",
    ):
        self.pipeline = pipeline
        self.stream = stream
        self.source_kind = source_kind
        self._running = False

    def start(self) -> None:
        """Inicia o stream (o callback já está configurado pelo setup_mic/setup_loopback)."""
        self._running = True
        console.print(f"[dim]PythonPipelineSource ({self.source_kind}): usando pyaudiowpatch[/dim]")

    def stop(self) -> None:
        """Para o stream."""
        self._running = False
        try:
            if hasattr(self.stream, "stop_stream"):
                self.stream.stop_stream()
            if hasattr(self.stream, "close"):
                self.stream.close()
        except Exception:
            pass


def create_pipeline_source(
    pipeline: "AudioPipeline",
    source_kind: str = "mic",
    *,
    rust_queue: "object | None" = None,
    python_stream: "object | None" = None,
) -> "RustPipelineSource | PythonPipelineSource":
    """Factory: cria a melhor fonte disponível para o pipeline.

    Prioridade:
    1. Rust runtime (se compilado E rust_queue fornecido)
    2. Python/pyaudiowpatch (fallback)

    Retorna um objeto com interface .start() / .stop().
    """
    if RUST_RUNTIME and rust_queue is not None:
        console.print(f"[green]Pipeline source ({source_kind}): [bold]Rust runtime[/bold] selecionado[/green]")
        return RustPipelineSource(pipeline, rust_queue, source_kind)

    if python_stream is not None:
        return PythonPipelineSource(pipeline, python_stream, source_kind)

    # Nenhum backend disponível
    console.print(f"[yellow]Pipeline source ({source_kind}): sem backend configurado[/yellow]")
    return PythonPipelineSource(pipeline, type("NullStream", (), {})(), source_kind)


def runtime_status_summary() -> str:
    """Retorna um resumo do status do runtime para exibição no startup."""
    if RUST_RUNTIME:
        return (
            "[bold green]✓ Rust runtime disponível[/bold green] — "
            "captura e DSP nativos com jitter reduzido"
        )
    return (
        "[dim]⚠ Rust runtime não compilado[/dim] — "
        "usando pyaudiowpatch (funcional, maior jitter). "
        "Execute [bold]compilar_rust.bat[/bold] para ativar."
    )

