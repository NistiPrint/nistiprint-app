"""Configuracao do Gunicorn carregada automaticamente no servidor.

O endpoint de impressao agrega dados de varios pedidos e pode ultrapassar o
padrao de 30 segundos do Gunicorn quando o banco esta remoto. O valor continua
configuravel pelo ambiente para permitir ajuste operacional sem alterar codigo.
"""

import os


timeout = int(os.getenv("GUNICORN_TIMEOUT_SECONDS", "180"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT_SECONDS", "30"))
