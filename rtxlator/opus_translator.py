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
    tokenizer: Any
    source_prefix: str | None = None


_TOKENIZER_FILES = (
    "tokenizer_config.json",
    "vocab.json",
    "source.spm",
    "target.spm",
)

_OPUS_REPO_CANDIDATES: dict[tuple[str, str], list[tuple[str, str | None]]] = {
    ("en", "pt"): [
        ("Helsinki-NLP/opus-mt-tc-big-en-pt", None),
        ("Helsinki-NLP/opus-mt-en-ROMANCE", ">>pt<<"),
    ],
    ("pt", "en"): [
        ("Helsinki-NLP/opus-mt-mul-en", ">>pt<<"),
        ("Helsinki-NLP/opus-mt-tc-big-mul-en", ">>pt<<"),
    ],
}


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

        source_ids = list(pair.tokenizer.encode(source_text))
        source_tokens = list(pair.tokenizer.convert_ids_to_tokens(source_ids))
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
        output_ids = pair.tokenizer.convert_tokens_to_ids(output_tokens)
        translated = pair.tokenizer.decode(output_ids, skip_special_tokens=True).strip()
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

        if not model_file.exists():
            return None

        if not self._ensure_tokenizer_assets(pair_dir, source_lang, target_lang):
            return None

        ctranslate2_module, transformers_module = self._import_runtime_deps()
        translator = ctranslate2_module.Translator(
            str(pair_dir),
            device=self.device,
            compute_type=self.compute_type,
        )
        tokenizer = transformers_module.MarianTokenizer.from_pretrained(
            str(pair_dir),
            local_files_only=True,
        )
        source_prefix = self._read_optional_text(pair_dir / "source_prefix.txt")

        return _LoadedOpusPair(
            translator=translator,
            tokenizer=tokenizer,
            source_prefix=source_prefix,
        )

    def _ensure_tokenizer_assets(self, pair_dir: Path, source_lang: str, target_lang: str) -> bool:
        missing_files = [name for name in _TOKENIZER_FILES if not (pair_dir / name).exists()]
        if not missing_files:
            return True

        repo_candidates = self._resolve_repo_candidates(pair_dir, source_lang, target_lang)
        if not repo_candidates:
            console.print(
                f"[yellow]OPUS-MT {source_lang}->{target_lang} sem tokenizer local e sem repo conhecido[/yellow]"
            )
            return False

        hub_module = self._import_hub_dep()
        for repo_id, source_prefix in repo_candidates:
            try:
                for filename in missing_files:
                    downloaded = Path(hub_module.hf_hub_download(repo_id=repo_id, filename=filename))
                    (pair_dir / filename).write_bytes(downloaded.read_bytes())
                (pair_dir / "hf_repo.txt").write_text(repo_id, encoding="utf-8")
                if source_prefix and not (pair_dir / "source_prefix.txt").exists():
                    (pair_dir / "source_prefix.txt").write_text(source_prefix, encoding="utf-8")
                console.print(f"[green][OK] Tokenizer OPUS-MT reparado de {repo_id}[/green]")
                return True
            except Exception as exc:
                console.print(
                    f"[yellow]Falha ao baixar tokenizer OPUS-MT de {repo_id}: {exc}[/yellow]"
                )

        console.print(
            f"[yellow]OPUS-MT {source_lang}->{target_lang} sem tokenizer local utilizavel[/yellow]"
        )
        return False

    def _resolve_repo_candidates(
        self,
        pair_dir: Path,
        source_lang: str,
        target_lang: str,
    ) -> list[tuple[str, str | None]]:
        repo_hint = self._read_optional_text(pair_dir / "hf_repo.txt")
        if repo_hint:
            source_prefix = self._read_optional_text(pair_dir / "source_prefix.txt")
            return [(repo_hint, source_prefix)]
        return list(_OPUS_REPO_CANDIDATES.get((source_lang, target_lang), ()))

    def _import_runtime_deps(self) -> tuple[ModuleType, ModuleType]:
        import ctranslate2
        import transformers

        return ctranslate2, transformers

    def _import_hub_dep(self) -> ModuleType:
        import huggingface_hub

        return huggingface_hub

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
