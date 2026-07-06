# Como Contribuir

O objetivo deste repositorio e manter um tradutor local de audio em tempo real simples de instalar, testar e auditar.

## Fluxo recomendado

1. Abra PR pequeno e descreva o fluxo afetado: captura, VAD, ASR, traducao, Rust runtime, instalacao ou docs.
2. Evite incluir logs ou caminhos locais com dados pessoais.
3. Rode os checks aplicaveis antes de pedir revisao.

## Checks locais

```bash
python -m pytest tests/ -q
```

Para o runtime Rust:

```bash
cd runtime-rs
cargo test
cargo check
```

## Regras de contribuicao

- nao versionar modelos baixados, binarios gerados ou audio real;
- documentar novas dependencias nativas;
- preservar fallback quando hardware, CUDA ou dispositivo de audio nao estiverem disponiveis.
