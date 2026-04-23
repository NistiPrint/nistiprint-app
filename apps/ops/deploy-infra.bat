@echo off
setlocal EnableDelayedExpansion

REM =======================================================
REM NISTIPRINT - DEPLOY DE INFRAESTRUTURA CRÍTICA
REM =======================================================
REM Uso:
REM   deploy-infra.bat up        - Sobe redis + n8n
REM   deploy-infra.bat down      - Derruba infra (CUIDADO!)
REM   deploy-infra.bat restart   - Reinicia sem perder dados
REM   deploy-infra.bat logs      - Mostra logs
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
echo [NISTIPRINT - DEPLOY INFRA]
echo.
echo Uso:
echo   deploy-infra.bat up        Sobe redis + n8n
echo   deploy-infra.bat down      Derruba infra (CUIDADO!)
echo   deploy-infra.bat restart   Reinicia sem perder dados
echo   deploy-infra.bat logs      Mostra logs
echo   deploy-infra.bat status    Status dos containers
echo.
goto :eof

:up
echo.
echo =============================================
echo [INFRA] Subindo Redis + n8n
echo =============================================
echo.
docker-compose -f docker-compose.infra.yml up -d
echo.
echo [CONCLUIDO] Infraestrutura crítica no ar!
echo.
echo Proximos passos:
echo   1. Verifique: deploy-infra.bat status
echo   2. Suba o worker: docker-compose -f docker-compose.worker.yml up -d
echo.
goto :eof

:down
echo.
echo =============================================
echo [INFRA] Derrubando Redis + n8n
echo =============================================
echo.
echo ATENCAO: Isso vai derrubar o n8n e redis!
echo Os volumes de dados NAO serao apagados.
echo.
pause
docker-compose -f docker-compose.infra.yml down
echo.
echo [CONCLUIDO] Infraestrutura derrubada.
echo.
goto :eof

:restart
echo.
echo =============================================
echo [INFRA] Reiniciando Redis + n8n
echo =============================================
echo.
docker-compose -f docker-compose.infra.yml restart
echo.
echo [CONCLUIDO] Infraestrutura reiniciada.
echo.
goto :eof

:logs
echo.
echo =============================================
echo [INFRA] Logs (Ctrl+C para sair)
echo =============================================
echo.
docker-compose -f docker-compose.infra.yml logs -f
goto :eof

:status
echo.
echo =============================================
echo [INFRA] Status dos Containers
echo =============================================
echo.
docker-compose -f docker-compose.infra.yml ps
echo.
echo Volumes:
docker volume ls | findstr nistiprint
echo.
goto :eof
