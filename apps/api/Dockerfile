# ===========================================
# NISTIPRINT API - DOCKERFILE
# ===========================================

FROM python:3.12-slim

WORKDIR /app

# Instalar dependências do sistema e limpar cache do apt no mesmo passo
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Configurar ambiente Python para não gerar .pyc e não usar buffer no log
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_CACHE_DIR=/root/.cache/pip

# O contexto de build deve ser a raiz (gcloud/run) para acessar nistiprint-shared
COPY v3-nistiprint-shared /app/v3-nistiprint-shared
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install /app/v3-nistiprint-shared

# Copiar APENAS o requirements primeiro para aproveitar o cache de camada do Docker
COPY v3-nistiprint-api/requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /app/requirements.txt

# Copiar o restante do código da API
COPY v3-nistiprint-api/ /app/

# Expor porta
EXPOSE 8080

# Comando padrão
CMD ["python", "main.py"]
