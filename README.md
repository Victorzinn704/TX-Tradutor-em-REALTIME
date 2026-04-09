# Realtime Translator

Tradutor de áudio em tempo real para Windows 11, com ASR local na GPU, tradução offline e runtime híbrido Python + Rust.

---

## Visão geral

```
[MIC / LOOPBACK WASAPI]
        │
  [WebRTC VAD]      ← pre-gate em CPU, descarta silêncio antes da GPU
        │
  [Silero VAD]      ← confirmação via faster-whisper vad_filter
        │
  [Whisper GPU]     ← faster-whisper / CTranslate2, int8_float16
        │
  [Language Lock]   ← detecta na 1ª frase, trava por sessão/fonte
        │
  [OPUS-MT CT2]     ← fast lane local, ~40ms
        │
  [Argos Translate] ← fallback para pares sem modelo OPUS-MT
        │
  [Google Translate]← apenas modo contextual/cloud
        │
  [Rich Terminal UI]
```

**Hardware alvo:** RTX 5060 Ti 8 GB, Windows 11, Python 3.11+

---

## Funcionalidades

| Funcionalidade | Estado |
|---|---|
| Captura de microfone (WASAPI) | ✅ |
| Captura de áudio do sistema (loopback WASAPI) | ✅ |
| ASR com faster-whisper na GPU | ✅ |
| Language lock por fonte/sessão | ✅ |
| Tradução local com OPUS-MT/CTranslate2 | ✅ |
| Fallback Argos Translate | ✅ |
| Fallback Google Translate (contextual) | ✅ |
| Contexto pessoal (glossário, correções, regras) | ✅ |
| Telemetria de latência em tempo real | ✅ |
| Perfis de latência por fonte (`mic`, `system`, `system_en`) | ✅ |
| Ponte de texto (tradução manual) | ✅ |
| Runtime Rust (captura + DSP + scheduler) | ✅ |

---

## Instalação

```bat
instalar.bat
```

O script cria o `.venv`, instala as dependências Python e baixa os modelos Argos padrão.

Para compilar o runtime Rust (opcional, melhora jitter e uso de CPU):

```bat
compilar_rust.bat
```

Requer Rust 1.70+ (o script instala via rustup se necessário). Gera `rtxlator/runtime_rs.pyd`.

---

## Uso rápido

```bat
rodar.bat
```

O menu interativo permite configurar idiomas, modelo, perfil e fontes de áudio sem tocar no código.

### CLI direta

```bat
python realtime_translator.py --source pt --target en --model base --latency-profile ultra --ui-mode stable
```

Flags principais:

| Flag | Padrão | Descrição |
|---|---|---|
| `--source` | `auto` | Idioma de origem (`pt`, `en`, `es`, `auto`) |
| `--target` | `pt` | Idioma de destino |
| `--model` | `base` | Modelo Whisper (`tiny`, `base`, `small`, `medium`, `large-v3`) |
| `--latency-profile` | `balanced` | Perfil de latência (`fast`, `balanced`, `ultra`) |
| `--ui-mode` | `stable` | Modo de UI (`stable`, `live`) |
| `--interpretation-mode` | `hybrid` | Modo de tradução (`fast`, `hybrid`, `contextual`) |
| `--mic-id` | auto | Índice do microfone |
| `--spk-id` | auto | Índice do dispositivo de saída (loopback) |
| `--partial-flush-s` | perfil | Override do flush parcial em segundos |
| `--list-devices` | — | Lista dispositivos e encerra |

---

## Modelos Whisper

| Modelo | Velocidade | Qualidade | Uso recomendado |
|---|---|---|---|
| `tiny` | ★★★★★ | ★☆☆☆☆ | Testes, hardware fraco |
| `base` | ★★★★☆ | ★★★☆☆ | Uso diário — melhor equilíbrio |
| `small` | ★★★☆☆ | ★★★★☆ | Frases difíceis ou com sotaque |
| `medium` | ★★☆☆☆ | ★★★★☆ | Qualidade alta com latência maior |
| `large-v3` | ★☆☆☆☆ | ★★★★★ | Máxima qualidade, uso offline |

---

## Perfis de latência

| Perfil | Flush (s) | Silêncio (chunks) | Uso recomendado |
|---|---|---|---|
| `fast` | 1.0 | 1 | Menor latência possível |
| `balanced` | 1.2 | 2 | Padrão — vídeo/chamada |
| `ultra` | 1.35 | 3 | Estabilidade máxima em mic |
| `system_en` | 1.0 | 2 | Áudio do sistema em inglês |

---

## Modos de interpretação

- **`fast`** — Argos local direto. Menor latência, mais literal.
- **`hybrid`** — Parcial rápida via Argos; final tenta leitura contextual. Melhor padrão geral.
- **`contextual`** — Prioriza naturalidade; aceita mais latência no resultado final.

---

## Telemetria

O terminal exibe por fonte ativa:

```
MIC  pt(locked)  partial=180ms  qwait=12ms  drop=0.3%
SPK  en(locked)  partial=95ms
```

| Métrica | Significado |
|---|---|
| `lang=xx(locked)` | Idioma travado após 1ª frase final |
| `partial=Xms` | Tempo da detecção de fala até o 1º parcial |
| `qwait=Xms` | Tempo do segmento na fila até o ASR iniciar |
| `drop=X%` | Taxa de chunks descartados por backlog |
| `fallback=X%` | Taxa de traduções que saíram do hot path |

Linha de resultado:

```
[12:34:56] MIC PT 148ms (asr 112 / tr 9) argos
```

---

## Contexto pessoal

O arquivo `user_language_context.json` contém quatro camadas de personalização:

```json
{
  "glossary": { "caixa": "cash register", "comanda": "order ticket" },
  "correction_memory": { "fechar a conta": "close the check" },
  "preferred_translations": {},
  "context_rules": []
}
```

Para editar de forma guiada:

```bat
python gerenciar_contexto.py
```

Ou pelo menu `rodar.bat → 6) Gerenciar contexto pessoal`.

---

## Ponte de texto

Tradução manual de mensagens digitadas:

```bat
python texto_bridge.py --source pt --target en
```

Ou `rodar.bat → 7) Ponte de texto`.

Sintaxe rápida no prompt:
- `> texto` → mensagem de saída (traduz para o idioma alvo)
- `< texto` → mensagem recebida (traduz para o idioma origem)

---

## Runtime Rust

O workspace `runtime-rs/` é compilado como extensão Python (`runtime_rs.pyd`) e ativado automaticamente se presente.

```
runtime-rs/
├── audio/   rtxlator-audio   — captura WASAPI (mic + loopback), event-driven
├── dsp/     rtxlator-dsp     — mono, gain, resample 16kHz, WebRTC VAD, segmenter
├── sched/   rtxlator-sched   — fila de prioridade partial/final, deadlines, ring buffer SPSC
└── ffi/     rtxlator-ffi     — PyO3 bridge → AudioSegment Python
```

Quando compilado, `RUST_RUNTIME=True` em `rtxlator/audio_rs.py` e `AudioSegment` nativo substitui o dataclass Python.

Para verificar:

```python
from rtxlator.audio_rs import RUST_RUNTIME
print(RUST_RUNTIME)  # True se compilado
```

Notas de build:
- Python 3.14: definir `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` antes do `cargo build` (o `compilar_rust.bat` já faz isso).
- Requer MSVC toolchain: `rustup target add x86_64-pc-windows-msvc`.

---

## Estrutura do projeto

```
realtime_translator/
│
├── realtime_translator.py   ← entry point principal
├── diagnostico.py           ← checa CUDA, dispositivos, dependências
├── gerenciar_contexto.py    ← editor guiado do contexto pessoal
├── texto_bridge.py          ← ponte de tradução manual
│
├── rodar.bat                ← launcher interativo
├── instalar.bat             ← setup do ambiente + modelos
├── compilar_rust.bat        ← build do workspace Rust
├── diagnostico.bat          ← atalho para diagnostico.py
├── listar_dispositivos.bat  ← lista dispositivos de áudio
│
├── rtxlator/                ← pacote Python principal
│   ├── audio_io.py          ← setup de streams WASAPI
│   ├── audio_rs.py          ← shim Rust/Python para AudioSegment
│   ├── audio_utils.py       ← DSP: mono, resample, RMS, VAD
│   ├── cache.py             ← LRU cache thread-safe de traduções
│   ├── constants.py         ← constantes globais, console Rich
│   ├── context_store.py     ← contexto pessoal persistente (JSON)
│   ├── cuda_setup.py        ← preload de DLLs NVIDIA no Windows
│   ├── device.py            ← detecção GPU/CPU e dispositivos de áudio
│   ├── display.py           ← UI Rich: tabelas, status, telemetria
│   ├── latency_profile.py   ← perfis de latência nomeados
│   ├── opus_translator.py   ← OPUS-MT via CTranslate2 (fast lane)
│   ├── pipeline.py          ← engine: VAD → buffer → ASR → resultado
│   ├── result.py            ← dataclass Result com métricas
│   ├── source_profiles.py   ← tuning por fonte (mic/system/system_en)
│   ├── text_processing.py   ← TextEnvelope, TextProcessor, cache key
│   ├── text_bridge.py       ← base da ponte de texto
│   └── translator.py        ← GPUTranslator (Argos + Google fallback)
│
├── runtime-rs/              ← workspace Rust (opcional)
│   ├── audio/               ← captura WASAPI nativa
│   ├── dsp/                 ← processamento de sinal (VAD, resample, gain)
│   ├── sched/               ← scheduler com fila de prioridade
│   └── ffi/                 ← bridge PyO3 → runtime_rs.pyd
│
├── tests/
│   └── test_opus_translator.py
├── test_realtime_translator.py
├── test_context_manager.py
├── test_source_profiles.py
├── test_text_processing.py
│
├── docs/
│   └── RFC-001-performance-roadmap.md
│
├── models/                  ← modelos baixados (Argos + HF cache)
└── user_language_context.json
```

---

## Regras de desempenho

- Backlog velho é pior que perder um chunk — o pipeline descarta.
- `partial` nunca bloqueia `final`.
- Flush parcial usa cópia do buffer para não competir com o flush final.
- Fallback remoto (Google) nunca entra no hot path parcial.
- Language lock elimina custo de autodetect contínuo após a 1ª frase.
- Tradução cacheada é identificada no output (`cache`).

---

## Diagnóstico

```bat
diagnostico.bat
```

Verifica CUDA, dispositivos de áudio, modelos instalados e status do runtime Rust.

---

## Testes

```bat
.venv\Scripts\python.exe -m pytest
```

22 testes Python. Para os testes Rust:

```bat
cd runtime-rs
cargo test
```

13 testes no crate `dsp`, 7 no crate `audio`.

---

## Roadmap

Ver [`docs/RFC-001-performance-roadmap.md`](docs/RFC-001-performance-roadmap.md).

Todas as 6 fases concluídas. O RFC está em estado de benchmark — medir os critérios com corpus real.

Próximas etapas naturais:
- Ligar o runtime Rust ao pipeline principal (hoje `AudioSegment` Rust está disponível mas o pipeline ainda usa `pyaudiowpatch`)
- Overlay/janela flutuante de tradução
