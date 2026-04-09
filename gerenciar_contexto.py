from __future__ import annotations

from rtxlator.context_store import CONTEXT_PATH, ContextStore


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" ({default})" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def choose_source_lang(allow_detect: bool = True) -> str | None:
    options = "detect/pt/en/es" if allow_detect else "pt/en/es"
    while True:
        raw = ask(f"Idioma de origem [{options}]", "detect" if allow_detect else "pt").casefold()
        if allow_detect and raw in ("detect", "detectar", "auto"):
            return None
        if raw in ("pt", "en", "es"):
            return raw
        print("Valor inválido. Use detect, pt, en ou es.")


def choose_target_lang() -> str:
    while True:
        raw = ask("Idioma de destino [pt/en/es]", "en").casefold()
        if raw in ("pt", "en", "es"):
            return raw
        print("Valor inválido. Use pt, en ou es.")


def print_block(title: str, lines: list[str]):
    print("\n" + "=" * 62)
    print(title)
    print("=" * 62)
    for line in lines:
        print(line)


def action_add_correction(store: ContextStore):
    src = choose_source_lang()
    dst = choose_target_lang()
    source_text = ask("Frase como você costuma falar")
    target_text = ask("Tradução final correta")
    store.upsert_mapping("correction_memory", src, dst, source_text, target_text)
    store.save()
    print("\n[ok] Correção salva.")


def action_add_glossary(store: ContextStore):
    src = choose_source_lang(allow_detect=False)
    dst = choose_target_lang()
    source_text = ask("Termo original")
    target_text = ask("Termo preferido")
    store.upsert_mapping("glossary", src, dst, source_text, target_text)
    store.save()
    print("\n[ok] Glossário salvo.")


def action_add_preferred(store: ContextStore):
    src = choose_source_lang()
    dst = choose_target_lang()
    source_text = ask("Frase que costuma sair ruim")
    target_text = ask("Tradução preferida")
    store.upsert_mapping("preferred_translations", src, dst, source_text, target_text)
    store.save()
    print("\n[ok] Frase preferida salva.")


def action_add_target_replacement(store: ContextStore):
    src = choose_source_lang()
    dst = choose_target_lang()
    source_text = ask("Saída errada atual")
    target_text = ask("Saída desejada")
    store.upsert_mapping("target_replacements", src, dst, source_text, target_text)
    store.save()
    print("\n[ok] Correção final salva.")


def action_add_normalization(store: ContextStore):
    src = choose_source_lang(allow_detect=False)
    heard = ask("Jeito que você fala")
    normalized = ask("Forma normalizada")
    store.upsert_source_normalization(src, heard, normalized)
    store.save()
    print("\n[ok] Normalização salva.")


def action_add_context_rule(store: ContextStore):
    src = choose_source_lang(allow_detect=False)
    dst = choose_target_lang()
    rule_name = ask("Nome da regra", f"regra-{src}-{dst}")
    keywords_raw = ask("Palavras-chave que ativam a regra (separadas por vírgula)")
    source_text = ask("Frase/termo a forçar nessa situação")
    target_text = ask("Tradução preferida nessa situação")
    store.upsert_context_rule(
        source_lang=src,
        target_lang=dst,
        rule_name=rule_name,
        keywords=[item.strip() for item in keywords_raw.split(",")],
        source_text=source_text,
        target_text=target_text,
    )
    store.save()
    print("\n[ok] Regra contextual salva.")


def action_show_summary(store: ContextStore):
    print_block("CONTEXTO PESSOAL - RESUMO", store.summary_lines())
    for section, label in (
        ("correction_memory", "Correções prontas"),
        ("preferred_translations", "Frases preferidas"),
        ("glossary", "Glossário"),
        ("target_replacements", "Correções finais"),
        ("context_rules", "Regras contextuais"),
    ):
        print_block(label, store.preview_entries(section))


def main():
    store = ContextStore(CONTEXT_PATH)
    while True:
        print_block(
            "GERENCIADOR DE CONTEXTO PESSOAL",
            [
                "1) Ver resumo atual",
                "2) Ensinar frase completa (memória de correção)",
                "3) Ensinar termo do glossário",
                "4) Definir frase preferida",
                "5) Corrigir saída final",
                "6) Normalizar seu jeito de falar",
                "7) Criar/atualizar regra de contexto",
                "8) Sair",
            ],
        )
        choice = ask("Escolha uma opção", "1")
        if choice == "1":
            action_show_summary(store)
        elif choice == "2":
            action_add_correction(store)
        elif choice == "3":
            action_add_glossary(store)
        elif choice == "4":
            action_add_preferred(store)
        elif choice == "5":
            action_add_target_replacement(store)
        elif choice == "6":
            action_add_normalization(store)
        elif choice == "7":
            action_add_context_rule(store)
        elif choice == "8":
            print("\nAté logo. Contexto salvo em:")
            print(store.path)
            return
        else:
            print("\nOpção inválida.")


if __name__ == "__main__":
    main()
