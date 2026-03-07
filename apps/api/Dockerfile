# ===========================================
# NISTIPRINT API - DOCKERFILE (MONOREPO)
# ===========================================

FROM python:3.12-slim

WORKDIR /app

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Configurar ambiente Python para não gerar .pyc e não usar buffer no log
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_CACHE_DIR=/root/.cache/pip

# O contexto de build deve ser a raiz do monorepo para acessar packages/shared
# Importante: O build context no docker-compose deve ser a raiz do monorepo (.)
COPY packages/shared /app/packages/shared
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -e /app/packages/shared

# Copiar APENAS o requirements primeiro para aproveitar o cache de camada do Docker
COPY apps/api/requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /app/requirements.txt

# Copiar o restante do código da API
COPY apps/api/ /app/

# Expor porta
EXPOSE 8080

# Comando padrão
CMD ["python", "main.py"]
