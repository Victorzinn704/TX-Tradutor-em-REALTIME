"""Tradutor local GPU/CPU via argostranslate + fallback Google Translate."""
from __future__ import annotations

import os
import threading
from pathlib import Path

from .constants import (
    CONTEXT_CURRENT_MARKER,
    CONTEXT_END_MARKER,
    MODELS_DIR,
    console,
    extract_contextual_segment,
)
from .context_store import PersonalLanguageContext


class GPUTranslator:
    """
    Tradução 100% local usando argostranslate (ctranslate2 internamente).

    GPU se CUDA disponível via ARGOS_DEVICE_TYPE=cuda, senão CPU (~20-30ms).
    Fallback automático para Google Translate se par sem pacote disponível.
    """

    def __init__(
        self,
        target_lang:         str,
        device:              str,
        compute_type:        str,
        models_dir:          Path = MODELS_DIR,
        interpretation_mode: str  = "hybrid",
        personal_context:    PersonalLanguageContext | None = None,
        opus_translator:     object | None = None,
    ):
        # ARGOS_DEVICE_TYPE deve ser definido ANTES do primeiro import argostranslate
        if device == "cuda":
            os.environ.setdefault("ARGOS_DEVICE_TYPE", "cuda")

        argos_pkg_dir = models_dir / "argos"
        argos_pkg_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("ARGOS_PACKAGES_DIR", str(argos_pkg_dir))

        self.target_lang         = target_lang
        self.device              = device
        self.interpretation_mode = interpretation_mode
        self.personal_context    = personal_context

        self._opus          = opus_translator
        self._installed:    set[str]       = set()
        self._lock          = threading.Lock()
        self._fallback_lock = threading.Lock()
        self._argos_ready   = self._try_init_argos()

    def _try_init_argos(self) -> bool:
        try:
            import argostranslate.package   # noqa: F401
            import argostranslate.translate  # noqa: F401
            return True
        except ImportError:
            console.print("[yellow]argostranslate nao instalado — pip install argostranslate[/yellow]")
            return False

    # ── API pública ────────────────────────────────────────────────────────

    def translate(
        self,
        text: str,
        src_lang: str = "auto",
        *,
        prefer_context: bool = False,
        context_segments: list[str] | None = None,
        allow_remote_fallback: bool = True,
    ) -> tuple[str, str]:
        """Traduz text de src_lang → target_lang. Thread-safe. Retorna (texto, provider)."""
        if not text.strip() or src_lang == self.target_lang:
            return text, "identity"

        source_text = text.strip()
        if self.personal_context is not None:
            source_text = self.personal_context.normalize_source_text(source_text, src_lang)
            direct = self.personal_context.lookup_memory(source_text, src_lang, self.target_lang)
            if direct:
                return direct, "memory"
            protected_text, protected_terms = self.personal_context.protect_terms(
                source_text, src_lang, self.target_lang,
            )
            prepared_context = [
                self.personal_context.normalize_source_text(seg, src_lang)
                for seg in (context_segments or [])
            ]
        else:
            protected_text   = source_text
            protected_terms  = {}
            prepared_context = context_segments or []

        cloud_first = (
            self.interpretation_mode == "contextual"
            or (self.interpretation_mode == "hybrid" and prefer_context)
        )

        if cloud_first and prepared_context and allow_remote_fallback:
            contextual = self._translate_google_with_context(protected_text, src_lang, prepared_context)
            if contextual:
                final = self._postprocess(contextual, src_lang, protected_terms)
                return final, "google-ctx"

        if allow_remote_fallback:
            attempts = (
                (self._translate_google, "google"),
                (self._translate_argos,  "argos"),
            ) if cloud_first else (
                (self._translate_opus,   "opus-mt"),  # fast lane local ~40ms
                (self._translate_argos,  "argos"),
                (self._translate_google, "google"),
            )
        else:
            attempts = (
                (self._translate_opus,  "opus-mt"),
                (self._translate_argos, "argos"),
            )

        for fn, provider in attempts:
            result = fn(protected_text, src_lang)
            if result:
                final = self._postprocess(result, src_lang, protected_terms)
                return final, provider

        return source_text, "identity"

    def preload(self, src_langs: list[str]) -> threading.Thread:
        """Pré-carrega pacotes de tradução em background."""
        def _run():
            for lang in src_langs:
                if not lang or lang == self.target_lang or not self._argos_ready:
                    continue
                if self._ensure_package(lang):
                    console.print(f"[green][OK] Traducao {lang}->{self.target_lang} pronta[/green]")
                else:
                    console.print(f"[yellow]  {lang}->{self.target_lang}: sem modelo, usara Google Translate[/yellow]")
        t = threading.Thread(target=_run, daemon=True, name="trans-preload")
        t.start()
        return t

    def normalize_lookup_text(self, text: str, source_lang: str | None) -> str:
        if self.personal_context is None:
            return text.strip()
        return self.personal_context.normalize_source_text(text, source_lang)

    # ── Internos ───────────────────────────────────────────────────────────

    def _translate_opus(self, text: str, src_lang: str) -> str | None:
        """Tenta OPUS-MT/CTranslate2. Retorna None se modelo não disponível."""
        if self._opus is None or src_lang in ("auto", ""):
            return None
        try:
            result, provider = self._opus.translate(text, src_lang)
            return result if provider != "identity" else None
        except Exception:
            return None

    def _translate_argos(self, text: str, src_lang: str) -> str | None:
        if not (self._argos_ready and src_lang not in ("auto", "")):
            return None
        try:
            if self._ensure_package(src_lang):
                import argostranslate.translate
                result = argostranslate.translate.translate(text, src_lang, self.target_lang)
                return result or None
        except Exception as e:
            console.print(f"[yellow]translate err ({src_lang}->{self.target_lang}): {e}[/yellow]")
        return None

    def _translate_google(self, text: str, src_lang: str) -> str | None:
        try:
            from deep_translator import GoogleTranslator
            with self._fallback_lock:
                source = src_lang if src_lang not in ("", "auto") else "auto"
                return GoogleTranslator(source=source, target=self.target_lang).translate(text) or None
        except Exception:
            return None

    def _translate_google_with_context(
        self, text: str, src_lang: str, context_segments: list[str],
    ) -> str | None:
        clean = [s.strip() for s in context_segments if s and s.strip()]
        if not clean:
            return self._translate_google(text, src_lang)
        history  = " ".join(clean[-2:])
        combined = f"{history} {CONTEXT_CURRENT_MARKER} {text} {CONTEXT_END_MARKER}".strip()
        translated = self._translate_google(combined, src_lang)
        if not translated:
            return None
        candidate = extract_contextual_segment(translated)
        return candidate if candidate else self._translate_google(text, src_lang)

    def _postprocess(self, text: str, source_lang: str | None, protected_terms: dict[str, str]) -> str:
        if self.personal_context is None:
            return text
        return self.personal_context.apply_target_preferences(
            text, source_lang, self.target_lang, replacements=protected_terms,
        )

    def _ensure_package(self, from_code: str) -> bool:
        if not from_code or from_code == self.target_lang:
            return False
        key = f"{from_code}::{self.target_lang}"
        if key in self._installed:
            return True
        with self._lock:
            if key in self._installed:
                return True
            try:
                import argostranslate.package
                import argostranslate.translate

                for pkg in argostranslate.package.get_installed_packages():
                    if pkg.from_code == from_code and pkg.to_code == self.target_lang:
                        self._installed.add(key)
                        return True

                console.print(f"[dim]  Baixando pacote {from_code}->{self.target_lang}...[/dim]")
                argostranslate.package.update_package_index()
                available = argostranslate.package.get_available_packages()
                pkg = next(
                    (p for p in available if p.from_code == from_code and p.to_code == self.target_lang),
                    None,
                )
                if pkg is None:
                    console.print(f"[yellow]  Sem pacote para {from_code}->{self.target_lang}[/yellow]")
                    return False

                argostranslate.package.install_from_path(pkg.download())
                self._installed.add(key)
                console.print(f"[green]  [OK] {from_code}->{self.target_lang} instalado[/green]")
                return True
            except Exception as e:
                console.print(f"[red]  Erro ao instalar pacote {from_code}->{self.target_lang}: {e}[/red]")
                return False
