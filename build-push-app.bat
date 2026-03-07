@echo off
SET DOCKER_USER=leandrogbreve
SET TAG=latest

echo [1/3] Construindo imagem da API...
docker build -t %DOCKER_USER%/nistiprint-api:%TAG% -f apps/api/Dockerfile .

echo [2/3] Construindo imagem do WORKER...
docker build -t %DOCKER_USER%/nistiprint-worker:%TAG% -f apps/worker/Dockerfile .

echo [3/3] Construindo imagem do FRONTEND...
docker build -t %DOCKER_USER%/nistiprint-frontend:%TAG% -f apps/frontend/Dockerfile ./apps/frontend

echo.
echo [PUSH] Enviando imagens para o registro...
docker push %DOCKER_USER%/nistiprint-api:%TAG%
docker push %DOCKER_USER%/nistiprint-worker:%TAG%
docker push %DOCKER_USER%/nistiprint-frontend:%TAG%

echo.
echo CONCLUIDO! Agora atualize a Stack no Portainer.
pause