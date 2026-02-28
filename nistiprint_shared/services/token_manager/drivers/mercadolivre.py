import requests
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("MLDriver")

def refresh_token(integration: dict) -> dict:
    """
    Driver para renovação de tokens do Mercado Livre.
    """
    credentials = integration.get("credentials") or {}
    config = integration.get("config") or {}
    
    client_id = config.get("client_id") or credentials.get("client_id")
    client_secret = config.get("client_secret") or credentials.get("client_secret")
    refresh_token = integration.get("refresh_token") or credentials.get("refresh_token")
    
    if not client_id or not client_secret or not refresh_token:
        raise ValueError("Configuração do Mercado Livre (client_id, client_secret ou refresh_token) incompleta.")

    url = "https://api.mercadolibre.com/oauth/token"
    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token
    }
    
    logger.info(f"Chamando API do Mercado Livre para renovação (Instance: {integration.get('instance_name')})")
    
    response = requests.post(url, data=payload)
    
    if response.status_code != 200:
        raise Exception(f"Erro na API do Mercado Livre: {response.status_code} - {response.text}")

    data = response.json()
    
    if data.get("error"):
        raise Exception(f"Erro reportado pelo ML: {data.get('error')} - {data.get('message')}")

    return {
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token"),
        "expires_at": (datetime.utcnow() + timedelta(seconds=data.get("expires_in", 21600))).isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }

