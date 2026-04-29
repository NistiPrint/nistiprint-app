@echo off
REM Script para sincronizar status de pedidos no Bling e Shopee
REM Uso: sync-pedidos-status.bat [opcoes]

echo ============================================================
echo Sincronizacao de Status de Pedidos (Bling + Shopee Flex)
echo ============================================================
echo.

REM Verificar argumentos
set DAYS=7
set LIMIT=
set DRY_RUN=
set FLEX_ONLY=
set STATUS_ONLY=

:parse_args
if "%~1"=="" goto :run
if "%~1"=="--days" set DAYS=%~2 & shift & shift & goto :parse_args
if "%~1"=="-d" set DAYS=%~2 & shift & shift & goto :parse_args
if "%~1"=="--limit" set LIMIT=--limit %~2 & shift & shift & goto :parse_args
if "%~1"=="-l" set LIMIT=--limit %~2 & shift & shift & goto :parse_args
if "%~1"=="--dry-run" set DRY_RUN=--dry-run & shift & goto :parse_args
if "%~1"=="--flex-only" set FLEX_ONLY=--flex-only & shift & goto :parse_args
if "%~1"=="--status-only" set STATUS_ONLY=--status-only & shift & goto :parse_args
if "%~1"=="--help" goto :help

:run
echo Configuracao:
echo   - Dias: %DAYS%
echo   - Limite: %LIMIT%
echo   - Dry Run: %DRY_RUN%
echo   - Flex Only: %FLEX_ONLY%
echo   - Status Only: %STATUS_ONLY%
echo.
echo Iniciando sincronizacao...
echo.

cd /d "%~dp0"
python sync_pedidos_status.py --days %DAYS% %LIMIT% %DRY_RUN% %FLEX_ONLY% %STATUS_ONLY%

echo.
echo ============================================================
echo Sincronizacao concluida!
echo Log salvo em: sync_pedidos_status.log
echo ============================================================
goto :eof

:help
echo Uso: sync-pedidos-status.bat [opcoes]
echo.
echo Opcoes:
echo   --days, -d N       Buscar pedidos dos ultimos N dias (default: 7)
echo   --limit, -l N      Limitar quantidade de pedidos
echo   --dry-run          Apenas simula, nao atualiza o banco
echo   --flex-only        Processar apenas pedidos Shopee (Flex)
echo   --status-only      Apenas atualizar status (nao verifica Flex)
echo   --help             Mostrar esta ajuda
echo.
echo Exemplos:
echo   sync-pedidos-status.bat
echo   sync-pedidos-status.bat --days 30
echo   sync-pedidos-status.bat --dry-run --limit 100
echo   sync-pedidos-status.bat --flex-only
echo   sync-pedidos-status.bat --status-only --days 1
goto :eof
