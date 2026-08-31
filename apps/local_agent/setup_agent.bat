@echo off
setlocal
cd /d "%~dp0"

echo [NistiPrint] Preparando ambiente virtual...

where py >nul 2>nul
if %errorlevel% equ 0 (
    set "PYTHON=py -3"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo [ERRO] Python 3 nao foi encontrado.
        echo        Instale o Python 3.11 ou superior e tente novamente.
        pause
        exit /b 1
    )
    set "PYTHON=python"
)

if not exist ".venv\Scripts\python.exe" (
    echo [NistiPrint] Criando .venv...
    %PYTHON% -m venv .venv
    if errorlevel 1 goto :error
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 goto :error

echo [NistiPrint] Atualizando pip...
python -m pip install --upgrade pip
if errorlevel 1 goto :error

echo [NistiPrint] Instalando dependencias do agente e da bandeja...
python -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo [OK] Ambiente preparado com sucesso.
echo      Execute run_agent.bat para iniciar o agente com console.
echo      Execute build_agent.bat para gerar o executavel.
pause
exit /b 0

:error
echo.
echo [ERRO] Nao foi possivel preparar o ambiente.
pause
exit /b 1