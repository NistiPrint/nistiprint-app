@echo off
setlocal EnableDelayedExpansion

REM =======================================================
REM NISTIPRINT - DEPLOY DE WORKER
REM =======================================================
REM Uso:
REM   deploy-worker.bat up         - Sobe worker + beat
REM   deploy-worker.bat down       - Derruba worker
REM   deploy-worker.bat restart    - Reinicia worker
REM   deploy-worker.bat logs       - Mostra logs
REM   deploy-worker.bat status     - Status dos containers
REM =======================================================

cd /d "%~dp0"

if "%~1"=="" goto :help
if /i "%~1"=="up" goto :up
if /i "%~1"=="down" goto :down
if /i "%~1"=="restart" goto :restart
if /i "%~1"=="logs" goto :logs
if /i "%~1"=="status" goto :status

goto :help

:help
echo.
echo [NISTIPRINT - DEPLOY WORKER]
echo.
echo Uso:
echo   deploy-worker.bat up         Sobe worker + beat
echo   deploy-worker.bat down       Derruba worker
echo   deploy-worker.bat restart    Reinicia worker
echo   deploy-worker.bat logs       Mostra logs
echo   deploy-worker.bat status     Status dos containers
echo.
goto :eof

:up
echo.
echo =============================================
echo [WORKER] Subindo Worker + Beat
echo =============================================
echo.
echo Verificando infraestrutura...
docker ps --format "{{.Names}}" | findstr "nistiprint-redis" >nul
if errorlevel 1 (
    echo [ERRO] Redis nao esta rodando!
    echo Execute: deploy-infra.bat up
    goto :eof
)
echo [OK] Redis disponivel.
echo.
echo Subindo worker...
docker-compose -f docker-compose.worker.yml up -d
echo.
echo [CONCLUIDO] Worker e Beat no ar!
echo.
echo Dica: O worker pode levar alguns segundos para conectar ao Redis.
echo Verifique os logs: deploy-worker.bat logs
echo.
goto :eof

:down
echo.
echo =============================================
echo [WORKER] Derrubando Worker + Beat
echo =============================================
echo.
docker-compose -f docker-compose.worker.yml down
echo.
echo [CONCLUIDO] Worker derrubado.
echo.
goto :eof

:restart
echo.
echo =============================================
echo [WORKER] Reiniciando Worker + Beat
echo =============================================
echo.
docker-compose -f docker-compose.worker.yml restart
echo.
echo [CONCLUIDO] Worker reiniciado.
echo.
goto :eof

:logs
echo.
echo =============================================
echo [WORKER] Logs (Ctrl+C para sair)
echo =============================================
echo.
docker-compose -f docker-compose.worker.yml logs -f
goto :eof

:status
echo.
echo =============================================
echo [WORKER] Status dos Containers
echo =============================================
echo.
docker-compose -f docker-compose.worker.yml ps
echo.
goto :eof
