@echo off
chcp 65001 >nul
setlocal DisableDelayedExpansion
title Aplicar traducao KH2
echo.
echo === Traducao Kingdom Hearts II ===
echo.

set "ALVO=%~1"
if defined ALVO goto temalvo

echo Arraste a pasta do jogo em cima deste arquivo.
echo Ou cole o caminho dela abaixo.
set /p "ALVO=Pasta PPSA35901-app: "
if defined ALVO goto temalvo

echo Nenhuma pasta informada.
goto fim

:temalvo
echo Alvo: "%ALVO%"
echo.

set "KH2_FROM_BAT=1"
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"

if exist "%~dp0aplicar_traducao.exe" (
    "%~dp0aplicar_traducao.exe" "%ALVO%"
    goto depois
)

where python >nul 2>&1
if errorlevel 1 goto trypy
python "%~dp0aplicar_traducao.py" "%ALVO%"
goto depois

:trypy
where py >nul 2>&1
if errorlevel 1 goto nopy
py -3 "%~dp0aplicar_traducao.py" "%ALVO%"
goto depois

:nopy
echo Python 3 nao encontrado.
echo Use o aplicar_traducao.exe da release ou instale o Python (python.org)
echo marcando "Add python.exe to PATH".
goto fim

:depois
if errorlevel 1 goto falhou
echo.
echo Pronto.
goto fim

:falhou
echo.
echo Falhou. Confira as mensagens acima e a pasta do jogo.

:fim
echo.
pause
endlocal
