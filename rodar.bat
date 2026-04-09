@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul
title Tradutor de Audio em Tempo Real
chcp 65001 >nul
set PYTHONUTF8=1
call .venv\Scripts\activate.bat 2>nul || (
    echo [ERRO] Ambiente virtual nao encontrado.
    echo Execute instalar.bat primeiro.
    pause
    exit /b
)

:: ================================================================
:: CONFIGURACAO — edite aqui conforme necessario
:: ================================================================

:: Idioma de destino da traducao
if not defined TARGET set TARGET=pt

:: Idioma de origem
::   detect = auto-detect (padrao)
::   pt     = portugues fixo
::   en     = ingles fixo
::   es     = espanhol fixo
if not defined SOURCE set SOURCE=detect

:: Modelo Whisper
::   tiny     = minima latencia, qualidade menor
::   base     = mais rapido com boa qualidade
::   small    = recomendado para mais qualidade
::   medium   = alta qualidade
::   large-v3 = maxima qualidade (~1s latencia com GPU)
if not defined MODEL set MODEL=small

:: Perfil de latencia
::   ultra    = menor latencia possivel
::   balanced = equilibrio
::   quality  = prioriza estabilidade/qualidade
if not defined LATENCY_PROFILE set LATENCY_PROFILE=ultra

:: Interpretacao da traducao
::   fast       = mais rapido, mais literal
::   hybrid     = parcial rapida + final mais contextual
::   contextual = prioriza interpretacao contextual
if not defined INTERPRETATION_MODE set INTERPRETATION_MODE=hybrid

:: Interface do terminal
::   stable   = sem piscadas, imprime resultados finais e parciais
::   live     = tabela em tempo real
if not defined UI_MODE set UI_MODE=stable

:: Captura de entradas
::   1 = ligado / 0 = desligado
if not defined CAPTURE_MIC set CAPTURE_MIC=1
if not defined CAPTURE_SYSTEM_AUDIO set CAPTURE_SYSTEM_AUDIO=1

:: Menu inicial
::   1 = pergunta configuracao ao abrir
::   0 = usa os valores fixos acima
if not defined SHOW_MENU set SHOW_MENU=1

:: ================================================================

if /I "%SHOW_MENU%"=="1" call :CONFIG_MENU

set CMD_ARGS=--model %MODEL% --target %TARGET% --latency-profile %LATENCY_PROFILE% --ui-mode %UI_MODE% --interpretation-mode %INTERPRETATION_MODE%
if /I not "%SOURCE%"=="detect" if not "%SOURCE%"=="" set CMD_ARGS=%CMD_ARGS% --source %SOURCE%
if /I "%CAPTURE_MIC%"=="0" set CMD_ARGS=%CMD_ARGS% --no-mic
if /I "%CAPTURE_SYSTEM_AUDIO%"=="0" set CMD_ARGS=%CMD_ARGS% --no-spk

call :BOOL_LABEL "%CAPTURE_MIC%" MIC_LABEL
call :BOOL_LABEL "%CAPTURE_SYSTEM_AUDIO%" SYS_LABEL

echo.
echo === INICIANDO ===
echo Origem........: %SOURCE%
echo Destino.......: %TARGET%
echo Modelo........: %MODEL%
if /I "%SOURCE%"=="en" if /I "%CAPTURE_SYSTEM_AUDIO%"=="1" (
    echo   ^> SPK usara Distil-Whisper automaticamente ^(perfil system_en^)
)
echo Latencia......: %LATENCY_PROFILE%
echo Interpretacao.: %INTERPRETATION_MODE%
echo Microfone.....: %MIC_LABEL%
echo Audio sistema.: %SYS_LABEL%
echo UI............: %UI_MODE%
echo.
python realtime_translator.py %CMD_ARGS%

popd >nul
pause
goto :eof

:CONFIG_MENU
cls
echo ===============================================================
echo            TRADUTOR DE AUDIO - MENU RAPIDO
echo ===============================================================
echo Deixe em branco e aperte ENTER para manter o valor atual.
echo.
echo Perfis rapidos:
echo   1^) Padrao atual
echo   2^) Eu falo em portugues ^> ingles
echo   3^) Eu falo em ingles ^> portugues  (mic)
echo   4^) Video/chamada em ingles ^> portugues  [Distil-Whisper, mais rapido]
echo   5^) Video/chamada em espanhol ^> portugues
echo   6^) Gerenciar contexto pessoal (glossario, memoria, regras)
echo   7^) Ponte de texto (entrada/saida manual)
echo.
set "PROFILE_CHOICE="
set /p PROFILE_CHOICE=Escolha um perfil rapido [1-7] (%SOURCE%->%TARGET%): 
if /I "%PROFILE_CHOICE%"=="1" goto :AFTER_PROFILE
if /I "%PROFILE_CHOICE%"=="2" (
    set SOURCE=pt
    set TARGET=en
    set CAPTURE_MIC=1
    set CAPTURE_SYSTEM_AUDIO=0
    goto :AFTER_PROFILE
)
if /I "%PROFILE_CHOICE%"=="3" (
    set SOURCE=en
    set TARGET=pt
    set CAPTURE_MIC=1
    set CAPTURE_SYSTEM_AUDIO=0
    goto :AFTER_PROFILE
)
if /I "%PROFILE_CHOICE%"=="4" (
    set SOURCE=en
    set TARGET=pt
    set CAPTURE_MIC=0
    set CAPTURE_SYSTEM_AUDIO=1
    set LATENCY_PROFILE=balanced
    goto :AFTER_PROFILE
)
if /I "%PROFILE_CHOICE%"=="5" (
    set SOURCE=es
    set TARGET=pt
    set CAPTURE_MIC=0
    set CAPTURE_SYSTEM_AUDIO=1
    set LATENCY_PROFILE=balanced
    goto :AFTER_PROFILE
)
if /I "%PROFILE_CHOICE%"=="6" (
    cls
    python gerenciar_contexto.py
    echo.
    pause
    goto :CONFIG_MENU
)
if /I "%PROFILE_CHOICE%"=="7" (
    cls
    python texto_bridge.py --source %SOURCE% --target %TARGET% --interpretation-mode %INTERPRETATION_MODE%
    echo.
    pause
    goto :CONFIG_MENU
)

:AFTER_PROFILE
echo.
set "VALUE="
set /p VALUE=Idioma de origem [detect/pt/en/es] (%SOURCE%): 
if not "%VALUE%"=="" set SOURCE=%VALUE%
set /p VALUE=Idioma de destino [pt/en/es] (%TARGET%): 
if not "%VALUE%"=="" set TARGET=%VALUE%
set /p VALUE=Modo de interpretacao [fast/hybrid/contextual] (%INTERPRETATION_MODE%): 
if not "%VALUE%"=="" set INTERPRETATION_MODE=%VALUE%
call :BOOL_LABEL "%CAPTURE_MIC%" CURRENT_BOOL
set /p VALUE=Capturar microfone? [s/n] (!CURRENT_BOOL!): 
if not "%VALUE%"=="" call :BOOL_PARSE "%VALUE%" CAPTURE_MIC
call :BOOL_LABEL "%CAPTURE_SYSTEM_AUDIO%" CURRENT_BOOL
set /p VALUE=Capturar audio do sistema? [s/n] (!CURRENT_BOOL!): 
if not "%VALUE%"=="" call :BOOL_PARSE "%VALUE%" CAPTURE_SYSTEM_AUDIO
echo.
echo Modelos:
echo   tiny     = menor latencia, entende menos
echo   base     = melhor equilibrio para uso diario
echo   small    = mais qualidade, mais lento
echo   medium   = bem mais pesado, bom para fala dificil
echo   large-v3 = maxima qualidade, maior latencia
set /p VALUE=Modelo [tiny/base/small/medium/large-v3] (%MODEL%):
if not "%VALUE%"=="" (
    if /I "%VALUE%"=="t"       set VALUE=tiny
    if /I "%VALUE%"=="b"       set VALUE=base
    if /I "%VALUE%"=="s"       set VALUE=small
    if /I "%VALUE%"=="m"       set VALUE=medium
    if /I "%VALUE%"=="l"       set VALUE=large-v3
    if /I "%VALUE%"=="large"   set VALUE=large-v3
    set MODEL=%VALUE%
)
set /p VALUE=Perfil de latencia [ultra/balanced/quality] (%LATENCY_PROFILE%):
if not "%VALUE%"=="" (
    if /I "%VALUE%"=="u" set VALUE=ultra
    if /I "%VALUE%"=="b" set VALUE=balanced
    if /I "%VALUE%"=="q" set VALUE=quality
    set LATENCY_PROFILE=%VALUE%
)
set /p VALUE=UI [stable/live] (%UI_MODE%):
if not "%VALUE%"=="" (
    if /I "%VALUE%"=="s" set VALUE=stable
    if /I "%VALUE%"=="l" set VALUE=live
    set UI_MODE=%VALUE%
)
echo.
exit /b 0

:BOOL_LABEL
setlocal
set "RAW=%~1"
set "OUT=n"
if /I "%RAW%"=="1" set "OUT=s"
if /I "%RAW%"=="s" set "OUT=s"
if /I "%RAW%"=="sim" set "OUT=s"
endlocal & set "%~2=%OUT%"
exit /b 0

:BOOL_PARSE
setlocal
set "RAW=%~1"
set "OUT="
if /I "%RAW%"=="1" set "OUT=1"
if /I "%RAW%"=="s" set "OUT=1"
if /I "%RAW%"=="sim" set "OUT=1"
if /I "%RAW%"=="0" set "OUT=0"
if /I "%RAW%"=="n" set "OUT=0"
if /I "%RAW%"=="nao" set "OUT=0"
if /I "%RAW%"=="não" set "OUT=0"
endlocal & if not "%OUT%"=="" set "%~2=%OUT%"
exit /b 0


