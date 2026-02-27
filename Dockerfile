# ===========================================
# NISTIPRINT API - DOCKERFILE
# ===========================================

FROM python:3.12-slim

WORKDIR /app

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# O contexto de build deve ser a raiz (gcloud/run) para acessar nistiprint-shared
COPY nistiprint-shared /app/nistiprint-shared
RUN pip install --no-cache-dir /app/nistiprint-shared

# Copiar requirements da API
COPY nistiprint-api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código da API
COPY nistiprint-api/ .

# Expor porta
EXPOSE 8080

# Comando padrão
CMD ["python", "main.py"]
