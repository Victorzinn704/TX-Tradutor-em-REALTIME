# RFC-001 — Performance Roadmap do Realtime Translator

## 1. Contexto

O `realtime_translator` é um projeto local de tradução de áudio em tempo real para `Windows 11`, pensado para operar em desktop com `RTX 5060 Ti 8GB` e `Python 3.11+`.

### Stack atual

- `faster-whisper` sobre `ctranslate2` para ASR
- `argostranslate` para tradução local
- `deep-translator` como fallback cloud/contextual
- `pyaudiowpatch` para captura `WASAPI` e `loopback`
- terminal com `rich`

### Problema atual

O projeto já está em um patamar bom para um runtime local, mas a latência end-to-end ainda depende fortemente de:

- endpointing
- política de fila
- autodetect de idioma
- variação do motor de tradução
- diferença de workload entre microfone e áudio do sistema

Em outras palavras: o gargalo restante está mais na disciplina de streaming e no motor de MT do que na linguagem Python em si.

---

## 2. Arquitetura Alvo

```text
[MIC / SYSTEM LOOPBACK]
        |
   [WebRTC VAD]  <-- pre-gate CPU, descarta silêncio antes da GPU
        |
   [Silero VAD]  <-- confirmação, via faster-whisper vad_filter
        |
   [Whisper large-v3-turbo / Distil-Whisper EN]  <-- ASR central
        |
   [Language Lock]  <-- detecta na primeira frase, trava por sessão
        |
   [OPUS-MT CTranslate2]  <-- hot path <40ms
        |
   [Argos fallback]  <-- pares sem modelo OPUS-MT
        |
   [Google Translate]  <-- apenas modo contextual/cloud
        |
   [Rich Terminal Display]
```

### Princípios da arquitetura alvo

- `partial` nunca bloqueia `final`
- `final` tem prioridade absoluta
- `remote fallback` nunca entra no hot path parcial
- `language lock` reduz custo e instabilidade de autodetect contínuo
- o caminho rápido precisa ser totalmente local

---

## 3. Fases de Execução

| Fase | O que muda | Critério de conclusão | Status |
|---|---|---|---|
| 1 | `Language lock` + métricas (`first_partial_ms`, `queue_wait_ms`, `drop_rate`, `fallback_rate`) | `drop_rate < 2%` e `first_partial_ms p95 < 400ms` | ✅ Concluída |
| 2 | `Distil-Whisper` para perfil `system_en_fast` | `first_partial_ms p95 < 200ms` para EN | ✅ Concluída |
| 3 | `OPUS-MT/CTranslate2` como fast lane | `translate_ms p95 < 50ms` | ✅ Concluída |
| 4 | `Two-stage VAD` (WebRTC pre-gate + Silero confirmação) | `drop_rate < 0.5%` | ✅ Concluída |
| 5 | `ASR central scheduler` com fila de prioridade `partial/final` | filas previsíveis e sem bloqueio de `final` | ✅ Concluída (Rust) |
| 6 | `Rust` para captura de áudio + DSP + supervisor | revisão após benchmark das fases 1–5 | ✅ Concluída — pendente integração ao pipeline principal |

---

## 4. Decisões Técnicas e Justificativas

### 4.1 Por que NÃO reescrever tudo em Rust agora

O projeto atual já concentra o hot path pesado em bibliotecas nativas/CUDA:

- `ctranslate2`
- `faster-whisper`
- runtime local de MT

O Python hoje está principalmente na orquestração:

- captura
- fila
- segmentação
- UI
- automação

Reescrever tudo em Rust neste momento aumentaria custo, risco e tempo de entrega sem atacar primeiro os gargalos mais prováveis:

- endpointing
- política de flush
- language lock
- VAD
- fast lane de tradução

### 4.2 Por que OPUS-MT/CTranslate2 e não Seamless/NLLB para realtime

`OPUS-MT` convertido para `CTranslate2` é uma escolha melhor para o caminho rápido porque:

- usa o mesmo runtime de inferência do ASR atual
- permite comportamento previsível por par de idiomas
- tende a ser mais leve e controlável no desktop local
- funciona melhor como fast lane especializada

`Seamless` e `NLLB` são interessantes, mas não devem ser o default do realtime local neste hardware porque:

- aumentam custo de inferência
- ampliam risco de latência
- trazem complexidade maior para uso sempre ativo

### 4.3 Por que language lock e não autodetect contínuo

Autodetect contínuo em streaming custa:

- tempo
- estabilidade
- previsibilidade em áudio difícil

O caminho preferido é:

1. detectar nas primeiras frases;
2. travar por fonte/sessão;
3. só reabrir a detecção quando houver evidência forte de troca de idioma.

### 4.4 Por que Distil-Whisper apenas para EN-only system audio

`Distil-Whisper` encaixa muito bem em:

- vídeo em inglês
- chamada em inglês
- live/stream com áudio do sistema

Ele não precisa ser o default multilíngue global. O melhor desenho é:

- `whisper-large-v3-turbo` como default multilíngue
- `Distil-Whisper` como perfil especializado `system_en_fast`

---

## 5. Backlog de Implementação

### Fase 1

- `[P: média]` adicionar `language lock` por fonte
- `[P: média]` expor `first_partial_ms`, `final_ms`, `queue_wait_ms`, `drop_rate`, `fallback_rate`
- `[P: baixa]` separar telemetria de `partial` e `final`
- `[P: média]` impedir autodetect redundante em sessão estável

### Fase 2

- `[P: média]` adicionar perfil `system_en_fast`
- `[P: média]` integrar benchmark A/B entre `base`, `small`, `large-v3-turbo` e `Distil-Whisper`
- `[P: baixa]` ajustar launcher/presets para perfil EN-only

### Fase 3

- `[P: alta]` adicionar `OpusMTTranslator`
- `[P: média]` integrar fast lane OPUS-MT no runtime principal
- `[P: média]` rebaixar `Argos` para fallback local
- `[P: baixa]` manter `Google` apenas como lane contextual/final

### Fase 4

- `[P: alta]` integrar `WebRTC VAD` como pre-gate
- `[P: média]` manter `Silero VAD` como confirmação
- `[P: média]` recalibrar flush e silêncio com duas camadas de VAD

### Fase 5

- `[P: alta]` criar `ASR scheduler` central
- `[P: alta]` implementar prioridade explícita de `final` sobre `partial`
- `[P: média]` limitar filas por deadline e budget

### Fase 6

- `[P: alta]` avaliar extração de captura/scheduler para Rust
- `[P: média]` estudar supervisor nativo, empacotamento e redução de jitter
- `[P: baixa]` manter `CTranslate2` como engine de inferência mesmo com runtime híbrido

---

## 6. Critérios de Benchmark

As fases acima devem ser medidas com corpus real do usuário, em no mínimo estes indicadores:

- `first_partial_ms`
- `final_after_endpoint_ms`
- `asr_ms`
- `translate_ms`
- `queue_wait_ms`
- `drop_rate`
- `fallback_rate`

### Alvos iniciais

- `first_partial_ms p95 < 400ms` no cenário geral
- `first_partial_ms p95 < 200ms` em `system_en_fast`
- `translate_ms p95 < 50ms` na fast lane OPUS-MT
- `drop_rate < 0.5%` após two-stage VAD

---

## 7. Referências

- CTranslate2 docs: https://opennmt.net/CTranslate2/parallel.html
- faster-whisper: https://github.com/SYSTRAN/faster-whisper
- whisper-large-v3-turbo: https://huggingface.co/openai/whisper-large-v3-turbo
- Distil-Whisper: https://huggingface.co/distil-whisper/distil-large-v3
- OPUS-MT Helsinki-NLP: https://huggingface.co/Helsinki-NLP
- Silero VAD: https://github.com/snakers4/silero-vad
- WebRTC VAD (py-webrtcvad): https://github.com/wiseman/py-webrtcvad
