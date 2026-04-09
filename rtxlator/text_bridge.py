from __future__ import annotations

import argparse
from dataclasses import dataclass

from .context_store import CONTEXT_PATH, PersonalLanguageContext
from .text_processing import TextEnvelope, TextProcessor


def normalize_lang_choice(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip().casefold()
    if raw in ("", "detect", "detectar", "auto"):
        return None
    return raw


@dataclass(frozen=True)
class TextBridgeConfig:
    source_lang: str | None
    target_lang: str
    reverse_target_lang: str
    interpretation_mode: str = "hybrid"


class TextBridgeSession:
    def __init__(self, config: TextBridgeConfig, translator_factory):
        self.config = config
        self.outgoing_translator, self.outgoing_cache = translator_factory(
            config.target_lang,
            config.interpretation_mode,
        )
        self.incoming_translator, self.incoming_cache = translator_factory(
            config.reverse_target_lang,
            "fast",
        )
        self.outgoing = TextProcessor(self.outgoing_translator, self.outgoing_cache)
        self.incoming = TextProcessor(self.incoming_translator, self.incoming_cache)

    def translate_outgoing(self, text: str):
        return self.outgoing.resolve(
            TextEnvelope(
                source="TEXT-OUT",
                raw_text=text,
                source_lang=self.config.source_lang,
                target_lang=self.config.target_lang,
                direction="outbound",
            )
        )

    def translate_incoming(self, text: str, source_lang: str | None = None):
        return self.incoming.resolve(
            TextEnvelope(
                source="TEXT-IN",
                raw_text=text,
                source_lang=source_lang or self.config.target_lang,
                target_lang=self.config.reverse_target_lang,
                direction="inbound",
            )
        )


def run_interactive(session: TextBridgeSession):
    print("=" * 68)
    print("PONTE DE TEXTO")
    print("=" * 68)
    print("Digite com um prefixo:")
    print("  > sua mensagem para enviar")
    print("  < mensagem recebida para traduzir")
    print("  /help para ajuda, /quit para sair")
    print()
    while True:
        raw = input("texto> ").strip()
        if not raw:
            continue
        if raw in ("/quit", "/exit", "/q"):
            print("Encerrado.")
            return
        if raw == "/help":
            print("Use '> texto' para saída e '< texto' para entrada.")
            continue
        if raw.startswith(">"):
            resolution = session.translate_outgoing(raw[1:].strip())
            print(f"[saida/{resolution.provider}] {resolution.translated}")
            continue
        if raw.startswith("<"):
            resolution = session.translate_incoming(raw[1:].strip())
            print(f"[entrada/{resolution.provider}] {resolution.translated}")
            continue
        resolution = session.translate_outgoing(raw)
        print(f"[saida/{resolution.provider}] {resolution.translated}")


def build_text_bridge_session(config: TextBridgeConfig):
    from realtime_translator import (
        MODELS_DIR,
        TranslationCache,
        detect_device,
        GPUTranslator,
    )

    device, compute_type, _ = detect_device()
    personal_context = PersonalLanguageContext(CONTEXT_PATH)

    def translator_factory(target_lang: str, interpretation_mode: str):
        translator = GPUTranslator(
            target_lang=target_lang,
            device=device,
            compute_type=compute_type,
            models_dir=MODELS_DIR,
            interpretation_mode=interpretation_mode,
            personal_context=personal_context,
        )
        preload_langs = [config.source_lang] if config.source_lang else ["en"]
        translator.preload([lang for lang in preload_langs if lang])
        return translator, TranslationCache()

    return TextBridgeSession(config, translator_factory)


def main():
    ap = argparse.ArgumentParser(description="Ponte de texto para tradução de entrada e saída.")
    ap.add_argument("--source", default="pt", help="Idioma de origem para suas mensagens.")
    ap.add_argument("--target", default="en", help="Idioma de destino para suas mensagens.")
    ap.add_argument("--reply-target", default=None, help="Idioma para traduzir mensagens recebidas.")
    ap.add_argument("--mode", default="duplex", choices=["duplex", "outgoing", "incoming"])
    ap.add_argument("--text", default=None, help="Executa uma tradução única e sai.")
    ap.add_argument("--interpretation-mode", default="hybrid", choices=["fast", "hybrid", "contextual"])
    args = ap.parse_args()

    config = TextBridgeConfig(
        source_lang=normalize_lang_choice(args.source),
        target_lang=args.target,
        reverse_target_lang=args.reply_target or (args.source if args.source not in ("", "detect", "detectar", "auto") else "pt"),
        interpretation_mode=args.interpretation_mode,
    )
    session = build_text_bridge_session(config)

    if args.text:
        if args.mode == "incoming":
            result = session.translate_incoming(args.text)
        else:
            result = session.translate_outgoing(args.text)
        print(result.translated)
        return

    run_interactive(session)


if __name__ == "__main__":
    main()
