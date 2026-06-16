# Matriz De Testes, Casos De Uso E Evidencias

Data da revisao: 2026-06-16.

## Objetivo

Este documento liga cada uso importante do tradutor ao modulo que implementa a regra, ao teste automatizado existente e ao tipo de evidencia que ainda exige maquina real.

A leitura correta e:

```text
caso de uso -> regra tecnica -> arquivo -> teste automatizado -> evidencia real -> limite
```

## Casos De Uso

| ID | Caso de uso | Regra tecnica | Arquivos | Teste/evidencia | Limite conhecido |
| --- | --- | --- | --- | --- | --- |
| UC-01 | Traduzir fala do microfone em tempo real | Capturar audio, aplicar VAD, transcrever, traduzir e exibir no terminal | `realtime_translator.py`, `rtxlator/pipeline.py`, `rtxlator/audio_io.py`, `rtxlator/display.py` | `tests/test_realtime_translator.py`, `tests/test_integration.py` | Captura real depende de microfone, WASAPI e driver |
| UC-02 | Traduzir audio do sistema por loopback | Usar endpoint correto de saida de audio e perfil `system`/`system_en` | `rtxlator/audio_io.py`, `rtxlator/source_profiles.py`, `docs/GUIA-DE-USO-WINDOWS.md` | `tests/test_source_profiles.py` + diagnostico manual | Precisa de Windows 11 e endpoint de loopback correto |
| UC-03 | Manter idioma travado por fonte/sessao | Evitar autodetect continuo depois da primeira frase estavel | `rtxlator/pipeline.py`, `rtxlator/source_profiles.py` | `tests/test_realtime_translator.py`, `tests/test_source_profiles.py` | Troca real de idioma precisa ser medida com audio real |
| UC-04 | Traduzir rapido pelo hot path local | OPUS-MT/CTranslate2 entra antes de fallbacks mais lentos | `rtxlator/opus_translator.py`, `rtxlator/translator.py` | `tests/test_opus_translator.py` | Benchmark p95 depende de modelo baixado e GPU/CPU local |
| UC-05 | Usar fallback local ou contextual | Argos cobre pares sem OPUS-MT; Google fica fora do hot path parcial | `rtxlator/translator.py`, `rtxlator/text_processing.py` | `tests/test_text_processing.py`, `tests/test_circuit_breaker.py` | Fallback Google depende de rede e deve ser medido fora do CI |
| UC-06 | Personalizar termos e correcoes | Contexto pessoal altera glossario, memoria e preferencias | `rtxlator/context_store.py`, `gerenciar_contexto.py` | `tests/test_context_manager.py` | `user_language_context.json` pode conter dado pessoal e nao deve ir para Git |
| UC-07 | Controlar backlog, cache e repeticoes | Cache evita retraducao; circuit breaker limita provider instavel | `rtxlator/cache.py`, `rtxlator/translator.py` | `tests/test_cache.py`, `tests/test_circuit_breaker.py` | Taxa de queda e fila real exigem audio continuo |
| UC-08 | Compilar runtime Rust opcional | Rust melhora captura, DSP e scheduler quando `runtime_rs.pyd` existe | `runtime-rs/`, `rtxlator/audio_rs.py`, `compilar_rust.bat` | `cargo test --workspace`; CI testa crates `audio` e `dsp` | Integração plena ao pipeline principal ainda e proxima fase |
| UC-09 | Rodar ponte de texto | Traduzir mensagem digitada sem audio | `texto_bridge.py`, `rtxlator/text_bridge.py` | `tests/test_text_processing.py` | Nao valida audio, VAD ou ASR |
| UC-10 | Diagnosticar ambiente Windows | Conferir CUDA, dispositivos, modelos e runtime | `diagnostico.py`, `diagnostico.bat`, `listar_dispositivos.bat` | Validacao manual documentada | Depende da maquina de apresentacao |

## Regras Que Nao Podem Quebrar

| ID | Regra | Onde aparece | Validacao |
| --- | --- | --- | --- |
| REG-01 | `partial` nao deve bloquear `final` | `ARCHITECTURE.md`, `rtxlator/pipeline.py`, `runtime-rs/sched` | testes Python/Rust + benchmark futuro |
| REG-02 | Fallback remoto nao deve entrar no hot path parcial | `rtxlator/translator.py`, `docs/RFC-001-performance-roadmap.md` | testes de texto/fallback + revisao |
| REG-03 | Contexto pessoal nao deve ser versionado | `.gitignore`, `rtxlator/context_store.py` | higiene de Git e revisao documental |
| REG-04 | Rust e opcional; Python precisa continuar rodando sem `runtime_rs.pyd` | `rtxlator/audio_rs.py` | testes Python e validacao manual |
| REG-05 | Python 3.11 e a base do CI | `.github/workflows/ci.yml` | workflow CI em Windows |
| REG-06 | Python 3.14 local exige cuidado com PyO3 | `compilar_rust.bat`, `docs/VALIDACAO-LOCAL.md` | teste Rust com `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` |

## Matriz De Validacao

| Camada | Comando | O que comprova |
| --- | --- | --- |
| Testes Python | `python -m pytest tests/ --cov=rtxlator --cov-report=term-missing -q` | Regras automatizadas de pipeline, texto, contexto, cache, profiles e translator |
| Rust workspace | `cargo test --workspace` | Crates Rust compilam e testes de audio/DSP/scheduler passam localmente |
| CI Python | workflow `CI` | Instala dependencias em Windows com Python 3.11 e roda testes com cobertura |
| CI Rust | workflow `CI` | Testa `rtxlator-dsp`, checa `rtxlator-audio` e roda testes Rust no Windows |
| Diagnostico | `diagnostico.bat` | Dispositivos, CUDA, modelos e runtime em maquina real |
| Uso real | `rodar.bat` ou `python realtime_translator.py ...` | Captura, ASR, traducao e UI em ambiente local |
| Ponte de texto | `python texto_bridge.py --source pt --target en` | Caminho textual sem audio |

## Evidencias

| Evidencia | Caminho | O que prova |
| --- | --- | --- |
| Validacao local | `docs/VALIDACAO-LOCAL.md` | Python tests, Rust tests, comportamento PyO3 e pontos que exigem hardware |
| Guia Windows | `docs/GUIA-DE-USO-WINDOWS.md` | Preparo de maquina, diagnostico, uso, IDs de audio e problemas comuns |
| Arquitetura | `ARCHITECTURE.md` | Camadas Python/Rust, fluxo de audio, traducao e UI |
| RFC performance | `docs/RFC-001-performance-roadmap.md` | Decisoes de latencia, fast lane, VAD, scheduler e benchmark pendente |
| CI | `.github/workflows/ci.yml` | Gate remoto de Python/Rust em Windows |

## Gaps Tecnicos

| Gap | Impacto | Acao recomendada |
| --- | --- | --- |
| Captura WASAPI real nao roda em CI | CI nao prova microfone, loopback ou endpoint correto | Usar `diagnostico.bat` e validacao em maquina de apresentacao |
| Benchmark p95 ainda depende de corpus real | Metas de latencia do RFC ficam sem medicao final | Criar corpus local e registrar `first_partial_ms`, `translate_ms`, `drop_rate` |
| Runtime Rust ainda nao substitui todo pipeline principal | Parte da reducao de jitter fica como fase futura | Integrar fila Rust ao `AudioPipeline` |
| Google fallback depende de rede externa | Resultado pode variar por disponibilidade e limite de provider | Manter Google fora do hot path parcial e medir separadamente |
| Overlay flutuante ainda e frente futura | Uso sem terminal ainda nao esta fechado | Criar validacao propria quando a UI overlay entrar |
