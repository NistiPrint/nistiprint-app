@echo off
setlocal
cd /d "%~dp0"

set "AGENT_EXE=dist\NistiPrintAgent.exe"
if not exist "%AGENT_EXE%" set "AGENT_EXE=NistiPrintAgent.exe"
if exist "%AGENT_EXE%" goto :run_exe

if exist ".venv\Scripts\python.exe" (
    call ".venv\Scripts\python.exe" agent.py
    goto :finished
)

echo [ERRO] Nao encontrei NistiPrintAgent.exe nem o ambiente Python do agente.
echo Baixe o executavel novamente ou execute setup_agent.bat nesta pasta.
goto :finished

:run_exe
echo [NistiPrint] Executando "%AGENT_EXE%" para diagnostico.
echo Mantenha esta janela aberta e consulte a mensagem se o agente falhar.
echo.
"%AGENT_EXE%"

:finished
echo.
echo Log do agente: %LOCALAPPDATA%\NistiPrint\agent.log
echo Log de falha na inicializacao: %LOCALAPPDATA%\NistiPrint\startup-error.log
pause
