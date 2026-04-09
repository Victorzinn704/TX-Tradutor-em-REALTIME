import json
import tempfile
import unittest
from pathlib import Path

from realtime_translator import (
    DEFAULT_PROFILE,
    AudioPipeline,
    LATENCY_PROFILES,
    PersonalLanguageContext,
    Result,
    build_runtime_status,
    extract_contextual_segment,
    make_translation_cache_key,
    normalize_lang_choice,
    render_result_line,
    resolve_latency_profile,
)


class TranslatorConfigTests(unittest.TestCase):
    def test_resolve_latency_profile_uses_defaults(self):
        profile = resolve_latency_profile(DEFAULT_PROFILE)
        self.assertEqual(profile.name, DEFAULT_PROFILE)
        self.assertEqual(profile.chunk_seconds, LATENCY_PROFILES[DEFAULT_PROFILE].chunk_seconds)

    def test_resolve_latency_profile_applies_overrides(self):
        profile = resolve_latency_profile(
            "balanced",
            chunk_seconds=0.11,
            buffer_min_s=0.22,
            buffer_flush_s=1.4,
            silence_chunks=5,
        )
        self.assertEqual(profile.chunk_seconds, 0.11)
        self.assertEqual(profile.buffer_min_s, 0.22)
        self.assertEqual(profile.buffer_flush_s, 1.4)
        self.assertEqual(profile.silence_chunks, 5)
        self.assertEqual(profile.name, "balanced")

    def test_translation_cache_key_is_language_aware(self):
        self.assertNotEqual(
            make_translation_cache_key("hello", "en"),
            make_translation_cache_key("hello", "es"),
        )

    def test_normalize_lang_choice_accepts_detect_aliases(self):
        self.assertIsNone(normalize_lang_choice("detect"))
        self.assertIsNone(normalize_lang_choice("detectar"))
        self.assertIsNone(normalize_lang_choice("auto"))
        self.assertEqual(normalize_lang_choice("PT"), "pt")

    def test_extract_contextual_segment(self):
        translated = "Yesterday I went to the market. [[C1]] And today I'll be back. [[E1]]"
        self.assertEqual(extract_contextual_segment(translated), "And today I'll be back.")

    def test_personal_context_applies_memory_and_glossary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ctx.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "source_normalization": {"pt": {"pra": "para"}},
                        "correction_memory": {"pt->en": {"pode fechar a conta": "Can you close the check?"}},
                        "preferred_translations": {},
                        "glossary": {"pt->en": {"caixa": "cash register"}},
                        "target_replacements": {"pt->en": {"close the account": "close the check"}},
                        "context_rules": [],
                    }
                ),
                encoding="utf-8",
            )
            context = PersonalLanguageContext(path)
            self.assertEqual(context.normalize_source_text("pra caixa", "pt"), "para caixa")
            self.assertEqual(
                context.lookup_memory("Pode fechar a conta?", "pt", "en"),
                "Can you close the check?",
            )
            protected, replacements = context.protect_terms("abrir o caixa", "pt", "en")
            self.assertIn("[[T0]]", protected)
            restored = context.apply_target_preferences("open the [[T0]]", "pt", "en", replacements)
            self.assertEqual(restored, "open the cash register")

    def test_build_runtime_status_shows_drop_counts(self):
        pipe = AudioPipeline.__new__(AudioPipeline)
        pipe.label = "MIC"
        pipe._dropped_chunks = 3
        pipe._last_latency_ms = 210
        pipe._last_transcribe_ms = 160
        pipe._last_translate_ms = 12
        pipe._last_cache_hit = True
        pipe._last_provider = "cache"
        # Novos atributos de telemetria Fase 1
        pipe._locked_lang = None
        pipe._total_chunks_fed = 30          # drop_rate = 3/30 = 10%
        pipe._total_translated = 0
        pipe._fallback_count = 0
        pipe._last_first_partial_ms = 0.0
        pipe._last_queue_wait_ms = 0.0
        pipe._context_cooldown_until = 0.0
        status = build_runtime_status("cuda", "small", LATENCY_PROFILES["ultra"], ["MIC USB"], [pipe], "hybrid")
        self.assertIn("profile=ultra", status)
        self.assertIn("mode=hybrid", status)
        self.assertIn("drop=10.0%", status)
        self.assertIn("MIC:asr=160ms tr=12ms cache", status)

    def test_render_result_line_marks_partial(self):
        result = Result(
            source="MIC",
            original="ola mundo",
            translation="hello world",
            lang="pt",
            latency_ms=123,
            is_partial=True,
            provider="google",
        )
        meta, body = render_result_line(result)
        self.assertIn("[parcial]", meta)
        self.assertIn("asr 0 / tr 0", meta)
        self.assertIn("google", meta)
        self.assertIn("ola mundo", body)
        self.assertIn("hello world", body)


if __name__ == "__main__":
    unittest.main()
