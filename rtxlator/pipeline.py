"""Pipeline de áudio: captura → VAD → Whisper → tradução → resultado."""
from __future__ import annotations

import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Full, Queue
from typing import TYPE_CHECKING

import numpy as np

from .audio_utils import is_speech, to_16k, to_mono
from .constants import WHISPER_SR, console
from .latency_profile import LatencyProfile
from .result import Result
from .source_profiles import apply_source_profile, prepare_audio_for_asr
from .text_processing import TextEnvelope, TextProcessor

if TYPE_CHECKING:
    from faster_whisper import WhisperModel
    from .translator import GPUTranslator


class AudioPipeline:
    """
    Thread dedicada por fonte de áudio.
    Fluxo: feed(bytes) → queue → VAD → Whisper → TextProcessor → Result
    """

    def __init__(
        self,
        label:         str,
        model:         "WhisperModel",
        results:       deque,
        results_lock:  threading.Lock,
        runtime_state: dict,
        ui_queue:      "Queue[Result] | None",
        text_processor: TextProcessor,
        trans_pool:    ThreadPoolExecutor,
        source_lang:   str | None,
        orig_sr:       int,
        channels:      int,
        tuning:        LatencyProfile,
        source_kind:   str = "mic",
        overlay_callback: "callable | None" = None,
    ):
        tuned_profile = apply_source_profile(tuning, source_kind)

        self.label         = label
        self.model         = model
        self.results       = results
        self.results_lock  = results_lock
        self.runtime_state = runtime_state
        self.ui_queue      = ui_queue
        self.text_processor = text_processor
        self.translator    = text_processor.translator
        self.trans_pool    = trans_pool
        self.source_lang   = source_lang
        self.orig_sr       = orig_sr
        self.channels      = channels
        self.tuning        = tuned_profile
        self.source_kind   = source_kind
        self.overlay_callback = overlay_callback

        queue_size = max(16, int(self.tuning.queue_seconds / self.tuning.chunk_seconds))
        self._queue: Queue[np.ndarray] = Queue(maxsize=queue_size)
        self._running   = False
        self._thread: threading.Thread | None = None

        self._dropped_chunks     = 0
        self._last_latency_ms    = 0.0
        self._last_transcribe_ms = 0.0
        self._last_translate_ms  = 0.0
        self._last_cache_hit     = False
        self._last_provider      = "idle"
        self._last_partial_at    = 0.0
        self._last_partial_text  = ""

        # ── Language lock ───────────────────────────────────────────────────
        # Detecta o idioma na primeira transcrição final e trava para o restante
        # da sessão. Se force_language estiver definido no perfil (ex: system_en),
        # o idioma é travado imediatamente — sem nenhum round de autodetect.
        self._locked_lang: str | None = tuned_profile.force_language

        # ── Telemetria Fase 1 ───────────────────────────────────────────────
        self._total_chunks_fed:    int   = 0
        self._total_translated:    int   = 0
        self._fallback_count:      int   = 0
        self._last_first_partial_ms: float = 0.0   # speech_start → primeiro parcial
        self._last_queue_wait_ms:  float = 0.0     # enfileirado → início de execução
        self._speech_start_at:     float = 0.0     # quando detectamos início de fala
        self._first_partial_sent:  bool  = False

        self._dispatch_lock    = threading.Lock()
        self._asr_pool         = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"asr-{label.lower()}")
        self._asr_busy         = False
        self._pending_partial: tuple[np.ndarray, float, int] | None = None
        self._pending_final:   tuple[np.ndarray, float, int] | None = None
        self._latest_seq         = 0
        self._latest_partial_seq = 0

        self._context_window: deque[str] = deque(maxlen=3)
        self._recent_translate_ms: deque[float] = deque(maxlen=8)
        self._context_cooldown_until = 0.0

    # ── Interface de alimentação ────────────────────────────────────────────

    def feed(self, raw: bytes) -> None:
        arr = np.frombuffer(raw, dtype=np.float32).copy()
        self._total_chunks_fed += 1
        try:
            self._queue.put_nowait(arr)
        except Full:
            self._dropped_chunks += 1

    # ── Controle de ciclo de vida ───────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        self._thread  = threading.Thread(target=self._run, daemon=True, name=f"pipe-{self.label}")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._asr_pool.shutdown(wait=True)

    # ── Propriedades de observabilidade ────────────────────────────────────

    @property
    def dropped_chunks(self) -> int:
        return self._dropped_chunks

    @property
    def last_latency_ms(self) -> float:
        return self._last_latency_ms

    @property
    def last_transcribe_ms(self) -> float:
        return self._last_transcribe_ms

    @property
    def last_translate_ms(self) -> float:
        return self._last_translate_ms

    @property
    def last_cache_hit(self) -> bool:
        return self._last_cache_hit

    @property
    def last_provider(self) -> str:
        return self._last_provider

    @property
    def locked_lang(self) -> str | None:
        return self._locked_lang

    @property
    def drop_rate(self) -> float:
        """Fração de chunks descartados por fila cheia (0.0–1.0)."""
        if self._total_chunks_fed == 0:
            return 0.0
        return self._dropped_chunks / self._total_chunks_fed

    @property
    def fallback_rate(self) -> float:
        """Fração de traduções que usaram fallback (não hot-path local)."""
        if self._total_translated == 0:
            return 0.0
        return self._fallback_count / self._total_translated

    @property
    def last_first_partial_ms(self) -> float:
        """Tempo entre início da fala detectada e primeiro resultado parcial."""
        return self._last_first_partial_ms

    @property
    def last_queue_wait_ms(self) -> float:
        """Tempo que o áudio ficou na fila antes de começar o ASR."""
        return self._last_queue_wait_ms

    # ── Loop principal ─────────────────────────────────────────────────────

    def _run(self) -> None:
        buffer: list[np.ndarray] = []
        buffer_samples = 0
        silence_streak = 0
        in_speech      = False

        while self._running:
            try:
                raw_chunk = self._queue.get(timeout=0.1)
            except Empty:
                if buffer:
                    buf_s = buffer_samples / WHISPER_SR
                    if buf_s >= self.tuning.buffer_flush_s:
                        self._flush(buffer, is_partial=False)
                        buffer.clear()
                        buffer_samples = 0
                        silence_streak = 0
                        in_speech      = False
                continue

            chunk = to_mono(raw_chunk, self.channels)
            chunk = to_16k(chunk, self.orig_sr)
            speech_now = is_speech(chunk)

            if speech_now:
                if not in_speech:
                    self._last_partial_at    = 0.0
                    self._last_partial_text  = ""
                    self._speech_start_at    = time.perf_counter()
                    self._first_partial_sent = False
                silence_streak = 0
                in_speech      = True
                buffer.append(chunk)
                buffer_samples += len(chunk)
            else:
                silence_streak += 1
                if in_speech:
                    buffer.append(chunk)
                    buffer_samples += len(chunk)

            buf_s = buffer_samples / WHISPER_SR
            now   = time.perf_counter()

            should_finalize = (
                (in_speech and silence_streak >= self.tuning.silence_chunks and buf_s >= self.tuning.buffer_min_s)
                or buf_s >= self.tuning.buffer_flush_s
            )
            partial_interval = max(0.25, self.tuning.partial_flush_s * 0.75)
            should_partial = (
                in_speech
                and silence_streak == 0
                and buf_s >= self.tuning.partial_flush_s
                and now - self._last_partial_at >= partial_interval
            )

            if should_finalize and buf_s >= self.tuning.buffer_min_s:
                self._flush(buffer, is_partial=False)
                buffer.clear()
                buffer_samples = 0
                silence_streak = 0
                in_speech      = False
                self._last_partial_at   = 0.0
                self._last_partial_text = ""
            elif should_partial and buf_s >= self.tuning.buffer_min_s:
                self._flush(list(buffer), is_partial=True)
                self._last_partial_at = now

    # ── Dispatch de ASR ────────────────────────────────────────────────────

    def _next_dispatch_seq(self) -> int:
        with self._dispatch_lock:
            self._latest_seq += 1
            return self._latest_seq

    def _flush(self, buffer: list[np.ndarray], *, is_partial: bool) -> None:
        audio        = np.concatenate(buffer)
        t0           = time.perf_counter()
        dispatch_seq = self._next_dispatch_seq()
        self._schedule_flush(audio, is_partial=is_partial, t0=t0, dispatch_seq=dispatch_seq)

    def _schedule_flush(self, audio: np.ndarray, *, is_partial: bool, t0: float, dispatch_seq: int) -> None:
        with self._dispatch_lock:
            if is_partial:
                self._latest_partial_seq = dispatch_seq
            if self._asr_busy:
                if is_partial:
                    self._pending_partial = (audio, t0, dispatch_seq)
                else:
                    self._pending_final   = (audio, t0, dispatch_seq)
                    self._pending_partial = None
                return
            self._asr_busy = True
        self._asr_pool.submit(self._flush_job, audio, is_partial, t0, dispatch_seq)

    def _flush_job(self, audio: np.ndarray, is_partial: bool, t0: float, dispatch_seq: int) -> None:
        self._last_queue_wait_ms = (time.perf_counter() - t0) * 1000

        audio = prepare_audio_for_asr(audio, self.source_kind)
        initial_prompt = None
        condition_on_previous_text = False
        if not is_partial and self._context_window:
            initial_prompt = " ".join(self._context_window)[-220:]
            condition_on_previous_text = True

        # Language lock: usa idioma travado se disponível, senão auto-detect.
        # Após a primeira transcrição final bem-sucedida, trava e elimina o
        # custo de detecção spectral em todos os segmentos seguintes.
        effective_lang = self._locked_lang or self.source_lang

        try:
            segments_gen, info = self.model.transcribe(
                audio,
                beam_size=1,
                best_of=1,
                language=effective_lang,
                condition_on_previous_text=condition_on_previous_text,
                initial_prompt=initial_prompt,
                without_timestamps=self.tuning.without_timestamps,
                vad_filter=self.tuning.whisper_vad,
                vad_parameters=dict(
                    threshold=0.4,
                    min_speech_duration_ms=self.tuning.min_speech_duration_ms,
                    max_speech_duration_s=float("inf"),
                    min_silence_duration_ms=self.tuning.min_silence_duration_ms,
                    speech_pad_ms=self.tuning.speech_pad_ms,
                ),
                temperature=0,
            )
            text = " ".join(s.text for s in segments_gen).strip()
        except Exception as e:
            console.print(f"[red]Erro transcricao ({self.label}): {e}[/red]")
            self._schedule_next_pending()
            return

        if not text:
            self._schedule_next_pending()
            return

        if is_partial and text == self._last_partial_text:
            self._schedule_next_pending()
            return
        if is_partial:
            self._last_partial_text = text

        detected_lang = info.language

        # Trava o idioma após a primeira transcrição final confiante.
        # Parciais nunca travam — podem ser incompletas e imprecisas.
        if not is_partial and self._locked_lang is None and detected_lang:
            self._locked_lang = detected_lang
            console.print(f"[dim]{self.label}: idioma travado -> {detected_lang}[/dim]")

        transcribe_ms = (time.perf_counter() - t0) * 1000

        self.trans_pool.submit(
            self._translate_and_save, text, detected_lang, t0, transcribe_ms, is_partial, dispatch_seq
        )
        self._schedule_next_pending()

    def _schedule_next_pending(self) -> None:
        with self._dispatch_lock:
            pending = None
            if self._pending_final is not None:
                audio, t0, dispatch_seq = self._pending_final
                self._pending_final = None
                pending = (audio, t0, dispatch_seq, False)
            elif self._pending_partial is not None:
                audio, t0, dispatch_seq = self._pending_partial
                self._pending_partial = None
                pending = (audio, t0, dispatch_seq, True)
            else:
                self._asr_busy = False
                return
        audio, t0, dispatch_seq, is_partial = pending
        self._asr_pool.submit(self._flush_job, audio, is_partial, t0, dispatch_seq)

    # ── Tradução e persistência ─────────────────────────────────────────────

    def _should_use_context(self, text: str, is_partial: bool) -> bool:
        if is_partial:
            return False
        if time.perf_counter() < self._context_cooldown_until:
            return False
        if len(self._context_window) < 1:
            return False
        return True

    def _context_latency_budget_ms(self) -> float:
        if not self._recent_translate_ms:
            return 400.0
        average_translate_ms = sum(self._recent_translate_ms) / len(self._recent_translate_ms)
        budget_ms = max(200.0, average_translate_ms * 1.5)
        return budget_ms

    def _translate_and_save(
        self,
        text:         str,
        lang:         str,
        t0:           float,
        transcribe_ms: float,
        is_partial:   bool,
        dispatch_seq: int,
    ) -> None:
        if is_partial:
            with self._dispatch_lock:
                is_stale = dispatch_seq != self._latest_partial_seq
            if is_stale:
                return

        use_context = self._should_use_context(text, is_partial)
        resolution  = self.text_processor.resolve(
            TextEnvelope(
                source=self.label,
                raw_text=text,
                source_lang=lang,
                target_lang=self.translator.target_lang,
                direction="audio",
                translation_state="raw",
                is_partial=is_partial,
                prefer_context=use_context,
                context_segments=tuple(self._context_window),
                conversation_id=self.label,
            )
        )

        translate_ms = resolution.translate_ms
        self._recent_translate_ms.append(translate_ms)
        if use_context and translate_ms > self._context_latency_budget_ms():
            self._context_cooldown_until = time.perf_counter() + 8.0

        total_ms = (time.perf_counter() - t0) * 1000
        self._last_latency_ms    = total_ms
        self._last_transcribe_ms = transcribe_ms
        self._last_translate_ms  = translate_ms
        self._last_cache_hit     = resolution.cache_hit
        self._last_provider      = resolution.provider

        # Telemetria: contagem e fallback rate
        self._total_translated += 1
        if resolution.provider not in ("cache", "opus-mt", "argos", "memory", "identity", "upstream"):
            self._fallback_count += 1

        # first_partial_ms: tempo entre início da fala e primeiro parcial entregue
        if is_partial and not self._first_partial_sent and self._speech_start_at > 0:
            self._last_first_partial_ms = (time.perf_counter() - self._speech_start_at) * 1000
            self._first_partial_sent = True

        if is_partial:
            with self._dispatch_lock:
                is_stale = dispatch_seq != self._latest_partial_seq
            if is_stale:
                return

        r = Result(
            source=self.label,
            original=resolution.original,
            translation=resolution.translated,
            lang=lang,
            latency_ms=total_ms,
            is_partial=is_partial,
            transcribe_ms=transcribe_ms,
            translate_ms=translate_ms,
            cache_hit=resolution.cache_hit,
            provider=resolution.provider,
        )

        with self.results_lock:
            partials = self.runtime_state.setdefault("partials", {})
            if is_partial:
                partials[self.label] = r
            else:
                partials.pop(self.label, None)
                self.results.appendleft(r)
                self._last_partial_text = ""
                self._context_window.append(text)
            self.runtime_state["results_version"] = (
                self.runtime_state.get("results_version", 0) + 1
            )

        if self.ui_queue is not None:
            try:
                self.ui_queue.put_nowait(r)
            except Full:
                pass

        if self.overlay_callback is not None:
            try:
                self.overlay_callback(r)
            except Exception:
                pass
