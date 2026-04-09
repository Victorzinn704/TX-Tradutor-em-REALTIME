@echo off
setlocal enabledelayedexpansion
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul
title Compilando runtime Rust — realtime_translator
chcp 65001 >nul
echo.
echo ================================================================
echo   Compilando runtime-rs (Rust + PyO3)
echo ================================================================
echo.

:: ── Verifica Rust ─────────────────────────────────────────────────
cargo --version >nul 2>&1
if errorlevel 1 (
    echo [1/3] Instalando Rust via rustup...
    if exist "%USERPROFILE%\rustup-init.exe" (
        "%USERPROFILE%\rustup-init.exe" -y --default-toolchain stable --target x86_64-pc-windows-msvc
    ) else (
        echo   Baixando rustup-init.exe...
        powershell -Command "Invoke-WebRequest -Uri https://win.rustup.rs/x86_64 -OutFile '%USERPROFILE%\rustup-init.exe'"
        "%USERPROFILE%\rustup-init.exe" -y --default-toolchain stable --target x86_64-pc-windows-msvc
    )
    set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
    cargo --version >nul 2>&1
    if errorlevel 1 (
        echo [ERRO] Rust nao instalado. Reinicie o terminal e execute novamente.
        popd >nul & pause & exit /b 1
    )
    echo   Rust instalado.
) else (
    echo [1/3] Rust encontrado:
    cargo --version
)

:: ── Adiciona target MSVC ──────────────────────────────────────────
echo.
echo [2/3] Garantindo target x86_64-pc-windows-msvc...
rustup target add x86_64-pc-windows-msvc >nul 2>&1
echo   OK.

:: ── Compila o workspace ───────────────────────────────────────────
echo.
echo [3/3] Compilando runtime-rs\ (release)...
cd runtime-rs
:: Python 3.14 requer stable ABI forward-compat (PyO3 0.22 suporta ate 3.13)
set "PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1"
cargo build --release --target x86_64-pc-windows-msvc 2>&1
if errorlevel 1 (
    echo.
    echo [ERRO] Compilacao falhou. Veja mensagens acima.
    popd >nul & pause & exit /b 1
)

:: ── Copia .dll para dentro do pacote Python ───────────────────────
echo.
echo Copiando runtime_rs.dll para rtxlator\...
set "DLL=target\x86_64-pc-windows-msvc\release\runtime_rs.dll"
if exist "%DLL%" (
    copy /Y "%DLL%" "..\rtxlator\runtime_rs.pyd" >nul
    echo   [OK] rtxlator\runtime_rs.pyd copiado.
) else (
    echo   [AVISO] DLL nao encontrada em %DLL% — verifique o build.
)

echo.
echo ================================================================
echo   Runtime Rust compilado e integrado ao Python.
echo   Execute rodar.bat para usar com aceleracao nativa.
echo ================================================================
echo.
popd >nul
pause
