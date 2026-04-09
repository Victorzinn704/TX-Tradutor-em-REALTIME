# Arquitetura — Realtime Translator

## Filosofia

O hot path pesado já roda em código nativo/CUDA. O Python aqui é orquestração — e isso é correto. O Rust entra onde o Python tem jitter real: captura de áudio e scheduling de segmentos.

```
┌─────────────────────────────────────────────────────────┐
│  Python (orquestração, UI, integração)                  │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │ AudioPipeline│  │ GPUTranslator│  │  Rich UI       │ │
│  │ (VAD+ASR)    │  │ OpusMT+Argos │  │  display.py    │ │
│  └──────┬───────┘  └──────┬───────┘  └────────────────┘ │
│         │                 │                               │
│  ┌──────▼───────────────────────────────────────┐        │
│  │  CTranslate2 / faster-whisper (nativo/CUDA)  │        │
│  └──────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────┘
         ▲
         │  PyO3 (runtime_rs.pyd)
┌────────┴────────────────────────────────────────────────┐
│  Rust (runtime-rs/)                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │  audio   │  │   dsp    │  │  sched   │  │  ffi   │  │
│  │ WASAPI   │  │ VAD+DSP  │  │ Queues   │  │  PyO3  │  │
│  │ capture  │  │ resample │  │ deadlines│  │ bridge │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

## Camadas

### Python — `rtxlator/`

| Módulo | Responsabilidade |
|---|---|
| `pipeline.py` | Engine central: VAD → buffer → flush → ASR → fila de resultados |
| `translator.py` | GPUTranslator: Argos (local) + Google (fallback cloud/contextual) |
| `opus_translator.py` | OpusMTTranslator: OPUS-MT via CTranslate2, fast lane ~40ms |
| `audio_io.py` | Setup de streams WASAPI via pyaudiowpatch |
| `audio_utils.py` | DSP Python: mono, resample, RMS, is_speech |
| `latency_profile.py` | Perfis nomeados de tuning (fast/balanced/ultra/system_en) |
| `source_profiles.py` | Overrides por fonte (mic tem mais padding; system_en tem flush agressivo) |
| `context_store.py` | Contexto pessoal: glossário, correções, regras por domínio |
| `text_processing.py` | Contrato textual: TextEnvelope, TextProcessor, cache key determinístico |
| `display.py` | UI Rich: tabelas live/stable, status de runtime, telemetria por pipe |
| `cache.py` | LRU thread-safe; chave por texto + par de idiomas + contexto |
| `audio_rs.py` | Shim: tenta `from .runtime_rs import AudioSegment`, cai no dataclass Python |

### Rust — `runtime-rs/`

| Crate | Responsabilidade |
|---|---|
| `rtxlator-audio` | Captura WASAPI event-driven (mic e loopback), thread dedicada com sinal de readiness antes do loop |
| `rtxlator-dsp` | `to_mono`, `apply_gain`, `resample_to_16k` (rubato), `Vad1` (WebRTC VAD), `Segmenter` (480-sample frames) |
| `rtxlator-sched` | `SegmentQueue` (prioridade Final > Partial, drain por deadline), `audio_ring` (SPSC lock-free via rtrb) |
| `rtxlator-ffi` | `AudioSegment` PyClass com `#[new]`, `duration_ms()`, `__repr__` — exportado como `runtime_rs.pyd` |

---

## Fluxo de dados

```
┌────────────────────────────────────────────────────────────────────┐
│ Thread de captura (WASAPI)                                         │
│                                                                    │
│  pyaudiowpatch callback → f32 samples                             │
│       │                                                            │
│  [is_speech / RMS gate]  ←── audio_utils.py                       │
│       │                                                            │
│  AudioPipeline.feed()   ←── pipeline.py                           │
│       │                                                            │
│  [buffer acumulado]                                                │
│       │                                                            │
│  [flush parcial / flush final]  ←── latency_profile + source_profile│
└────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────────────┐
│ Thread de ASR (GPU)                                                │
│                                                                    │
│  faster-whisper.transcribe()   ←── Whisper int8_float16 na GPU    │
│       │                                                            │
│  language lock: _locked_lang                                       │
│       │                                                            │
│  Result(text, lang, partial/final)                                 │
└────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────────────┐
│ Thread de tradução                                                  │
│                                                                    │
│  TranslationCache.get()                                            │
│       │ miss                                                        │
│  OpusMTTranslator.translate()   ←── fast lane OPUS-MT CT2         │
│       │ fallback                                                    │
│  GPUTranslator.translate()      ←── Argos → Google                │
│       │                                                            │
│  Result(translation, provider, latency_ms)                        │
└────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────────────┐
│ Thread de UI (Rich)                                                 │
│  display.build_runtime_status()  ←── telemetria por pipe           │
│  display.render_result_line()    ←── linha de resultado formatada  │
└────────────────────────────────────────────────────────────────────┘
```

---

## Decisões de design

### Language lock

Autodetect contínuo em streaming custa tempo e cria instabilidade em áudio difícil. O pipeline detecta na primeira frase final, trava `_locked_lang` por fonte e só reabre se houver evidência forte de troca. Elimina ~20ms de overhead por segmento.

### Two-stage VAD

- **Estágio 1 (Rust/Python):** WebRTC VAD em CPU — descarta silêncio antes de enfileirar. Custo: microssegundos.
- **Estágio 2 (Whisper):** `vad_filter=True` no faster-whisper — confirmação de fala real antes do ASR.

### OPUS-MT como fast lane

OPUS-MT convertido para CTranslate2 usa o mesmo runtime do Whisper, sem HTTP, sem dependência externa. Latência p95 < 50ms. Argos fica como fallback para pares sem modelo OPUS-MT. Google só entra no modo contextual/cloud.

### Fila de prioridade

`Final` tem prioridade absoluta sobre `Partial`. Segmentos com deadline expirado são drenados antes de processar novos. Isso garante que backlog velho nunca atrasa uma frase nova.

### Rust: captura com readiness real

`capture_worker` em Rust inicializa o cliente WASAPI e envia o sinal de readiness **antes** de entrar no loop de captura. `start()` em Python retorna assim que o dispositivo está configurado e rodando — não quando o stream termina.

### Hybrid Python + Rust

Python permanece correto para orquestração, cache, UI e integração com CTranslate2. Rust resolve os problemas que Python tem no limite: jitter de captura (~5ms de sleep no polling vs event-driven), segmentação lock-free sem GIL, scheduling determinístico de segmentos.

---

## Próximos passos

1. **Ligar o runtime Rust ao pipeline principal** — hoje `AudioSegment` Rust existe mas o pipeline ainda usa `pyaudiowpatch`. O próximo passo é `AudioPipeline` consumir da fila Rust (`SegmentQueue`) em vez do callback Python.

2. **Distil-Whisper para perfil `system_en_fast`** — modelo 4x mais rápido para áudio do sistema em inglês; manter `large-v3-turbo` como default multilíngue.

3. **Overlay/janela flutuante** — exibir tradução sobre a janela ativa, sem terminal visível.

4. **Benchmark das fases** — medir `first_partial_ms p95`, `translate_ms p95`, `drop_rate` com corpus real para validar os critérios do RFC-001.
