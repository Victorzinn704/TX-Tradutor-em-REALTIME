# Validação local

Data da última revisão documental: 2026-06-16.

Este registro descreve o que foi conferido localmente antes da atualização documental. Ele não substitui o CI do GitHub, mas ajuda a explicar o estado real do projeto e as decisões de manutenção.

## Ambiente usado

| Item | Valor observado |
| --- | --- |
| Sistema | Windows |
| Python no PATH | 3.14.3 |
| pytest | 9.0.3 |
| Cargo/Rust | disponível localmente |
| CI do repositório | Windows, Python 3.11, Rust stable |

O projeto declara Python 3.11+ e o CI usa Python 3.11. O Python 3.14 local é útil para revelar compatibilidade de ferramenta, mas não é a versão base do pipeline remoto.

## Comandos executados

### Testes Python

```bat
python -m pytest -q
```

Resultado:

```text
61 passed
```

Esse resultado corrigiu a documentação anterior, que ainda citava uma contagem menor de testes Python.

### Pré-build Rust sem variável PyO3

```bat
cd runtime-rs
cargo test --workspace --no-run
```

Resultado:

```text
error: the configured Python interpreter version (3.14) is newer than PyO3's maximum supported version (3.13)
```

Decisão:

- não alterar dependências Rust neste PR;
- documentar o comportamento;
- manter o caminho já previsto em `compilar_rust.bat`, que define `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1`.

### Testes Rust com variável PyO3

```bat
cd runtime-rs
set PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
cargo test --workspace
```

Resultado:

```text
rtxlator-audio: 7 passed
rtxlator-dsp: 13 passed
rtxlator-sched: 12 passed
rtxlator-ffi: 0 tests
doc-tests: passed
```

### Higiene pública do repositório

```bat
rg -n "<padrao_de_caminho_local>|<termo_de_agente>" -S .
```

Achados corrigidos:

- `criar_atalhos.ps1` usava caminhos fixos de máquina;
- `runtime-rs/audio/src/lib.rs` citava uma ferramenta/agente em comentário técnico.

## Correções feitas nesta revisão

| Arquivo | Ajuste |
| --- | --- |
| `criar_atalhos.ps1` | Passou a usar `$PSScriptRoot` e a Área de Trabalho real do usuário. |
| `runtime-rs/audio/src/lib.rs` | Comentário técnico ficou neutro e vinculado ao contrato WASAPI. |
| `.gitignore` | Removida sobra textual sem função. |
| `README.md` | Defaults de CLI, perfis de latência e contagem de testes foram alinhados ao código. |
| `ARCHITECTURE.md` | Perfis de latência passaram a refletir `ultra`, `balanced` e `quality`. |
| `docs/RFC-001-performance-roadmap.md` | Status das fases passou a separar implementação de benchmark final. |

## O que ainda exige máquina real

Alguns pontos não devem ser validados só por teste unitário:

- captura WASAPI com microfone real;
- loopback do endpoint correto de áudio;
- latência p95 com corpus de fala real;
- comportamento do fallback Google em rede instável;
- consumo de VRAM por modelo Whisper escolhido;
- overlay flutuante sobre janela ativa.

Esses itens dependem de hardware, driver e cenário de uso. O projeto documenta o caminho de diagnóstico, mas a medição final precisa acontecer no computador de apresentação ou uso diário.

## Critério atual de pronto

Para considerar uma alteração pronta neste repositório:

1. `python -m pytest` deve passar quando as dependências estiverem instaladas;
2. `cargo test --workspace` deve passar no ambiente Rust configurado;
3. `diagnostico.bat` deve listar dispositivos sem quebrar o terminal;
4. `README.md` não deve prometer perfil, teste ou fluxo que o código não expõe;
5. caminhos locais e estado pessoal não devem ser versionados.
