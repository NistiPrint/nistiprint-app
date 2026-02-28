import requests
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("BlingDriver")

def refresh_token(integration: dict) -> dict:
    """
    Driver para renovação de tokens do Bling V3.
    """
    credentials = integration.get("credentials") or {}
    config = integration.get("config") or {}
    
    # Busca em ambos os lugares por segurança
    client_id = config.get("client_id") or credentials.get("client_id")
    client_secret = config.get("client_secret") or credentials.get("client_secret")
    
    refresh_token = integration.get("refresh_token") or credentials.get("refresh_token")

    if not client_id or not client_secret:
        raise ValueError("Configuração do Bling (client_id ou client_secret) ausente.")
        
    if not refresh_token:
        raise ValueError("Refresh token ausente. A integração precisa ser reautorizada.")

    url = "https://www.bling.com.br/Api/v3/oauth/token"
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    
    auth = (client_id, client_secret)

    logger.info(f"Chamando API do Bling para renovação (Instance: {integration.get('instance_name')})")
    
    response = requests.post(url, data=payload, auth=auth)
    
    if response.status_code != 200:
        raise Exception(f"Erro na API do Bling: {response.status_code} - {response.text}")

    data = response.json()
    
    if data.get("error"):
        raise Exception(f"Erro reportado pelo Bling: {data.get('error_description', data.get('error'))}")

    # Retorna o dicionário formatado para atualização no Supabase
    return {
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token"),
        "expires_at": (datetime.utcnow() + timedelta(seconds=data.get("expires_in", 21600))).isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }

