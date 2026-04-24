# Use a imagem base oficial do Python.
FROM python:3.11-slim

# Defina o diretório de trabalho dentro do container.
WORKDIR /app

# Copie o arquivo de dependências e instale-as.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copie o resto do código da aplicação.
COPY . .

# Comando para iniciar o servidor web quando o container iniciar.
# O Gunicorn é um servidor WSGI de produção, mais robusto que o servidor de desenvolvimento do Flask.
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app
