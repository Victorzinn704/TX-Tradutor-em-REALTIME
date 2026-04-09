@echo off
setlocal EnableExtensions
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul
title Diagnostico de Audio e CUDA
chcp 65001 >nul
set PYTHONUTF8=1
call .venv\Scripts\activate.bat 2>nul || (
    echo Execute instalar.bat primeiro.
    popd >nul
    pause
    exit /b
)
python diagnostico.py
popd >nul
pause
