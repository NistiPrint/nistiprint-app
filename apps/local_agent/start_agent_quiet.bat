@echo off
setlocal
cd /d "%~dp0"

if exist "dist\NistiPrintAgent.exe" (
    start "" /min "dist\NistiPrintAgent.exe"
    exit /b 0
)

if not exist ".venv\Scripts\pythonw.exe" (
    echo [ERRO] Agente nao preparado. Execute setup_agent.bat ou build_agent.bat.
    exit /b 1
)

start "" /min ".venv\Scripts\pythonw.exe" agent.py
exit /b 0