import unittest

from rtxlator.text_processing import TextEnvelope, TextProcessor


class FakeCache:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def put(self, key, value):
        self.data[key] = value


class FakeTranslator:
    def __init__(self):
        self.interpretation_mode = "hybrid"
        self.target_lang = "en"
        self.calls = []

    def normalize_lookup_text(self, text, source_lang):
        return text.strip().lower()

    def translate(self, text, src_lang="auto", *, prefer_context=False, context_segments=None, allow_remote_fallback=True):
        self.calls.append((text, prefer_context, allow_remote_fallback))
        if prefer_context:
            return f"ctx:{text}", "google-ctx"
        return f"mt:{text}", "argos"


class TextProcessorTests(unittest.TestCase):
    def test_cache_is_direction_aware(self):
        processor = TextProcessor(FakeTranslator(), FakeCache())
        first = processor.resolve(TextEnvelope(source="A", raw_text="Olá", source_lang="pt", target_lang="en", direction="outbound"))
        second = processor.resolve(TextEnvelope(source="B", raw_text="Olá", source_lang="pt", target_lang="en", direction="inbound"))
        self.assertEqual(first.provider, "argos")
        self.assertEqual(second.provider, "argos")

    def test_context_mode_bypasses_cache(self):
        translator = FakeTranslator()
        processor = TextProcessor(translator, FakeCache())
        result = processor.resolve(
            TextEnvelope(
                source="A",
                raw_text="Fechar pedido",
                source_lang="pt",
                target_lang="en",
                prefer_context=True,
                context_segments=("mesa cinco",),
            )
        )
        self.assertEqual(result.provider, "google-ctx")
        self.assertEqual(result.translated, "ctx:fechar pedido")
        self.assertEqual(translator.calls[-1][-1], True)

    def test_partial_disables_remote_fallback(self):
        translator = FakeTranslator()
        processor = TextProcessor(translator, FakeCache())
        processor.resolve(
            TextEnvelope(
                source="A",
                raw_text="Mesa cinco",
                source_lang="pt",
                target_lang="en",
                is_partial=True,
            )
        )
        self.assertEqual(translator.calls[-1][-1], False)


if __name__ == "__main__":
    unittest.main()
