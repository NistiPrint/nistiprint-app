@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual nao encontrado.
    echo        Execute setup_agent.bat primeiro.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1

echo [NistiPrint] Iniciando agente local...
echo [NistiPrint] Para encerrar, pressione Ctrl+C.
echo.
python agent.py

if errorlevel 1 (
    echo.
    echo [ERRO] O agente foi encerrado com erro. Consulte:
    echo        %LOCALAPPDATA%\NistiPrint\agent.log
    pause
)