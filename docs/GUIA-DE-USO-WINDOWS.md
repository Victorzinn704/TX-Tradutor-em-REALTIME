# Guia de uso no Windows

Este guia descreve o caminho recomendado para preparar, diagnosticar e executar o `Realtime Translator` em uma máquina Windows. O projeto foi desenhado para uso local: ele não sobe servidor, não exige banco de dados e não precisa de backend externo.

## 1. Requisitos

Antes de rodar o projeto, confirme estes pontos:

| Item | Por que importa |
| --- | --- |
| Windows 11 | O áudio usa WASAPI e loopback do Windows. |
| Python 3.11 ou superior | O runtime Python, testes e instalador dependem dele. |
| Driver NVIDIA atualizado | Necessário para usar CUDA com `faster-whisper` e `CTranslate2`. |
| Git ou ZIP do repositório | Serve para baixar o código. |
| Espaço em disco para modelos | Whisper, Argos e OPUS-MT podem ocupar centenas de MB ou mais. |
| Microfone ou saída de áudio ativa | O tradutor precisa de uma fonte real para capturar áudio. |

O projeto também funciona em CPU, mas a experiência de tempo real fica mais lenta. GPU NVIDIA é o cenário-alvo.

## 2. Baixar o projeto

Pelo Git:

```bat
git clone https://github.com/Victorzinn704/TX-Tradutor-em-REALTIME.git
cd TX-Tradutor-em-REALTIME
```

Por ZIP:

1. abra o repositório no GitHub;
2. use `Code > Download ZIP`;
3. extraia a pasta;
4. abra o terminal dentro da pasta extraída.

## 3. Instalar dependências

Execute:

```bat
instalar.bat
```

O instalador faz quatro trabalhos principais:

1. cria o ambiente virtual em `.venv`;
2. instala as bibliotecas de áudio, ASR, tradução e UI;
3. prepara pacotes de tradução local quando possível;
4. testa se CUDA está disponível pelo `CTranslate2`.

Se o download de modelo falhar por conexão, limite do Hugging Face ou falta de espaço, a instalação não precisa ser considerada perdida. O próprio script informa o que falhou e o runtime tenta baixar alguns recursos no primeiro uso.

## 4. Diagnosticar a máquina

Antes de usar em apresentação, rode:

```bat
diagnostico.bat
```

Esse comando mostra:

- se CUDA está disponível;
- qual GPU foi detectada;
- quais dispositivos de áudio existem;
- quais endpoints de loopback podem capturar áudio do sistema;
- qual ID usar em `--mic-id` e `--spk-id`.

Se o áudio do sistema sair por um fone, monitor ou placa diferente, escolha o loopback do mesmo endpoint. Esse detalhe costuma explicar boa parte dos casos em que o tradutor "não escuta" vídeo, chamada ou reunião.

## 5. Executar pelo menu

Para uso normal:

```bat
rodar.bat
```

O menu permite escolher idioma, perfil de latência, fonte de áudio e ferramentas auxiliares sem alterar código.

## 6. Executar pela CLI

Exemplo para fala em português e tradução para inglês:

```bat
.venv\Scripts\python.exe realtime_translator.py --source pt --target en --model base --latency-profile ultra --ui-mode stable
```

Exemplo para vídeo ou reunião em inglês pelo áudio do sistema:

```bat
.venv\Scripts\python.exe realtime_translator.py --source en --target pt --no-mic --model base --latency-profile balanced --ui-mode stable
```

Quando `--source en` está fixo e o loopback está ativo, o pipeline pode usar o perfil `system_en`, com language lock imediato e Distil-Whisper EN-only para reduzir latência.

## 7. Listar dispositivos

Para achar IDs de microfone e loopback:

```bat
listar_dispositivos.bat
```

Depois use:

```bat
.venv\Scripts\python.exe realtime_translator.py --mic-id 3 --spk-id 7
```

Troque `3` e `7` pelos IDs mostrados no seu terminal.

## 8. Ponte de texto

Para traduzir texto digitado sem depender de áudio:

```bat
.venv\Scripts\python.exe texto_bridge.py --source pt --target en
```

No prompt da ponte:

```text
> mensagem que eu quero enviar
< mensagem que eu recebi
```

O sinal `>` traduz uma mensagem de saída. O sinal `<` traduz uma mensagem recebida.

## 9. Contexto pessoal

Para cadastrar glossário, correções e preferências:

```bat
.venv\Scripts\python.exe gerenciar_contexto.py
```

Esse fluxo grava `user_language_context.json`, que fica fora do Git porque pode conter frases e termos pessoais.

## 10. Runtime Rust opcional

Para compilar a ponte nativa:

```bat
compilar_rust.bat
```

O script gera `rtxlator\runtime_rs.pyd` quando a compilação termina corretamente.

Em máquinas com Python 3.14, o build PyO3 precisa desta variável:

```bat
set PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
```

O `compilar_rust.bat` já define essa variável antes do `cargo build`.

## 11. Problemas comuns

| Sintoma | Verificação prática |
| --- | --- |
| O áudio do sistema não aparece | Rode `diagnostico.bat` e escolha o loopback do endpoint correto. |
| CUDA não é detectado | Atualize driver NVIDIA e confira `nvidia-smi`. |
| O primeiro uso demora | Modelos podem estar sendo baixados ou carregados pela primeira vez. |
| Tradução fica literal demais | Use `--interpretation-mode hybrid` ou ajuste o contexto pessoal. |
| Latência alta no modo contextual | Use `fast` ou `hybrid`; remoto nunca deve entrar no caminho parcial. |
| Build Rust falha com Python 3.14 | Defina `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` ou use Python 3.11. |

