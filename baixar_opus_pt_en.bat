@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
call .venv\Scripts\activate.bat

echo Baixando OPUS-MT multilingual->en (inclui pt->en)...
if not exist models\opus\pt-en mkdir models\opus\pt-en >nul 2>&1
.venv\Scripts\ct2-transformers-converter.exe --model Helsinki-NLP/opus-mt-mul-en --output_dir models\opus\pt-en --copy_files source.spm target.spm tokenizer_config.json vocab.json --quantization int8 --force
if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao baixar o modelo publico do Hugging Face.
    echo        Isso normalmente e conexao, rate limit ou token invalido.
    echo        Se realmente precisar autenticar, rode no terminal:
    echo        .venv\Scripts\hf.exe auth login
    pause
    exit /b 1
)

echo >>pt<< > models\opus\pt-en\source_prefix.txt
echo Helsinki-NLP/opus-mt-mul-en > models\opus\pt-en\hf_repo.txt
echo [OK] Modelo pt-en pronto. OPUS-MT fast lane ativa.
pause
