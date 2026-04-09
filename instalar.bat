@echo off
setlocal enabledelayedexpansion
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul
title Instalando Tradutor de Audio em Tempo Real
chcp 65001 >nul
set PYTHONUTF8=1
echo.
echo ================================================================
echo   INSTALADOR — Tradutor de Audio em Tempo Real
echo   RTX 5060 Ti + RedDragon
echo ================================================================
echo.

:: ── Verifica Python ──────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado.
    echo        Instale em: https://www.python.org/downloads/
    echo        Marque "Add Python to PATH" durante a instalacao.
    popd >nul
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do echo   Python: %%v

:: ── Verifica driver NVIDIA ───────────────────────────────────────
echo.
echo [1/6] Verificando driver NVIDIA...
nvidia-smi >nul 2>&1
if errorlevel 1 (
    echo   [AVISO] nvidia-smi nao encontrado.
    echo           Instale o driver mais recente para RTX 5060 Ti:
    echo           https://www.nvidia.com/drivers
    echo.
) else (
    for /f "tokens=*" %%g in ('nvidia-smi --query-gpu^=name --format^=csv^,noheader 2^>nul') do (
        echo   GPU: %%g [OK]
    )
)

:: ── Ambiente virtual ─────────────────────────────────────────────
echo.
echo [2/6] Criando ambiente virtual Python...
if exist .venv (
    echo   Ambiente virtual ja existe, reutilizando.
) else (
    python -m venv .venv
    if errorlevel 1 (
        echo [ERRO] Falha ao criar venv.
        popd >nul
        pause
        exit /b 1
    )
    echo   Criado em .venv\
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet

:: ── Dependencias base ─────────────────────────────────────────────
echo.
echo [3/6] Instalando dependencias Python (incluindo argostranslate)...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERRO] Falha ao instalar dependencias. Tentando separadamente...
    pip install pyaudiowpatch faster-whisper deep-translator scipy numpy rich argostranslate --quiet
)
echo   Dependencias: OK

:: ── CUDA runtime via pip (Windows) ──────────────────────────────
echo.
echo [4/6] Garantindo CUDA runtime via pip...
echo   (cublas + cudnn + cuda-runtime)
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12 nvidia-cuda-runtime-cu12 --quiet

:: ── Baixa pacotes de traducao principais ─────────────────────────
echo.
echo [5/6] Pre-baixando pacotes de traducao en-^>pt e es-^>pt...
python -c "import os; os.environ['ARGOS_PACKAGES_DIR']='models/argos'; import argostranslate.package; argostranslate.package.update_package_index(); avail=argostranslate.package.get_available_packages(); [argostranslate.package.install_from_path(p.download()) for p in avail if (p.from_code,p.to_code) in [('en','pt'),('es','pt'),('pt','en')]]" 2>nul
if errorlevel 1 (
    echo   [AVISO] Pre-download falhou — pacotes serao baixados na primeira traducao.
) else (
    echo   Pacotes de traducao: OK
)

:: ── Modelos OPUS-MT via CTranslate2 ──────────────────────────────
echo.
echo [6/6] Preparando modelos OPUS-MT para fast lane...
if not exist models\opus\en-pt mkdir models\opus\en-pt >nul 2>&1
if not exist models\opus\es-pt mkdir models\opus\es-pt >nul 2>&1
if not exist models\opus\pt-en mkdir models\opus\pt-en >nul 2>&1

pip install ctranslate2 transformers sentencepiece --quiet
if errorlevel 1 (
    echo   [AVISO] Nao foi possivel garantir ferramentas de conversao OPUS-MT.
) else (
    call :PREPARE_OPUS_MODEL "Helsinki-NLP/opus-mt-tc-big-en-pt" "models\\opus\\en-pt" ""
    if not exist models\opus\en-pt\model.bin (
        call :PREPARE_OPUS_MODEL "Helsinki-NLP/opus-mt-en-ROMANCE" "models\\opus\\en-pt" ">>pt<<"
    )
    call :PREPARE_OPUS_MODEL "Helsinki-NLP/opus-mt-es-pt" "models\\opus\\es-pt" ""
    call :PREPARE_OPUS_MODEL "Helsinki-NLP/opus-mt-mul-en" "models\\opus\\pt-en" ">>pt<<"
    if not exist models\opus\pt-en\model.bin (
        call :PREPARE_OPUS_MODEL "Helsinki-NLP/opus-mt-tc-big-mul-en" "models\\opus\\pt-en" ">>pt<<"
    )
)

:: Testa se CUDA funciona com ctranslate2
echo.
echo Verificando CUDA com ctranslate2...
python -c "import ctranslate2; n=ctranslate2.get_cuda_device_count(); print('  CUDA devices:', n)" 2>nul
if errorlevel 1 (
    echo.
    echo   [AVISO] ctranslate2 nao detectou CUDA via pip.
    echo.
    echo   SOLUCAO MANUAL (1 vez):
    echo   1. Instale CUDA Toolkit 12.x:
    echo      https://developer.nvidia.com/cuda-downloads
    echo      Escolha: Windows ^> x86_64 ^> 11 ^> exe (local)
    echo.
    echo   2. Instale cuDNN 9.x:
    echo      https://developer.nvidia.com/cudnn-downloads
    echo      (requer conta NVIDIA gratuita)
    echo.
    echo   3. Reinicie o PC e execute rodar.bat
    echo.
    echo   O programa funciona em CPU enquanto isso, so sera mais lento.
)

:: ── Distil-Whisper EN-only (perfil system_en_fast) ───────────────
echo.
echo [7/7] Pre-carregando Distil-Whisper para perfil system_en...
echo   (usado automaticamente com --source en + loopback)
python -c "from faster_whisper import WhisperModel; m=WhisperModel('Systran/faster-distil-whisper-large-v3', device='cpu', compute_type='int8'); print('  Distil-Whisper: OK')" 2>nul
if errorlevel 1 (
    echo   [AVISO] Download do Distil-Whisper falhou ou nao ha espaco suficiente.
    echo          Sera baixado automaticamente no primeiro uso com --source en.
) else (
    echo   Distil-Whisper: OK
)

:: ── Finaliza ─────────────────────────────────────────────────────
echo.
echo ================================================================
echo   Instalacao concluida!
echo.
echo   Proximos passos:
echo   1. Execute:  diagnostico.bat    (verifica dispositivos)
echo   2. Execute:  rodar.bat          (inicia o tradutor)
echo ================================================================
echo.
popd >nul
pause
goto :eof

:PREPARE_OPUS_MODEL
set "HF_MODEL=%~1"
set "OUT_DIR=%~2"
set "SOURCE_PREFIX=%~3"
echo   [OPUS] %HF_MODEL% ^> %OUT_DIR%
if exist "%OUT_DIR%\model.bin" (
    echo     Modelo ja existe, reutilizando.
    if not "%SOURCE_PREFIX%"=="" (
        > "%OUT_DIR%\source_prefix.txt" echo %SOURCE_PREFIX%
    )
    exit /b 0
)

ct2-transformers-converter --model %HF_MODEL% --output_dir "%OUT_DIR%" --force >nul 2>&1
if errorlevel 1 (
    echo     [AVISO] Falha ao converter %HF_MODEL% — verifique conexao e espaco em disco.
    exit /b 0
)

python -c "from pathlib import Path; import shutil; import sys; from huggingface_hub import hf_hub_download; model=sys.argv[1]; out=Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True); shutil.copyfile(hf_hub_download(repo_id=model, filename='source.spm'), out / 'source.spm'); shutil.copyfile(hf_hub_download(repo_id=model, filename='target.spm'), out / 'target.spm')" "%HF_MODEL%" "%OUT_DIR%" >nul 2>&1
if errorlevel 1 (
    echo     [AVISO] Modelo convertido, mas source.spm/target.spm nao puderam ser copiados.
) else (
    echo     Tokenizers SentencePiece salvos.
)

if not "%SOURCE_PREFIX%"=="" (
    > "%OUT_DIR%\source_prefix.txt" echo %SOURCE_PREFIX%
)

if exist "%OUT_DIR%\model.bin" (
    echo     [OK] Modelo OPUS-MT pronto.
) else (
    echo     [AVISO] Conversao concluida sem model.bin detectado.
)
exit /b 0
