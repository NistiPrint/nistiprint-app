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

echo [NistiPrint] Instalando PyInstaller...
python -m pip install "pyinstaller>=6.0"
if errorlevel 1 goto :error

if not exist "icon.ico" (
    echo [ERRO] icon.ico nao encontrado.
    echo        Coloque o icone em %~dp0icon.ico e tente novamente.
    goto :error
)

echo [NistiPrint] Gerando dist\NistiPrintAgent.exe...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
python -m PyInstaller --noconfirm --clean --onefile --windowed --name NistiPrintAgent --icon icon.ico --add-data "icon.ico;." --hidden-import tray --hidden-import pystray --hidden-import PIL --hidden-import PIL.Image agent.py
if errorlevel 1 goto :error

echo.
echo [OK] Executavel criado em:
echo      %~dp0dist\NistiPrintAgent.exe
echo.
echo O executavel usa o mesmo mapa e log em:
echo      %LOCALAPPDATA%\NistiPrint\
pause
exit /b 0

:error
echo.
echo [ERRO] Nao foi possivel gerar o executavel.
pause
exit /b 1