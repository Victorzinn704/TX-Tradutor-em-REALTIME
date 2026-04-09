from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rtxlator.opus_translator import OpusMTTranslator


class FakeSentencePieceProcessor:
    def __init__(self, model_file: str) -> None:
        self.model_file = model_file

    def encode(self, text: str, out_type=str) -> list[str]:
        return [part for part in text.strip().split() if part]

    def decode_pieces(self, tokens: list[str]) -> str:
        return " ".join(tokens)


class FakeCTranslateTranslator:
    def __init__(self, model_path: str, device: str, compute_type: str) -> None:
        self.model_path = model_path
        self.device = device
        self.compute_type = compute_type
        self.calls: list[list[str]] = []

    def translate_batch(self, batches: list[list[str]], beam_size: int, return_scores: bool):
        assert beam_size == 1
        assert return_scores is False
        self.calls.append(batches[0])
        time.sleep(0.01)
        return [SimpleNamespace(hypotheses=[["ola", "mundo"]])]


@pytest.fixture
def fake_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    ctranslate2_module = ModuleType("ctranslate2")
    ctranslate2_module.Translator = FakeCTranslateTranslator
    sentencepiece_module = ModuleType("sentencepiece")
    sentencepiece_module.SentencePieceProcessor = FakeSentencePieceProcessor
    monkeypatch.setitem(sys.modules, "ctranslate2", ctranslate2_module)
    monkeypatch.setitem(sys.modules, "sentencepiece", sentencepiece_module)


@pytest.fixture
def fake_model_tree(tmp_path: Path) -> Path:
    pair_dir = tmp_path / "models" / "opus" / "en-pt"
    pair_dir.mkdir(parents=True)
    (pair_dir / "model.bin").write_bytes(b"fake-model")
    (pair_dir / "source.spm").write_text("fake-spm", encoding="utf-8")
    (pair_dir / "target.spm").write_text("fake-spm", encoding="utf-8")
    return tmp_path / "models"


def test_translate_returns_identity_when_pair_missing(tmp_path: Path, fake_runtime: None) -> None:
    translator = OpusMTTranslator(target_lang="pt", device="cpu", compute_type="int8", models_dir=tmp_path / "models")
    assert translator.translate("Hello world", src_lang="en") == ("Hello world", "identity")


def test_translate_returns_identity_when_source_matches_target(fake_model_tree: Path, fake_runtime: None) -> None:
    translator = OpusMTTranslator(target_lang="pt", device="cpu", compute_type="int8", models_dir=fake_model_tree)
    assert translator.translate("Olá mundo", src_lang="pt") == ("Olá mundo", "identity")


def test_translate_returns_identity_for_empty_text(fake_model_tree: Path, fake_runtime: None) -> None:
    translator = OpusMTTranslator(target_lang="pt", device="cpu", compute_type="int8", models_dir=fake_model_tree)
    assert translator.translate("   ", src_lang="en") == ("   ", "identity")


def test_translate_disables_any_remote_path(fake_model_tree: Path, fake_runtime: None) -> None:
    translator = OpusMTTranslator(target_lang="pt", device="cpu", compute_type="int8", models_dir=fake_model_tree)
    translated, provider = translator.translate(
        "Hello world",
        src_lang="en",
        prefer_context=True,
        context_segments=["earlier context"],
        allow_remote_fallback=False,
    )
    assert translated == "ola mundo"
    assert provider == "opus-mt"


def test_translate_is_thread_safe(fake_model_tree: Path, fake_runtime: None) -> None:
    translator = OpusMTTranslator(target_lang="pt", device="cpu", compute_type="int8", models_dir=fake_model_tree)
    results: list[tuple[str, str]] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            results.append(translator.translate("Hello world", src_lang="en"))
        except BaseException as exc:  # pragma: no cover - explicit deadlock safety
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2.0)

    assert not errors
    assert len(results) == 10
    assert all(result == ("ola mundo", "opus-mt") for result in results)


def test_preload_returns_thread(fake_model_tree: Path, fake_runtime: None) -> None:
    translator = OpusMTTranslator(target_lang="pt", device="cpu", compute_type="int8", models_dir=fake_model_tree)
    thread = translator.preload(["en"])
    assert isinstance(thread, threading.Thread)
    thread.join(timeout=2.0)


def test_normalize_lookup_text_strips_whitespace(fake_model_tree: Path, fake_runtime: None) -> None:
    translator = OpusMTTranslator(target_lang="pt", device="cpu", compute_type="int8", models_dir=fake_model_tree)
    assert translator.normalize_lookup_text("  hello  ", "en") == "hello"
