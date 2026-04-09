"""Testes de integração — verificam o fluxo completo sem hardware real.

Estes testes validam cenários end-to-end usando mocks para ASR e tradução,
garantindo que o pipeline, circuit breaker, cache e text processing
funcionam juntos corretamente.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from rtxlator.cache import TranslationCache
from rtxlator.circuit_breaker import CircuitBreaker, RateLimiter
from rtxlator.latency_profile import LatencyProfile
from rtxlator.result import Result
from rtxlator.text_processing import TextEnvelope, TextProcessor, TextResolution


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_sine_audio(freq: float = 440, duration_s: float = 0.5, sr: int = 16_000) -> np.ndarray:
    """Gera áudio senoidal para testes."""
    t = np.linspace(0, duration_s, int(sr * duration_s), dtype=np.float32)
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def make_silence(duration_s: float = 0.5, sr: int = 16_000) -> np.ndarray:
    """Gera silêncio para testes."""
    return np.zeros(int(sr * duration_s), dtype=np.float32)


def make_speech_like_audio(duration_s: float = 1.0, sr: int = 16_000) -> np.ndarray:
    """Gera áudio que parece fala (RMS acima do threshold)."""
    t = np.linspace(0, duration_s, int(sr * duration_s), dtype=np.float32)
    # Mix de frequências para simular fala
    audio = (
        0.3 * np.sin(2 * np.pi * 200 * t) +
        0.2 * np.sin(2 * np.pi * 500 * t) +
        0.15 * np.sin(2 * np.pi * 1200 * t) +
        0.1 * np.random.randn(len(t)).astype(np.float32)
    )
    # Normalizar para RMS ~0.1 (bem acima de SILENCE_RMS_TH=0.006)
    rms = float(np.sqrt(np.mean(audio**2)))
    if rms > 0:
        audio = audio * (0.1 / rms)
    return audio.astype(np.float32)


class MockTranslator:
    """Mock do GPUTranslator para testes de integração."""

    def __init__(self, translation: str = "translated text", provider: str = "mock"):
        self.translation = translation
        self.provider = provider
        self.target_lang = "en"
        self.interpretation_mode = "fast"
        self.call_count = 0

    def normalize_lookup_text(self, text: str, source_lang: str | None) -> str:
        return text.strip()

    def translate(
        self,
        text: str,
        src_lang: str = "auto",
        *,
        prefer_context: bool = False,
        context_segments: list[str] | None = None,
        allow_remote_fallback: bool = True,
    ) -> tuple[str, str]:
        self.call_count += 1
        return self.translation, self.provider


class MockWhisperModel:
    """Mock do WhisperModel para testes sem GPU."""

    def __init__(self, text: str = "hello world", language: str = "en"):
        self.text = text
        self.language = language
        self.call_count = 0

    def transcribe(self, audio, **kwargs):
        self.call_count += 1
        segments = [MagicMock(text=self.text)]
        info = MagicMock(language=self.language)
        return iter(segments), info


# ── Testes de Integração ───────────────────────────────────────────────────────

class TestTextProcessorIntegration:
    """Testa o fluxo TextProcessor + TranslationCache + Translator."""

    def test_full_resolve_flow(self):
        """Texto → TextProcessor → resolve → TextResolution."""
        translator = MockTranslator(translation="texto traduzido", provider="mock")
        cache = TranslationCache(max_size=10)
        processor = TextProcessor(translator, cache)

        envelope = TextEnvelope(
            source="MIC",
            raw_text="hello world",
            source_lang="en",
            target_lang="pt",
        )
        result = processor.resolve(envelope)

        assert result.original == "hello world"
        assert result.translated == "texto traduzido"
        assert result.provider == "mock"
        assert result.cache_hit is False
        assert result.translate_ms >= 0

    def test_cache_hit_on_second_resolve(self):
        """Segunda chamada com mesmo texto deve vir do cache."""
        translator = MockTranslator(translation="cached", provider="mock")
        cache = TranslationCache(max_size=10)
        processor = TextProcessor(translator, cache)

        envelope = TextEnvelope(
            source="MIC",
            raw_text="same text",
            source_lang="en",
            target_lang="pt",
        )

        first = processor.resolve(envelope)
        assert first.cache_hit is False
        assert translator.call_count == 1

        second = processor.resolve(envelope)
        assert second.cache_hit is True
        assert second.provider == "cache"
        assert translator.call_count == 1  # não chamou de novo

    def test_partial_skips_cache(self):
        """Parciais com prefer_context=True devem pular cache."""
        translator = MockTranslator(translation="contextual", provider="google-ctx")
        cache = TranslationCache(max_size=10)
        processor = TextProcessor(translator, cache)

        envelope = TextEnvelope(
            source="MIC",
            raw_text="some text",
            source_lang="en",
            target_lang="pt",
            prefer_context=True,
            context_segments=("previous sentence",),
        )

        result = processor.resolve(envelope)
        assert result.provider == "google-ctx"
        assert result.cache_hit is False

    def test_empty_text_returns_identity(self):
        """Texto vazio retorna imediatamente sem traduzir."""
        translator = MockTranslator()
        cache = TranslationCache(max_size=10)
        processor = TextProcessor(translator, cache)

        envelope = TextEnvelope(
            source="MIC",
            raw_text="   ",
            source_lang="en",
            target_lang="pt",
        )

        result = processor.resolve(envelope)
        assert result.provider == "identity"
        assert translator.call_count == 0

    def test_upstream_translated_bypasses_translation(self):
        """Estado 'translated_upstream' não chama o tradutor."""
        translator = MockTranslator()
        cache = TranslationCache(max_size=10)
        processor = TextProcessor(translator, cache)

        envelope = TextEnvelope(
            source="RUST",
            raw_text="pre-translated",
            source_lang="en",
            target_lang="pt",
            translation_state="translated_upstream",
        )

        result = processor.resolve(envelope)
        assert result.provider == "upstream"
        assert translator.call_count == 0


class TestCircuitBreakerWithTranslator:
    """Testa o circuit breaker integrado ao fluxo de tradução."""

    def test_breaker_blocks_after_failures(self):
        """Provider deve ser pulado quando circuit breaker está aberto."""
        breaker = CircuitBreaker("test-provider", max_failures=2, cooldown_s=10)

        # Simula 2 falhas
        breaker.record_failure()
        breaker.record_failure()

        assert breaker.allow() is False
        stats = breaker.stats
        assert stats.is_open is True
        assert stats.total_failures == 2

    def test_rate_limiter_with_translator_flow(self):
        """Rate limiter integrado não deve bloquear chamadas dentro do rate."""
        limiter = RateLimiter(max_per_second=100)  # alto rate para não bloquear
        translator = MockTranslator()
        cache = TranslationCache(max_size=10)
        processor = TextProcessor(translator, cache)

        # 10 traduções em sequência devem funcionar
        for i in range(10):
            assert limiter.acquire() is True
            result = processor.resolve(TextEnvelope(
                source="MIC",
                raw_text=f"text {i}",
                source_lang="en",
                target_lang="pt",
            ))
            assert result.translated == "translated text"

    def test_circuit_breaker_recovery(self):
        """Provider deve se recuperar após cooldown."""
        breaker = CircuitBreaker("test", max_failures=2, cooldown_s=0.05)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.allow() is False

        time.sleep(0.06)
        assert breaker.allow() is True

        breaker.record_success()
        assert breaker.stats.is_open is False
        assert breaker.stats.consecutive_failures == 0


class TestPipelineComponents:
    """Testa componentes do pipeline de forma integrada."""

    def test_audio_speech_detection(self):
        """Áudio com fala deve ser detectado, silêncio não."""
        from rtxlator.audio_utils import is_speech, rms

        speech_audio = make_speech_like_audio(duration_s=0.1)
        silence = make_silence(duration_s=0.1)

        assert rms(speech_audio) > 0.006
        assert is_speech(speech_audio) is True
        assert is_speech(silence) is False

    def test_mono_conversion(self):
        """Áudio stereo deve ser convertido para mono."""
        from rtxlator.audio_utils import to_mono

        stereo = np.random.randn(3200).astype(np.float32)  # 100 frames * 2 channels
        mono = to_mono(stereo, 2)
        assert mono.shape[0] == 1600

    def test_source_profile_overrides(self):
        """Perfis de fonte devem sobrescrever parâmetros de tuning."""
        from rtxlator.source_profiles import apply_source_profile
        from rtxlator.latency_profile import LATENCY_PROFILES

        base = LATENCY_PROFILES["ultra"]
        system = apply_source_profile(base, "system")

        assert system.buffer_min_s != base.buffer_min_s
        assert system.silence_chunks != base.silence_chunks

        mic = apply_source_profile(base, "mic")
        assert mic.buffer_min_s == base.buffer_min_s  # mic não tem overrides

    def test_audio_normalization_for_asr(self):
        """prepare_audio_for_asr deve normalizar áudio sem clipar."""
        from rtxlator.source_profiles import prepare_audio_for_asr

        quiet_audio = make_sine_audio(440, 0.1, 16000) * 0.01
        normalized = prepare_audio_for_asr(quiet_audio, "mic")

        # Deve ter ganho aplicado
        assert float(np.max(np.abs(normalized))) > float(np.max(np.abs(quiet_audio)))
        # Não deve ultrapassar [-1, 1]
        assert float(np.max(np.abs(normalized))) <= 1.0

    def test_result_dataclass(self):
        """Result deve armazenar todos os campos corretamente."""
        r = Result(
            source="MIC",
            original="hello",
            translation="olá",
            lang="en",
            latency_ms=42.5,
            is_partial=False,
            transcribe_ms=30.0,
            translate_ms=12.5,
            cache_hit=True,
            provider="opus-mt",
        )

        assert r.source == "MIC"
        assert r.original == "hello"
        assert r.translation == "olá"
        assert r.latency_ms == 42.5
        assert r.provider == "opus-mt"
        assert r.cache_hit is True
        assert r.ts  # deve ter timestamp


class TestConcurrentPipeline:
    """Testa cenários concorrentes que simulam o uso real."""

    def test_concurrent_text_processing(self):
        """Múltiplas threads traduzindo simultaneamente."""
        translator = MockTranslator()
        cache = TranslationCache(max_size=256)
        processor = TextProcessor(translator, cache)
        errors = []
        results_count = 0
        lock = threading.Lock()

        def process_batch(thread_id: int):
            nonlocal results_count
            try:
                for i in range(20):
                    result = processor.resolve(TextEnvelope(
                        source=f"T{thread_id}",
                        raw_text=f"text from thread {thread_id} message {i}",
                        source_lang="en",
                        target_lang="pt",
                    ))
                    assert result.translated == "translated text"
                    with lock:
                        results_count += 1
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=process_batch, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert results_count == 80  # 4 threads * 20 messages

    def test_results_queue_integrity(self):
        """Results deque + lock mantém integridade sob pressão."""
        results = deque(maxlen=50)
        results_lock = threading.Lock()
        errors = []

        def producer(pid: int):
            try:
                for i in range(50):
                    r = Result(
                        source=f"P{pid}",
                        original=f"msg{i}",
                        translation=f"tr{i}",
                        lang="en",
                        latency_ms=float(i),
                    )
                    with results_lock:
                        results.appendleft(r)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=producer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 50  # maxlen enforced
