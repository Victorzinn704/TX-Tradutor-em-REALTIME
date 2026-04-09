import tempfile
import unittest
from pathlib import Path

from gerenciar_contexto import ContextStore


class ContextManagerTests(unittest.TestCase):
    def test_upsert_mapping_and_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ctx.json'
            store = ContextStore(path)
            store.upsert_mapping('correction_memory', 'pt', 'en', 'Pode fechar a conta?', 'Can you close the check?')
            store.save()
            reloaded = ContextStore(path)
            self.assertEqual(
                reloaded.data['correction_memory']['pt->en']['pode fechar a conta'],
                'Can you close the check?',
            )

    def test_upsert_context_rule_merges_keywords(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ctx.json'
            store = ContextStore(path)
            store.upsert_context_rule(
                source_lang='pt',
                target_lang='en',
                rule_name='desk-restaurant-pt-en',
                keywords=['mesa', 'pedido'],
                source_text='fechar pedido',
                target_text='close the order',
            )
            store.upsert_context_rule(
                source_lang='pt',
                target_lang='en',
                rule_name='desk-restaurant-pt-en',
                keywords=['garçom'],
                source_text='caixa',
                target_text='cash register',
            )
            rule = next(item for item in store.data['context_rules'] if item['name'] == 'desk-restaurant-pt-en')
            self.assertIn('garçom', rule['when_contains_any'])
            self.assertEqual(rule['preferred_terms']['caixa'], 'cash register')


if __name__ == '__main__':
    unittest.main()
