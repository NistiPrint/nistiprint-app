@echo off
REM ===========================================
REM NISTIPRINT - LOG MANAGEMENT SCRIPT (WINDOWS)
REM ===========================================
REM Utilitarios para visualizar e gerenciar logs
REM Retencao automatica: 7 dias
REM ===========================================

setlocal enabledelayedexpansion

REM ===========================================
REM FUNCOES
REM ===========================================

:show_help
echo.
echo ═══════════════════════════════════════════
echo    NISTIPRINT - LOG MANAGEMENT TOOL
echo ═══════════════════════════════════════════
echo.
echo Uso: %~nx0 ^<comando^> [opcoes]
echo.
echo Comandos disponiveis:
echo   status          - Mostra status dos logs de todos os containers
echo   size            - Mostra tamanho dos logs de cada container
echo   follow ^<svc^>     - Logs em tempo real de um servico
echo   tail ^<svc^> [n]  - Ultimas n linhas (padrao: 100)
echo   search ^<svc^> ^<term^> - Busca termo nos logs
echo   export ^<svc^>     - Exporta logs para arquivo
echo   help            - Mostra esta ajuda
echo.
echo Servicos disponiveis:
echo   producao: frontend, api
echo   local:    frontend, api, worker, celery-beat, redis
echo.
goto :eof

:show_status
echo.
echo ═══════════════════════════════════════════
echo    STATUS DOS CONTAINERS E LOGS
echo ═══════════════════════════════════════════
echo.
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"
if errorlevel 1 (
    echo Erro: Nao foi possivel acessar o Docker
    goto :eof
)
echo.
echo Logs estao configurados com retencao automatica:
echo   - Driver: local
echo   - Max size por arquivo: 10MB
echo   - Max arquivos: 10 (100MB por container)
echo   - Compressao: ativada
echo.
goto :eof

:show_log_size
echo.
echo ═══════════════════════════════════════════
echo    TAMANHO DOS LOGS POR CONTAINER
echo ═══════════════════════════════════════════
echo.
for /f %%i in ('docker ps -q') do (
    set container=%%i
    for /f "tokens=*" %%n in ('docker inspect --format="{{.Name}}" %%i') do (
        set name=%%n
        set name=!name:/=!
        for /f "tokens=*" %%p in ('docker inspect --format="{{.LogPath}}" %%i') do (
            set logpath=%%p
            if exist !logpath! (
                for /f "tokens=1" %%s in ('powershell -command "[math]::Round((Get-Item '!logpath!').Length / 1MB, 2)"') do (
                    echo   !name!: %%s MB
                )
            )
        )
    )
)
echo.
goto :eof

:follow_logs
if "%~2"=="" (
    echo Erro: Especifique um servico
    echo Uso: %~nx0 follow ^<servico^>
    goto :eof
)
set service=%~2
echo Monitorando logs de '%service%' (Ctrl+C para sair)...
echo.
for /f %%i in ('docker ps --filter "name=%service%" --format "{{.ID}}"') do set container=%%i
if "!container!"=="" (
    echo Erro: Container '%service%' nao encontrado
    goto :eof
)
docker logs -f !container! --tail 50
goto :eof

:tail_logs
if "%~2"=="" (
    echo Erro: Especifique um servico
    echo Uso: %~nx0 tail ^<servico^> [n_linhas]
    goto :eof
)
set service=%~2
set lines=%~3
if "!lines!"=="" set lines=100
for /f %%i in ('docker ps --filter "name=%service%" --format "{{.ID}}"') do set container=%%i
if "!container!"=="" (
    echo Erro: Container '%service%' nao encontrado
    goto :eof
)
echo Ultimas !lines! linhas de '%service%':
echo.
docker logs !container! --tail !lines!
goto :eof

:search_logs
if "%~2"=="" (
    echo Erro: Especifique servico e termo de busca
    echo Uso: %~nx0 search ^<servico^> ^<termo^>
    goto :eof
)
if "%~3"=="" (
    echo Erro: Especifique servico e termo de busca
    echo Uso: %~nx0 search ^<servico^> ^<termo^>
    goto :eof
)
set service=%~2
set term=%~3
for /f %%i in ('docker ps --filter "name=%service%" --format "{{.ID}}"') do set container=%%i
if "!container!"=="" (
    echo Erro: Container '%service%' nao encontrado
    goto :eof
)
echo Buscando '%term%' nos logs de '%service%':
echo.
docker logs !container! 2>&1 | findstr /i "%term%"
goto :eof

:export_logs
if "%~2"=="" (
    echo Erro: Especifique um servico
    echo Uso: %~nx0 export ^<servico^>
    goto :eof
)
set service=%~2
for /f %%i in ('docker ps --filter "name=%service%" --format "{{.ID}}"') do set container=%%i
if "!container!"=="" (
    echo Erro: Container '%service%' nao encontrado
    goto :eof
)
for /f "tokens=1-3 delims=/ " %%a in ("%date%") do set datestr=%%c%%b%%a
for /f "tokens=1-2 delims=: " %%a in ("%time%") do set timestr=%%a%%b
set filename=logs_%service%_%datestr%_%timestr%.txt
echo Exportando logs de '%service%' para %filename%...
docker logs !container! > "%filename%" 2>&1
echo Logs exportados: %filename%
goto :eof

REM ===========================================
REM MAIN
REM ===========================================

if "%~1"=="" goto show_help
if /i "%~1"=="status" goto show_status
if /i "%~1"=="size" goto show_log_size
if /i "%~1"=="follow" goto follow_logs
if /i "%~1"=="tail" goto tail_logs
if /i "%~1"=="search" goto search_logs
if /i "%~1"=="export" goto export_logs
if /i "%~1"=="help" goto show_help

echo Comando desconhecido: %~1
echo Use '%~nx0 help' para ver os comandos disponiveis
