# ===========================================
# NISTIPRINT API - WSGI ENTRY POINT
# ===========================================
# Este arquivo é o ponto de entrada para o Gunicorn no Cloud Run
# ===========================================

import os

# Importar a factory function do main.py
from main import create_app

# Criar a aplicação Flask
app = create_app()

# Configurar porta para Cloud Run
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
