@echo off
setlocal EnableDelayedExpansion

REM =======================================================
REM NISTIPRINT - MIGRACAO DE STACK
REM =======================================================
REM Migrar da stack unificada (core) para stacks separadas
REM (infra + worker)
REM =======================================================
REM Uso:
REM   migrate-stack.bat              - Migrar com seguranca
REM   migrate-stack.bat force        - Migrar sem backup
REM =======================================================

cd /d "%~dp0"

echo.
echo =============================================
echo [MIGRACAO] Stack Core -> Infra + Worker
echo =============================================
echo.
echo Esta migracao vai:
echo   1. Parar a stack core atual
echo   2. Preservar volumes do redis e n8n
echo   3. Subir nova stack de infra (redis + n8n)
echo   4. Subir nova stack de worker
echo.
echo Os volumes existentes SERAO PRESERVADOS!
echo.

if /i "%~1"=="force" goto :migrate

echo AVISO: Faca backup antes de continuar!
echo.
pause

:migrate
echo.
echo [1/5] Verificando stack core atual...
docker stack ps nistiprint-core --format "{{.Name}}" 2>nul | findstr "worker" >nul
if errorlevel 1 (
    echo [INFO] Stack core nao encontrada ou ja migrada.
    goto :check_volumes
)
echo [OK] Stack core encontrada.

echo.
echo [2/5] Parando stack core (sem remover volumes)...
docker stack rm nistiprint-core
echo Aguardando parada dos servicos...
timeout /t 10 /nobreak >nul

:check_volumes
echo.
echo [3/5] Verificando volumes existentes...
docker volume ls | findstr "nistiprint-redis-data" >nul
if errorlevel 1 (
    echo [ERRO] Volume do Redis nao encontrado!
    echo Os dados podem ter sido perdidos.
    goto :abort
)
docker volume ls | findstr "nistiprint-n8n-data" >nul
if errorlevel 1 (
    echo [ERRO] Volume do n8n nao encontrado!
    echo Os dados podem ter sido perdidos.
    goto :abort
)
echo [OK] Volumes preservados.

echo.
echo [4/5] Subindo infraestrutura critica...
docker-compose -f docker-compose.infra.yml up -d
timeout /t 5 /nobreak >nul

echo.
echo [5/5] Subindo worker...
docker-compose -f docker-compose.worker.yml up -d

echo.
echo =============================================
echo [CONCLUIDO] Migracao finalizada!
echo =============================================
echo.
echo Proximos passos no Portainer:
echo   1. Remova a stack "nistiprint-core" (opcional)
echo   2. Crie stack "nistiprint-infra" com docker-compose.infra.yml
echo   3. Crie stack "nistiprint-worker" com docker-compose.worker.yml
echo.
echo Ou use localmente:
echo   - deploy-infra.bat status
echo   - deploy-worker.bat status
echo.
goto :eof

:abort
echo.
echo =============================================
echo [ABORTADO] Migracao cancelada!
echo =============================================
echo.
goto :eof
