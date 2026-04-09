@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >/dev/null
call .venv\Scripts\activate.bat

echo Baixando OPUS-MT multilingual->en (inclui pt->en)...
ct2-transformers-converter --model Helsinki-NLP/opus-mt-mul-en --output_dir models\opus\pt-en --copy_files source.spm target.spm --quantization int8
if errorlevel 1 (
    echo.
    echo [ERRO] Falha. Tente: .venv\Scripts\huggingface-cli login
    pause
    exit /b 1
)

echo >>pt<< > models\opus\pt-en\source_prefix.txt
echo [OK] Modelo pt-en pronto. OPUS-MT fast lane ativa.
pause
