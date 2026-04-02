@echo off
setlocal EnableDelayedExpansion

REM =======================================================
REM NISTIPRINT - SCRIPT DE BUILD E PUSH
REM =======================================================
REM Aplicacoes: api, worker, frontend
REM Infraestrutura (redis, n8n): gerencia separadamente
REM =======================================================

SET DOCKER_USER=leandrogbreve
SET TAG=latest

REM ==================== AJUDA ====================
if "%~1"=="" goto :help
if /i "%~1"=="-h" goto :help
if /i "%~1"=="--help" goto :help
if /i "%~1"=="help" goto :help

REM ==================== LOCAL ====================
if /i "%~1"=="local" (
    if "%~2"=="" goto :local_all
    if /i "%~2"=="api" goto :local_api
    if /i "%~2"=="worker" goto :local_worker
    if /i "%~2"=="frontend" goto :local_frontend
    SET TAG=%~2
    shift
    if "%~2"=="" goto :local_all
    goto :local_services
)

REM ==================== PUSH ====================
if /i "%~1"=="push" (
    if "%~2"=="" goto :push_all
    if /i "%~2"=="api" goto :push_api
    if /i "%~2"=="worker" goto :push_worker
    if /i "%~2"=="frontend" goto :push_frontend
    SET TAG=%~2
    shift
    if "%~2"=="" goto :push_all
    goto :push_services
)

REM ==================== CLEAN ====================
if /i "%~1"=="clean" goto :clean

goto :help

:help
echo.
echo [NISTIPRINT BUILD]
echo.
echo Aplicacoes: api, worker, frontend
echo Infraestrutura (redis, n8n): stack separada
echo.
echo Uso:
echo   build.bat local              Build local: api, worker, frontend (tag: latest)
echo   build.bat local dev          Build local com tag customizada
echo   build.bat local api          Build local apenas da API
echo   build.bat local dev api      Build local API com tag dev
echo   build.bat local dev api worker  Build local API e Worker com tag dev
echo   build.bat push               Build + Push: api, worker, frontend (tag: latest)
echo   build.bat push dev           Build + Push todos (tag: dev)
echo   build.bat push dev api       Build + Push API (tag: dev)
echo   build.bat push dev api worker Build + Push API e Worker (tag: dev)
echo   build.bat clean              Remove imagens dangling/orphan
echo.
echo Exemplos:
echo   build.bat local              Testa todas as aplicacoes localmente
echo   build.bat local worker       Testa apenas o worker
echo   build.bat push worker        Publica apenas o worker
echo.
echo Nota: redis e n8n sao gerenciados pela stack nistiprint-infra
echo       Veja: apps/ops/docker-compose.infra.yml
echo.
goto :eof

:local_all
echo.
echo =============================================
echo [LOCAL BUILD] Construindo imagens para teste
echo =============================================
echo Tag: %TAG%
echo.
echo [1/3] Construindo API...
docker build -t %DOCKER_USER%/nistiprint-api:%TAG% -f apps/api/Dockerfile .
echo [2/3] Construindo WORKER...
docker build -t %DOCKER_USER%/nistiprint-worker:%TAG% -f apps/worker/Dockerfile .
echo [3/3] Construindo FRONTEND...
docker build -t %DOCKER_USER%/nistiprint-frontend:%TAG% -f apps/frontend/Dockerfile ./apps/frontend
echo.
echo [CONCLUIDO] Imagens prontas para uso local
echo.
goto :eof

:local_services
echo.
echo =============================================
echo [LOCAL BUILD] Servicos especificos
echo =============================================
echo Tag: %TAG%
echo.
:local_loop
if "%~2"=="" goto :local_done
if /i "%~2"=="api" (
    echo [BUILD] API...
    docker build -t %DOCKER_USER%/nistiprint-api:%TAG% -f apps/api/Dockerfile .
) else if /i "%~2"=="worker" (
    echo [BUILD] WORKER...
    docker build -t %DOCKER_USER%/nistiprint-worker:%TAG% -f apps/worker/Dockerfile .
) else if /i "%~2"=="frontend" (
    echo [BUILD] FRONTEND...
    docker build -t %DOCKER_USER%/nistiprint-frontend:%TAG% -f apps/frontend/Dockerfile ./apps/frontend
) else (
    echo [WARN] Servico desconhecido: %~2
)
shift
goto :local_loop

:local_api
echo.
echo =============================================
echo [LOCAL BUILD] API
echo =============================================
echo Tag: %TAG%
echo.
docker build -t %DOCKER_USER%/nistiprint-api:%TAG% -f apps/api/Dockerfile .
goto :local_done

:local_worker
echo.
echo =============================================
echo [LOCAL BUILD] WORKER
echo =============================================
echo Tag: %TAG%
echo.
docker build -t %DOCKER_USER%/nistiprint-worker:%TAG% -f apps/worker/Dockerfile .
goto :local_done

:local_frontend
echo.
echo =============================================
echo [LOCAL BUILD] FRONTEND
echo =============================================
echo Tag: %TAG%
echo.
docker build -t %DOCKER_USER%/nistiprint-frontend:%TAG% -f apps/frontend/Dockerfile ./apps/frontend
goto :local_done

:local_done
echo.
echo [CONCLUIDO] Imagens prontas para uso local
echo.
goto :eof

:push_all
echo.
echo =============================================
echo [PUSH BUILD] Construindo e enviando imagens
echo =============================================
echo Tag: %TAG%
echo.
echo [1/3] API...
docker build -t %DOCKER_USER%/nistiprint-api:%TAG% -f apps/api/Dockerfile .
docker push %DOCKER_USER%/nistiprint-api:%TAG%
echo [2/3] WORKER...
docker build -t %DOCKER_USER%/nistiprint-worker:%TAG% -f apps/worker/Dockerfile .
docker push %DOCKER_USER%/nistiprint-worker:%TAG%
echo [3/3] FRONTEND...
docker build -t %DOCKER_USER%/nistiprint-frontend:%TAG% -f apps/frontend/Dockerfile ./apps/frontend
docker push %DOCKER_USER%/nistiprint-frontend:%TAG%
goto :push_done

:push_services
echo.
echo =============================================
echo [PUSH BUILD] Servicos especificos
echo =============================================
echo Tag: %TAG%
echo.
:push_loop
if "%~2"=="" goto :push_done
if /i "%~2"=="api" (
    echo [BUILD+PUSH] API...
    docker build -t %DOCKER_USER%/nistiprint-api:%TAG% -f apps/api/Dockerfile .
    docker push %DOCKER_USER%/nistiprint-api:%TAG%
) else if /i "%~2"=="worker" (
    echo [BUILD+PUSH] WORKER...
    docker build -t %DOCKER_USER%/nistiprint-worker:%TAG% -f apps/worker/Dockerfile .
    docker push %DOCKER_USER%/nistiprint-worker:%TAG%
) else if /i "%~2"=="frontend" (
    echo [BUILD+PUSH] FRONTEND...
    docker build -t %DOCKER_USER%/nistiprint-frontend:%TAG% -f apps/frontend/Dockerfile ./apps/frontend
    docker push %DOCKER_USER%/nistiprint-frontend:%TAG%
) else (
    echo [WARN] Servico desconhecido: %~2
)
shift
goto :push_loop

:push_api
echo.
echo =============================================
echo [PUSH BUILD] API
echo =============================================
echo Tag: %TAG%
echo.
docker build -t %DOCKER_USER%/nistiprint-api:%TAG% -f apps/api/Dockerfile .
docker push %DOCKER_USER%/nistiprint-api:%TAG%
goto :push_done

:push_worker
echo.
echo =============================================
echo [PUSH BUILD] WORKER
echo =============================================
echo Tag: %TAG%
echo.
docker build -t %DOCKER_USER%/nistiprint-worker:%TAG% -f apps/worker/Dockerfile .
docker push %DOCKER_USER%/nistiprint-worker:%TAG%
goto :push_done

:push_frontend
echo.
echo =============================================
echo [PUSH BUILD] FRONTEND
echo =============================================
echo Tag: %TAG%
echo.
docker build -t %DOCKER_USER%/nistiprint-frontend:%TAG% -f apps/frontend/Dockerfile ./apps/frontend
docker push %DOCKER_USER%/nistiprint-frontend:%TAG%
goto :push_done

:push_done
echo.
echo [CONCLUIDO] Imagens enviadas para Docker Hub
echo.
goto :eof

:clean
echo.
echo =============================================
echo [CLEAN] Removendo imagens dangling/orphan
echo =============================================
echo.
echo Removendo imagens dangling...
docker image prune -f
echo.
echo [CONCLUIDO] Limpeza finalizada
echo.
goto :eof
