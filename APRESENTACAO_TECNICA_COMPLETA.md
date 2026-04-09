# Apresentação Técnica Completa — Realtime Translator

## 1. Visão executiva

O `Realtime Translator` é um projeto local para Windows focado em tradução de áudio e texto em tempo quase real, com prioridade explícita para três objetivos ao mesmo tempo:

1. baixa latência percebida;
2. boa inteligibilidade na transcrição e na tradução;
3. previsibilidade operacional para uso diário em microfone, áudio do sistema, vídeo, reunião e texto.

Ele não é uma aplicação web, não depende de backend próprio e não roda como serviço distribuído. A “infra” dele é local: ambiente Python, GPU NVIDIA, dispositivo(s) de áudio, modelos locais e launchers Windows. O coração do sistema é um runtime Python que coordena captura de áudio, segmentação de fala, ASR com Whisper acelerado por GPU, tradução local com Argos Translate e, quando necessário, fallback remoto via Google Translate.

Hoje o projeto também já começa a sair do formato de “script único” e virar um mini-produto com:

- módulo compartilhado de contexto pessoal;
- contrato textual reutilizável;
- ponte de texto para entrada e saída manual;
- perfis diferentes para microfone e loopback;
- testes automatizados;
- documentação operacional;
- launchers e instalador padronizados.

---

## 2. O que o projeto faz

### 2.1 Entradas suportadas

O projeto consegue consumir quatro classes de entrada:

- **microfone**: fala direta do usuário;
- **áudio do sistema**: loopback WASAPI para vídeos, chamadas, lives e reuniões;
- **texto de saída**: o texto que o usuário quer enviar, para traduzir antes do envio;
- **texto de entrada**: o texto que o usuário recebe, para traduzir na chegada.

### 2.2 Saídas produzidas

As saídas principais hoje são:

- transcrição detectada do áudio;
- tradução final para o idioma-alvo;
- parciais especulativas para reduzir latência percebida;
- telemetria por frase (`total`, `asr`, `tr`, `cache`, `provider`);
- UI de terminal em modo `stable` ou `live`;
- saída traduzida manual na ponte de texto.

### 2.3 Modos de uso suportados

Os fluxos mais maduros hoje são:

- `PT -> EN` pelo microfone;
- `EN -> PT` pelo microfone;
- vídeo/chamada em inglês via áudio do sistema;
- vídeo/chamada em espanhol via áudio do sistema;
- ponte de texto para mensagens manuais.

---

## 3. Stack e tecnologias usadas

## 3.1 Linguagem e runtime

- **Python 3.11+**
- ambiente virtual local em `.venv/`
- execução local via `.bat`, `PowerShell` e `python`

A escolha por Python continua correta para este projeto porque o hot path pesado não está em Python puro; ele está nas bibliotecas nativas/CUDA. O Python está orquestrando filas, UI, CLI, automação, cache e integração.

## 3.2 Bibliotecas principais

Arquivo base: `requirements.txt`

### Captura e áudio
- `pyaudiowpatch`:
  - wrapper PyAudio/WASAPI com suporte útil para loopback no Windows.
  - É a ponte entre a aplicação e os dispositivos de áudio.

### ASR / transcrição
- `faster-whisper`:
  - implementação eficiente do Whisper.
  - Faz a transcrição do áudio para texto.
- `ctranslate2`:
  - backend de inferência usado pelo `faster-whisper`.
  - É a parte central da aceleração por GPU.

### Tradução
- `argostranslate`:
  - MT local/offline.
  - Usa modelos instalados em `models/argos`.
- `deep-translator`:
  - usado para `GoogleTranslator` como fallback remoto.
  - Entra principalmente quando o par de idiomas local não está pronto ou quando o modo contextual final pede algo mais natural.

### Processamento numérico
- `numpy`:
  - buffers e manipulação de áudio.
- `scipy`:
  - resampling para `16kHz`.

### UI de terminal
- `rich`:
  - UI do terminal, tabela live, status, estilo e console estável.

### Tokenização/modelos auxiliares
- `sentencepiece`:
  - suporte dos modelos de tradução.

### CUDA no Windows
- `nvidia-cublas-cu12`
- `nvidia-cudnn-cu12`
- `nvidia-cuda-runtime-cu12`

Esses pacotes existem para garantir que as DLLs CUDA fiquem disponíveis dentro do ambiente Python, sem depender só do PATH global do Windows.

---

## 4. Infraestrutura real do projeto

Este projeto não possui backend, banco, filas distribuídas nem servidor web. A infraestrutura real é local e composta por:

- Windows + `cmd`/PowerShell;
- Python + `.venv`;
- GPU NVIDIA (idealmente CUDA disponível para `ctranslate2`);
- dispositivos de áudio do sistema;
- cache local de modelos;
- arquivos JSON locais para contexto pessoal;
- launchers `.bat` e atalhos `.lnk`.

### 4.1 Dependências de máquina

Para operar bem, a máquina precisa de:

- driver NVIDIA funcional (`nvidia-smi` saudável);
- suporte WASAPI/loopback para o endpoint de áudio;
- Python funcional;
- ambiente virtual criado;
- pacotes Python instalados;
- modelos Argos e Whisper disponíveis ou baixáveis.

### 4.2 Infra de modelos locais

A pasta `models/` guarda o estado pesado do projeto.

#### `models/argos/`
Contém os pacotes locais de tradução instalados pelo Argos, hoje com pares observados como:

- `translate-en_pt-*`
- `translate-es_pt-*`
- `translate-pt_en-*`

Cada pacote inclui:

- `metadata.json`
- `sentencepiece.model`
- `model/` com arquivos de inferência
- `stanza/` com recursos auxiliares por idioma

#### `models/hf/`
Contém o cache do Hugging Face usado pelos modelos Whisper, incluindo snapshots como:

- `models--Systran--faster-whisper-base`
- `models--Systran--faster-whisper-small`

Isso reduz custo de download e warm-up em execuções seguintes.

---

## 5. Arquitetura de alto nível

A arquitetura atual pode ser lida em cinco camadas:

1. **entrada/captura**;
2. **segmentação e orquestração de áudio**;
3. **ASR**;
4. **resolução textual e tradução**;
5. **UI/CLI e ferramentas operacionais**.

### 5.1 Camada de entrada

Responsável por:

- descobrir microfone;
- descobrir loopback de saída;
- abrir streams com formato viável;
- alimentar o pipeline com chunks de áudio.

Funções-chave em `realtime_translator.py`:

- `find_redragon_devices`
- `list_all_devices`
- `select_mic_info`
- `select_loopback_info`
- `_pick_input_format`
- `setup_mic`
- `setup_loopback`
- `make_stream_callback`

### 5.2 Camada de segmentação e controle de latência

Responsável por:

- montar buffers por fonte;
- decidir quando há fala versus silêncio;
- emitir flush parcial;
- emitir flush final;
- evitar backlog velho;
- controlar fila e descarte.

Objetos-chave:

- `LatencyProfile`
- `LATENCY_PROFILES`
- `AudioPipeline`

### 5.3 Camada ASR

Responsável por:

- transcrever áudio em texto;
- detectar idioma quando `source` está em auto;
- usar prompt curto com contexto recente;
- rodar em GPU quando disponível.

Pontos-chave:

- `load_whisper_model`
- `warm_up_models`
- `AudioPipeline._flush_job`
- `detect_device`

### 5.4 Camada textual

Responsável por:

- normalizar entrada textual;
- consultar memória pessoal;
- aplicar glossário;
- decidir cache x tradução x fallback;
- manter contratos consistentes entre áudio e texto.

Arquivos-chave:

- `rtxlator/context_store.py`
- `rtxlator/text_processing.py`
- `rtxlator/text_bridge.py`

### 5.5 Camada de apresentação/uso

Responsável por:

- UI de terminal;
- launchers;
- diagnósticos;
- instalador;
- ponte de texto;
- gerenciador de contexto.

Arquivos-chave:

- `rodar.bat`
- `diagnostico.py`
- `gerenciar_contexto.py`
- `texto_bridge.py`
- `criar_atalhos.ps1`

---

## 6. Fluxo completo do runtime de áudio

## 6.1 Inicialização

O fluxo de `realtime_translator.py` começa com:

1. correção de DLLs NVIDIA no Windows;
2. configuração de cache local do HF;
3. parse dos argumentos CLI;
4. resolução do perfil de latência;
5. inicialização do `PyAudio`;
6. descoberta de fontes de entrada;
7. detecção de device (`cuda` ou `cpu`);
8. carregamento de uma ou duas instâncias do Whisper;
9. warm-up do Whisper/CUDA;
10. criação do cache, tradutor, `TextProcessor`, estado de runtime e pipelines;
11. abertura dos streams e início do loop de UI.

## 6.2 Captura de áudio

Cada stream do PyAudio chama um callback leve que faz apenas:

- copiar o buffer float32 recebido;
- empurrar o chunk para a fila do `AudioPipeline` correspondente.

Isso é importante: o callback não tenta transcrever nem traduzir. Ele delega para a thread do pipeline.

## 6.3 Normalização do chunk

Dentro de `AudioPipeline._run`, cada chunk passa por:

- `to_mono`
- `to_16k`
- `is_speech`

Essa sequência faz o Whisper receber o formato esperado.

## 6.4 Lógica de endpointing

O pipeline mantém:

- `buffer`
- `buffer_samples`
- `silence_streak`
- `in_speech`

Com isso, ele decide entre:

- continuar acumulando fala;
- disparar parcial quando a fala continua longa;
- disparar final quando há silêncio suficiente;
- forçar flush se o buffer ficar grande demais.

## 6.5 Flush parcial e final

Quando decide flush, o pipeline agenda o trabalho com `_schedule_flush`.

Regras importantes:

- existe um worker ASR serial por fonte (`_asr_pool max_workers=1`);
- `final` tem prioridade sobre `partial`;
- só a parcial mais recente fica pendente;
- backlog velho é descartado antes de contaminar a experiência.

## 6.6 ASR

`_flush_job` faz:

- preparo final de áudio com `prepare_audio_for_asr`
- construção de `initial_prompt` curto com `self._context_window`
- chamada a `WhisperModel.transcribe(...)`

Parâmetros relevantes:

- `beam_size=1`
- `best_of=1`
- `temperature=0`
- `without_timestamps`
- `vad_filter` controlado pelo perfil

## 6.7 Resolução textual

Depois da transcrição, o pipeline envia a frase para `_translate_and_save`, que monta um `TextEnvelope` e delega para `TextProcessor.resolve(...)`.

O `TextProcessor` decide:

- se a frase sobe como identidade;
- se vai para cache;
- se vai para Argos;
- se vai para Google fallback;
- se usa contexto ou não;
- se `partial` pode ou não cair em remoto.

## 6.8 Atualização de UI

O resultado final vira um objeto `Result`, que pode ir para:

- `results` (deque de resultados finais);
- `partials` (mapa de parciais por fonte);
- `ui_queue` (modo estável);
- `runtime_state` (telemetria e versão visual).

O terminal então renderiza:

- tabela `live`, ou
- linhas estáveis em `stable`.

---

## 7. Arquivo por arquivo — papel de cada parte do projeto

## 7.1 Raiz do projeto

### `realtime_translator.py`
É o runtime principal. Hoje concentra:

- bootstrap do Windows/CUDA;
- constantes e perfis de latência;
- detecção de hardware;
- descoberta de dispositivos;
- utilitários de áudio;
- cache simples de tradução;
- adaptador do tradutor GPU/local/fallback;
- modelo de resultado;
- pipeline de áudio completo;
- renderização de console;
- CLI principal.

É o arquivo mais importante e também o principal candidato a futura divisão modular.

### `rodar.bat`
Launcher principal de operação.

Responsabilidades:

- localizar a pasta do projeto via `%~dp0`;
- ativar `.venv`;
- oferecer menu rápido;
- aplicar presets de uso;
- montar argumentos para o runtime;
- chamar `python realtime_translator.py ...`.

Hoje ele também abre:

- gerenciador de contexto;
- ponte de texto.

### `instalar.bat`
Instalador local do projeto.

Responsabilidades:

- verificar Python;
- criar `.venv`;
- instalar `requirements.txt`;
- instalar runtimes CUDA via pip;
- pré-baixar alguns pacotes Argos;
- validar CUDA com `ctranslate2`.

### `diagnostico.py`
Ferramenta de auditoria rápida da máquina.

Responsabilidades:

- checar `ctranslate2` e CUDA;
- consultar `nvidia-smi`;
- listar dispositivos de áudio;
- destacar RedDragon;
- listar endpoints loopback;
- orientar uso de `--spk-id` e perfil `balanced` em chamadas.

### `diagnostico.bat`
Wrapper simples para ativar a venv e rodar `diagnostico.py`.

### `listar_dispositivos.bat`
Wrapper simples para chamar `realtime_translator.py --list-devices`.

### `gerenciar_contexto.py`
CLI guiado para manter o contexto pessoal.

Responsabilidades:

- resumo do contexto;
- cadastro de correções completas;
- cadastro de glossário;
- frases preferidas;
- correções finais;
- normalizações do jeito de falar;
- regras contextuais.

### `texto_bridge.py`
Wrapper fino para a ponte de texto. Só delega para `rtxlator.text_bridge.main()`.

### `criar_atalhos.ps1`
Automação de atalhos Windows.

Responsabilidades:

- criar `.lnk` para launcher, diagnóstico, listagem e instalador;
- apontar `TargetPath`, `WorkingDirectory`, `IconLocation`, `Description`.

### `README.md`
Guia operacional do projeto.

### `ARCHITECTURE.md`
Documento de direção técnica enxuto. Resume a decisão arquitetural atual.

### `pyproject.toml`
Semente de organização do projeto Python.

Hoje declara:

- nome;
- versão;
- descrição;
- Python mínimo;
- defaults operacionais do tradutor.

### `requirements.txt`
Fonte única de dependências do runtime/instalação.

### `.gitignore`
Exclui:

- `.venv/`
- `__pycache__/`
- `*.pyc`
- `*.bak`
- `.runtime/`
- `models/`
- `.tmp_*`
- `user_language_context.json`

Ou seja: código entra no Git; caches, modelos e contexto pessoal não.

### `user_language_context.json`
Base viva de personalização do usuário.

É um arquivo de dados, não de código. Hoje contém:

- `source_normalization`
- `correction_memory`
- `preferred_translations`
- `glossary`
- `target_replacements`
- `context_rules`

### `.tmp_*.log/.err`
Arquivos temporários de smoke test e depuração local. Não fazem parte da arquitetura oficial; são artefatos de validação.

## 7.2 Pasta `rtxlator/`

Essa pasta é a primeira extração real de domínio do projeto.

### `rtxlator/__init__.py`
Exporta a API compartilhada do pacote.

### `rtxlator/context_store.py`
Fonte única de verdade do contexto pessoal.

Responsabilidades:

- criar o JSON padrão se ele não existir;
- corrigir estrutura quebrada;
- salvar com escrita atômica;
- fazer backup antes de salvar;
- normalizar frases de entrada;
- consultar memória de correções;
- proteger termos do glossário com placeholders;
- aplicar substituições finais na saída;
- manter regras contextuais.

É um dos arquivos mais importantes do ponto de vista de “inteligência prática” sem destruir latência.

### `rtxlator/source_profiles.py`
Especializa o pipeline por tipo de fonte.

Hoje diferencia `mic` e `system` em dois pontos:

1. tuning de latência/VAD;
2. ganho/normalização de áudio.

Isso é especialmente importante para loopback e vídeo chamada.

### `rtxlator/text_processing.py`
Cria um contrato comum para qualquer fluxo textual.

Entidades centrais:

- `TextEnvelope`: o que chegou;
- `TextResolution`: o que saiu;
- `TextProcessor`: quem resolve cache/contexto/tradução.

Essa camada é o elo que permite unificar áudio, texto digitado e texto recebido.

### `rtxlator/text_bridge.py`
Implementa a ponte de texto real.

Responsabilidades:

- configurar sessão de texto;
- manter tradutor de saída e de entrada;
- rodar CLI interativa;
- permitir `> mensagem` e `< mensagem`;
- reutilizar o mesmo núcleo textual do runtime de áudio.

## 7.3 Pastas de runtime

### `.claude/`
Não faz parte do produto final; é infraestrutura de agente/execução local.

#### `.claude/napkin.md`
Runbook interno com lições recorrentes:

- encoding de terminal;
- gargalos de latência;
- disciplina de backlog;
- guardrails de cache/contexto;
- diferenças entre microfone e loopback.

### `.venv/`
Ambiente virtual local. Contém todas as libs instaladas e binários Python. É essencial para executar, mas não é fonte de verdade do projeto.

### `models/`
Cache local dos modelos. É infraestrutura local de inferência, não código-fonte.

### `__pycache__/`
Artefatos compilados Python sem relevância arquitetural.

---

## 8. Realtime, latência e disciplina de desempenho

Este projeto existe sob um princípio arquitetural muito claro: **no realtime, um resultado fresco vale mais do que um resultado atrasado porém completo**.

### 8.1 Decisões que mostram essa filosofia

- filas curtas por pipeline;
- descarte de chunks quando a fila enche;
- parcial não bloqueia final;
- final tem prioridade sobre parcial;
- remoto é proibido no caminho parcial;
- contexto pesado só entra se couber no orçamento de latência;
- loopback usa tuning mais estável que `ultra` puro.

### 8.2 Perfis de latência

O projeto trabalha hoje com três perfis:

- `ultra`
- `balanced`
- `quality`

Cada perfil controla:

- tamanho do chunk;
- mínimo de buffer;
- flush máximo;
- flush parcial;
- número de chunks de silêncio;
- tamanho da fila;
- VAD do Whisper;
- tempos mínimos de fala/silêncio.

### 8.3 Métricas expostas

O projeto já expõe por frase:

- `latency_ms`
- `transcribe_ms`
- `translate_ms`
- `cache_hit`
- `provider`

E no status:

- drops por fonte;
- `ctx-pause` quando o modo contextual fica caro demais.

---

## 9. Uso de GPU e caminho CUDA

Hoje a GPU é usada no caminho mais importante: **ASR**.

### 9.1 Como a GPU entra

- `detect_device()` tenta `ctranslate2.get_cuda_device_count()`;
- se encontrar CUDA, escolhe `device=cuda` e `compute_type=int8_float16`;
- `faster-whisper` é carregado com esse device;
- o projeto também faz bootstrap das DLLs NVIDIA instaladas por pip para evitar falhas de carregamento no Windows.

### 9.2 O que roda em GPU

Confirmadamente, o caminho principal acelerado é:

- `WhisperModel` / `faster-whisper` / `ctranslate2`.

### 9.3 O que não está plenamente no mesmo caminho de GPU

Partes auxiliares do ecossistema de tradução/localização ainda podem usar CPU, especialmente componentes auxiliares dos pacotes de MT. Isso não destrói o projeto, porque o maior ganho de latência vem do ASR acelerado.

---

## 10. Tradução, fallback e “inteligência” contextual

## 10.1 Estratégia base

A tradução trabalha em camadas:

1. identidade, quando origem e destino coincidem ou a frase já veio traduzida;
2. memória determinística do usuário;
3. proteção de termos do glossário;
4. Argos local/offline;
5. Google fallback, quando permitido;
6. pós-processamento de saída com preferências finais.

## 10.2 Modos de interpretação

### `fast`
- mais rápido;
- mais literal;
- tende a ficar no local/cache.

### `hybrid`
- parcial rápida;
- final pode tentar leitura mais contextual;
- se ficar caro demais, entra em cooldown contextual.

### `contextual`
- tenta máxima naturalidade;
- maior risco de custo em `tr ms`.

## 10.3 Contexto pessoal

O projeto evita “treino de modelo” pesado e usa uma abordagem muito mais pragmática e controlável:

- normalizações do jeito de falar;
- memória exata de correções;
- glossário com placeholders;
- correções finais de saída;
- regras ativadas por palavras-chave de domínio.

Essa é uma solução de altíssimo ROI para projetos realtime: melhora muito frase recorrente sem destruir CPU nem previsibilidade.

---

## 11. Ponte de texto

A ponte de texto é o começo da expansão do sistema para além do áudio.

Ela permite:

- traduzir texto antes de enviar;
- traduzir texto assim que chega;
- testar o núcleo textual sem depender do áudio;
- reaproveitar contexto pessoal, cache e tradutor.

Arquiteturalmente, ela é muito importante porque prova que o runtime não é mais “só áudio”; ele está virando um núcleo linguístico reutilizável.

---

## 12. Testes e prevenção de regressão

O projeto já tem uma base saudável de testes unitários e de comportamento.

### `test_realtime_translator.py`
Valida:

- perfis de latência;
- overrides;
- chave de cache por idioma;
- alias de detecção de idioma;
- extração de segmento contextual;
- aplicação de memória/glossário;
- status de runtime;
- renderização de linha parcial.

### `test_context_manager.py`
Valida:

- persistência de mapeamentos;
- merge de keywords em regras contextuais.

### `test_source_profiles.py`
Valida:

- que `system` é mais tolerante que o default;
- que áudio de sistema de baixo nível recebe boost.

### `test_text_processing.py`
Valida:

- cache separado por direção;
- bypass de cache para contexto;
- desativação de remoto em parciais.

Além disso, já foram usados smoke tests para:

- compilar com `py_compile`;
- rodar a suíte `unittest`;
- subir o CLI principal;
- rodar o gerenciador de contexto;
- rodar a ponte de texto.

---

## 13. Riscos técnicos atuais

Mesmo bem melhor do que no início, o projeto ainda tem riscos importantes.

### 13.1 Monolito principal ainda grande

`realtime_translator.py` continua sendo grande e concentrando muita responsabilidade.

### 13.2 Dependência do ambiente Windows

O projeto é fortemente otimizado para Windows/WASAPI/CUDA. Portabilidade hoje não é meta principal.

### 13.3 Loopback ainda depende do endpoint correto

Parte da percepção de “tradução ruim do áudio do sistema” pode vir de:

- endpoint errado;
- perfil inadequado;
- idioma em auto quando poderia estar fixo;
- comportamento específico do áudio da chamada.

### 13.4 Fallback remoto

O fallback com Google é útil, mas introduz:

- variação de latência;
- dependência de rede;
- menor previsibilidade;
- serialização de chamadas, já que hoje ele funciona como um gargalo mais centralizado do que o caminho local.

### 13.5 Ausência de separação formal de artefatos

Ainda existe mistura entre:

- código-fonte;
- logs temporários;
- caches locais;
- estado pessoal.

Isso já está melhor, mas ainda pode evoluir.

### 13.6 Pacotes Argos ainda podem entrar no caminho crítico

Embora o projeto já faça preload dos pares mais prováveis, a instalação lazy de um par novo ainda pode causar:

- stalls perceptíveis;
- primeira tradução muito mais lenta;
- diferença de comportamento entre ambientes recém-instalados e ambientes já aquecidos.

---

## 14. Pontos fortes do projeto hoje

- hot path pesado já acelerado em GPU;
- desenho explícito para baixa latência;
- suporte real a microfone e loopback;
- contexto pessoal determinístico e útil;
- arquitetura textual começando a desacoplar áudio de tradução;
- instalador e launchers práticos para uso local;
- testes cobrindo regras importantes de regressão;
- documentação operacional suficiente para continuidade.

---

## 15. Melhor direção de evolução

A próxima evolução saudável não é “jogar mais complexidade aleatória”. É seguir a mesma linha de robustez:

1. dividir `realtime_translator.py` em módulos (`audio_io`, `runtime`, `display`, `providers`);
2. criar um modo de chamada/loopback realmente especializado;
3. mover runtime artifacts para uma pasta dedicada (`.runtime/` ou `%LOCALAPPDATA%`);
4. separar melhor tradução local e fallback remoto em pools/políticas distintas;
5. criar adaptadores reais para chat/texto;
6. testar mais profundamente o caminho de áudio do sistema;
7. se necessário, adicionar uma camada semântica final opcional, mas fora do hot path parcial.

---

## 16. Conclusão técnica

Hoje o projeto já não é mais “um script de tradução”.

Ele é um **runtime local de tradução multimodal leve**, com:

- captura de áudio;
- transcrição acelerada por GPU;
- tradução local/offline;
- fallback remoto controlado;
- personalização contextual do usuário;
- UI de terminal;
- ponte de texto;
- testes;
- instalador e diagnósticos.

O desenho técnico atual está alinhado com o objetivo real do produto: **ser rápido, usável, ajustável e evolutivo sem sacrificar estabilidade**.

O principal desafio daqui para frente não é “fazer funcionar”; isso já está acontecendo. O desafio é **modularizar melhor sem perder a agressividade de desempenho que já foi conquistada**.
