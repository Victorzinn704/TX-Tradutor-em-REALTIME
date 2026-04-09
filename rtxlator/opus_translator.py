from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from .constants import MODELS_DIR, console


@dataclass(frozen=True)
class _LoadedOpusPair:
    translator: Any
    source_tokenizer: Any
    target_tokenizer: Any
    source_prefix: str | None = None


class OpusMTTranslator:
    """
    Tradutor local baseado em modelos OPUS-MT convertidos para CTranslate2.

    Estrutura esperada em disco:

    models/
      opus/
        en-pt/
          model.bin
          source.spm
          target.spm
          [source_prefix.txt]
    """

    def __init__(
        self,
        target_lang: str,
        device: str,
        compute_type: str,
        models_dir: Path = MODELS_DIR,
        interpretation_mode: str = "hybrid",
    ) -> None:
        self.target_lang = target_lang
        self.device = device
        self.compute_type = compute_type
        self.models_dir = Path(models_dir)
        self.interpretation_mode = interpretation_mode

        self._pair_cache: dict[str, _LoadedOpusPair | None] = {}
        self._load_lock = threading.Lock()

    def normalize_lookup_text(self, text: str, source_lang: str | None) -> str:
        _ = source_lang
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
        _ = prefer_context, context_segments, allow_remote_fallback

        clean_text = text.strip()
        if not clean_text:
            return text, "identity"

        normalized_src = (src_lang or "").strip().lower()
        if not normalized_src or normalized_src == "auto":
            return text, "identity"
        if normalized_src == self.target_lang:
            return text, "identity"

        pair = self._ensure_pair_loaded(normalized_src, self.target_lang)
        if pair is None:
            return text, "identity"

        source_text = clean_text
        if pair.source_prefix:
            source_text = f"{pair.source_prefix} {source_text}".strip()

        source_tokens = pair.source_tokenizer.encode(source_text, out_type=str)
        if not source_tokens:
            return text, "identity"

        results = pair.translator.translate_batch(
            [source_tokens],
            beam_size=1,
            return_scores=False,
        )
        if not results:
            return text, "identity"

        hypotheses = getattr(results[0], "hypotheses", None) or []
        if not hypotheses:
            return text, "identity"

        output_tokens = self._clean_output_tokens(list(hypotheses[0]))
        translated = pair.target_tokenizer.decode_pieces(output_tokens).strip()
        return (translated or clean_text), "opus-mt"

    def preload(self, src_langs: list[str]) -> threading.Thread:
        def _run() -> None:
            for src_lang in src_langs:
                normalized_src = (src_lang or "").strip().lower()
                if not normalized_src or normalized_src == self.target_lang:
                    continue
                pair = self._ensure_pair_loaded(normalized_src, self.target_lang)
                if pair is None:
                    console.print(
                        f"[yellow]OPUS-MT indisponivel para {normalized_src}->{self.target_lang}[/yellow]"
                    )
                else:
                    console.print(
                        f"[green][OK] OPUS-MT {normalized_src}->{self.target_lang} pronto[/green]"
                    )

        thread = threading.Thread(
            target=_run,
            daemon=True,
            name=f"opus-preload-{self.target_lang}",
        )
        thread.start()
        return thread

    def _ensure_pair_loaded(self, source_lang: str, target_lang: str) -> _LoadedOpusPair | None:
        pair_key = f"{source_lang}->{target_lang}"
        cached = self._pair_cache.get(pair_key)
        if cached is not None or pair_key in self._pair_cache:
            return cached

        with self._load_lock:
            cached = self._pair_cache.get(pair_key)
            if cached is not None or pair_key in self._pair_cache:
                return cached

            try:
                loaded = self._load_pair(source_lang, target_lang)
            except Exception as exc:
                console.print(
                    f"[yellow]Falha ao carregar OPUS-MT {source_lang}->{target_lang}: {exc}[/yellow]"
                )
                loaded = None
            self._pair_cache[pair_key] = loaded
            return loaded

    def _load_pair(self, source_lang: str, target_lang: str) -> _LoadedOpusPair | None:
        pair_dir = self.models_dir / "opus" / f"{source_lang}-{target_lang}"
        model_file = pair_dir / "model.bin"
        source_spm = pair_dir / "source.spm"
        target_spm = pair_dir / "target.spm"

        if not model_file.exists():
            return None
        if not source_spm.exists() or not target_spm.exists():
            console.print(
                f"[yellow]OPUS-MT {source_lang}->{target_lang} sem tokenizers em {pair_dir}[/yellow]"
            )
            return None

        ctranslate2_module, sentencepiece_module = self._import_runtime_deps()
        translator = ctranslate2_module.Translator(
            str(pair_dir),
            device=self.device,
            compute_type=self.compute_type,
        )
        source_tokenizer = sentencepiece_module.SentencePieceProcessor(model_file=str(source_spm))
        target_tokenizer = sentencepiece_module.SentencePieceProcessor(model_file=str(target_spm))
        source_prefix = self._read_optional_text(pair_dir / "source_prefix.txt")

        return _LoadedOpusPair(
            translator=translator,
            source_tokenizer=source_tokenizer,
            target_tokenizer=target_tokenizer,
            source_prefix=source_prefix,
        )

    def _import_runtime_deps(self) -> tuple[ModuleType, ModuleType]:
        import ctranslate2
        import sentencepiece

        return ctranslate2, sentencepiece

    @staticmethod
    def _read_optional_text(path: Path) -> str | None:
        if not path.exists():
            return None
        value = path.read_text(encoding="utf-8").strip()
        return value or None

    @staticmethod
    def _clean_output_tokens(tokens: list[str]) -> list[str]:
        ignored = {"<pad>", "</s>", "<s>"}
        return [token for token in tokens if token not in ignored]
