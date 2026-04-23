@echo off
REM ===========================================
REM NISTIPRINT - BUILD E DEPLOY UNIFICADO (API + FRONTEND)
REM ===========================================
REM Uso:
REM   build-gcp-unified.bat          - Build + Push + Deploy
REM   build-gcp-unified.bat build    - Apenas build
REM   build-gcp-unified.bat push     - Apenas push
REM   build-gcp-unified.bat deploy   - Apenas deploy
REM ===========================================

setlocal enabledelayedexpansion

REM Configurações
set PROJECT_ID=neolabs-nistiprint
set REGION=southamerica-east1
set ARTIFACT_REGISTRY=cloud-run-source-deploy
set SERVICE_NAME=nistiprint-app
set IMAGE_NAME=%REGION%-docker.pkg.dev/%PROJECT_ID%/%ARTIFACT_REGISTRY%/%SERVICE_NAME%:latest

REM Verifica argumento
if "%~1"=="" goto all
if /i "%~1"=="build" goto build
if /i "%~1"=="push" goto push
if /i "%~1"=="deploy" goto deploy
goto usage

:usage
echo.
echo NISTIPRINT - Build e Deploy Unificado (API + Frontend)
echo.
echo Uso:
echo   build-gcp-unified.bat          - Build + Push + Deploy
echo   build-gcp-unified.bat build    - Apenas build
echo   build-gcp-unified.bat push     - Apenas push
echo   build-gcp-unified.bat deploy   - Apenas deploy
echo.
goto end

:build
echo.
echo ===========================================
echo BUILD - Imagem Unificada (API + Frontend)
echo ===========================================
echo.
docker build -f apps/api/Dockerfile.gcp-unified ^
    -t %IMAGE_NAME% ^
    --build-arg VITE_API_URL=https://nistiprint-app-992903106218.%REGION%.run.app ^
    --build-arg VITE_SUPABASE_URL=%SUPABASE_URL% ^
    --build-arg VITE_SUPABASE_ANON_KEY=%SUPABASE_ANON_KEY% ^
    .

if %ERRORLEVEL% neq 0 (
    echo ERRO: Build falhou!
    goto end
)
echo Build concluido!
goto end

:push
echo.
echo ===========================================
echo PUSH - Imagem Unificada
echo ===========================================
echo.
docker push %IMAGE_NAME%
if %ERRORLEVEL% neq 0 (
    echo ERRO: Push falhou!
    goto end
)
echo Push concluido!
goto end

:deploy
echo.
echo ===========================================
echo DEPLOY - App Unificado no Cloud Run
echo ===========================================
echo.
echo Usando secrets do GCP Secret Manager...
echo.

REM Deploy com todos os secrets
gcloud run deploy %SERVICE_NAME% ^
    --image %IMAGE_NAME% ^
    --project %PROJECT_ID% ^
    --region %REGION% ^
    --allow-unauthenticated ^
    --memory 2Gi ^
    --cpu 1 ^
    --concurrency 80 ^
    --timeout 300s ^
    --min-instances=1 ^
    --update-secrets FIREBASE_CREDENTIALS=neolabs-nistiprint-firebase-adminsdk:latest,DATABASE_URL=DATABASE_URL_RIOMIDC:latest,GEMINI_API_KEY=GENAI_API_KEY_LEANDROGBREVE:latest,AISTUDIO_APIKEY=AISTUDIO_APIKEY:latest,SUPABASE_URL=SUPABASE_URL:latest,SUPABASE_SERVICE_KEY=SUPABASE_SERVICE_KEY:latest,SECRET_KEY=SECRET_KEY:latest

if %ERRORLEVEL% neq 0 (
    echo ERRO: Deploy falhou!
    echo.
    echo Verifique se todos os secrets existem no GCP Secret Manager:
    echo   gcloud secrets list
    goto end
)

echo.
echo ===========================================
echo DEPLOY CONCLUÍDO!
echo ===========================================
echo.
echo URL do App: https://%SERVICE_NAME%-992903106218.%REGION%.run.app
echo.
goto end

:all
echo.
echo ===========================================
echo NISTIPRINT - BUILD + PUSH + DEPLOY UNIFICADO
echo ===========================================
echo.

REM Build
call :build
if %ERRORLEVEL% neq 0 goto end

REM Push
call :push
if %ERRORLEVEL% neq 0 goto end

REM Deploy
call :deploy
if %ERRORLEVEL% neq 0 goto end

echo.
echo ===========================================
echo PROCESSO CONCLUÍDO COM SUCESSO!
echo ===========================================
echo.
echo URL do App: https://%SERVICE_NAME%-992903106218.%REGION%.run.app
echo.
goto end

:end
endlocal
