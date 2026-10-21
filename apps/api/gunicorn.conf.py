"""Configuracao do Gunicorn carregada automaticamente no servidor.

O stream de notificacoes mantem conexoes abertas. Workers sync ficariam
ocupados por essas conexoes e impediriam o atendimento das demais rotas.
O endpoint de impressao pode ultrapassar o timeout padrao de 30 segundos;
o limite continua configuravel pelo ambiente.
"""

import os


worker_class = "gthread"
threads = 8
timeout = int(os.getenv("GUNICORN_TIMEOUT_SECONDS", "180"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT_SECONDS", "30"))
