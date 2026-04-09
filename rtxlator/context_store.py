from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Iterable

CONTEXT_PATH = Path(__file__).resolve().parent.parent / "user_language_context.json"

DEFAULT_CONTEXT_DATA = {
    "version": 1,
    "source_normalization": {
        "pt": {
            "pra": "para",
            "pro": "para o",
            "tá": "esta",
            "to": "estou",
        }
    },
    "correction_memory": {
        "pt->en": {
            "pode fechar a conta": "Can you close the check?",
            "fechar pedido": "close the order",
        }
    },
    "preferred_translations": {
        "pt->en": {
            "em aberto": "open total",
            "salão": "dining room",
        }
    },
    "glossary": {
        "pt->en": {
            "caixa": "cash register",
            "comanda": "order ticket",
            "garçom": "waiter",
            "mesa": "table",
            "salão": "dining room",
        },
        "en->pt": {
            "cash register": "caixa",
            "order ticket": "comanda",
            "dining room": "salão",
        },
    },
    "target_replacements": {
        "pt->en": {
            "close the account": "close the check",
            "close account": "close check",
            "box": "cash register",
        }
    },
    "context_rules": [
        {
            "name": "desk-restaurant-pt-en",
            "source_lang": "pt",
            "target_lang": "en",
            "when_contains_any": ["caixa", "comanda", "pedido", "mesa", "salão", "garçom"],
            "preferred_terms": {
                "fechar a conta": "close the check",
                "fechar pedido": "close the order",
                "caixa": "cash register",
                "comanda": "order ticket",
            },
        }
    ],
}


class ContextStore:
    def __init__(self, path: Path = CONTEXT_PATH):
        self.path = path
        self.data = self._load_or_create()

    def _load_or_create(self) -> dict:
        if not self.path.exists():
            data = deepcopy(DEFAULT_CONTEXT_DATA)
            self._atomic_write(data)
            return data
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return self._ensure_structure(raw)
        except Exception:
            data = deepcopy(DEFAULT_CONTEXT_DATA)
            fallback = self.path.with_suffix(".broken.json")
            try:
                self.path.replace(fallback)
            except Exception:
                pass
            self._atomic_write(data)
            return data

    def _ensure_structure(self, raw: dict) -> dict:
        data = deepcopy(DEFAULT_CONTEXT_DATA)
        for key, value in raw.items():
            data[key] = value
        data.setdefault("version", 1)
        for key in ("source_normalization", "correction_memory", "preferred_translations", "glossary", "target_replacements"):
            if not isinstance(data.get(key), dict):
                data[key] = {}
        if not isinstance(data.get("context_rules"), list):
            data["context_rules"] = []
        return data

    def _atomic_write(self, data: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def save(self):
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.path.with_suffix(f".{timestamp}.bak")
        try:
            if self.path.exists():
                backup.write_text(self.path.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass
        self._atomic_write(self.data)

    @staticmethod
    def pair_key(source_lang: str | None, target_lang: str) -> str:
        return f"{source_lang or 'auto'}->{target_lang}"

    @staticmethod
    def normalize_lookup(text: str) -> str:
        collapsed = re.sub(r"\s+", " ", text.casefold().strip())
        return re.sub(r"[!?.,;:]+$", "", collapsed)

    def normalize_source_text(self, text: str, source_lang: str | None) -> str:
        if not source_lang:
            return text.strip()
        replacements = self.data.get("source_normalization", {}).get(source_lang, {})
        normalized = text
        for src, dst in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
            pattern = re.compile(rf"(?i)(?<!\w){re.escape(src)}(?!\w)")
            normalized = pattern.sub(dst, normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    def lookup_memory(self, text: str, source_lang: str | None, target_lang: str) -> str | None:
        pair_key = self.pair_key(source_lang, target_lang)
        lookup_key = self.normalize_lookup(text)
        for section in ("correction_memory", "preferred_translations"):
            candidate = self.data.get(section, {}).get(pair_key, {}).get(lookup_key)
            if candidate:
                return candidate
        return None

    def _active_terms(self, text: str, source_lang: str | None, target_lang: str) -> dict[str, str]:
        pair_key = self.pair_key(source_lang, target_lang)
        active = dict(self.data.get("glossary", {}).get(pair_key, {}))
        text_lookup = self.normalize_lookup(text)
        for rule in self.data.get("context_rules", []):
            if rule.get("source_lang") != source_lang or rule.get("target_lang") != target_lang:
                continue
            if any(keyword.casefold() in text_lookup for keyword in rule.get("when_contains_any", [])):
                active.update(rule.get("preferred_terms", {}))
        return active

    def protect_terms(self, text: str, source_lang: str | None, target_lang: str) -> tuple[str, dict[str, str]]:
        protected = text
        replacements: dict[str, str] = {}
        idx = 0
        for source_term, target_term in sorted(
            self._active_terms(text, source_lang, target_lang).items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            marker = f"[[T{idx}]]"
            pattern = re.compile(rf"(?i)(?<!\w){re.escape(source_term)}(?!\w)")
            if pattern.search(protected):
                protected = pattern.sub(marker, protected)
                replacements[marker] = target_term
                idx += 1
        return protected, replacements

    def apply_target_preferences(
        self,
        text: str,
        source_lang: str | None,
        target_lang: str,
        replacements: dict[str, str] | None = None,
    ) -> str:
        final = text
        for marker, replacement in (replacements or {}).items():
            final = final.replace(marker, replacement)
        pair_key = self.pair_key(source_lang, target_lang)
        for src, dst in sorted(
            self.data.get("target_replacements", {}).get(pair_key, {}).items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            final = re.compile(re.escape(src), re.I).sub(dst, final)
        return re.sub(r"\s+", " ", final).strip()

    def upsert_mapping(self, section: str, source_lang: str | None, target_lang: str, source_text: str, target_text: str):
        pair = self.pair_key(source_lang, target_lang)
        bucket = self.data.setdefault(section, {}).setdefault(pair, {})
        bucket[self.normalize_lookup(source_text)] = target_text.strip()

    def upsert_source_normalization(self, source_lang: str, heard: str, normalized: str):
        bucket = self.data.setdefault("source_normalization", {}).setdefault(source_lang, {})
        bucket[heard.strip()] = normalized.strip()

    def upsert_context_rule(
        self,
        *,
        source_lang: str,
        target_lang: str,
        rule_name: str,
        keywords: Iterable[str],
        source_text: str,
        target_text: str,
    ):
        keywords_clean = [item.strip() for item in keywords if item.strip()]
        normalized_source = self.normalize_lookup(source_text)
        normalized_target = target_text.strip()
        rules = self.data.setdefault("context_rules", [])
        for rule in rules:
            if rule.get("name") == rule_name and rule.get("source_lang") == source_lang and rule.get("target_lang") == target_lang:
                existing_keywords = {item.strip() for item in rule.get("when_contains_any", []) if item.strip()}
                existing_keywords.update(keywords_clean)
                rule["when_contains_any"] = sorted(existing_keywords)
                preferred = rule.setdefault("preferred_terms", {})
                preferred[normalized_source] = normalized_target
                return
        rules.append(
            {
                "name": rule_name,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "when_contains_any": sorted(set(keywords_clean)),
                "preferred_terms": {normalized_source: normalized_target},
            }
        )

    def summary_lines(self) -> list[str]:
        def count_pairs(section: str) -> int:
            return sum(len(v) for v in self.data.get(section, {}).values())

        return [
            f"Arquivo : {self.path}",
            f"Correções prontas : {count_pairs('correction_memory')}",
            f"Frases preferidas : {count_pairs('preferred_translations')}",
            f"Glossário        : {count_pairs('glossary')}",
            f"Correções finais : {count_pairs('target_replacements')}",
            f"Normalizações    : {sum(len(v) for v in self.data.get('source_normalization', {}).values())}",
            f"Regras context.  : {len(self.data.get('context_rules', []))}",
        ]

    def preview_entries(self, section: str, limit: int = 5) -> list[str]:
        lines: list[str] = []
        data = self.data.get(section, {})
        if isinstance(data, dict):
            for pair, mapping in data.items():
                if not isinstance(mapping, dict):
                    continue
                for src, dst in list(mapping.items())[:limit]:
                    lines.append(f"{pair}: {src} -> {dst}")
                if lines:
                    break
        if section == "context_rules":
            for rule in self.data.get("context_rules", [])[:limit]:
                lines.append(
                    f"{rule.get('name')} [{rule.get('source_lang')}->{rule.get('target_lang')}] kw={', '.join(rule.get('when_contains_any', []))}"
                )
        return lines or ["(sem itens)"]


PersonalLanguageContext = ContextStore
