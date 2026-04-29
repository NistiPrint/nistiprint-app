import hmac
import hashlib
import time
import requests
import logging
import os
from datetime import datetime, timedelta

logger = logging.getLogger("ShopeeDriver")

def refresh_token(integration: dict) -> dict:
    """
    Driver para renovação de tokens da Shopee V2.
    """
    credentials = integration.get("credentials") or {}
    config = integration.get("config") or {}
    
    # Tenta pegar de credentials, config ou environment variables (fallback)
    partner_id_raw = credentials.get("partner_id") or config.get("partner_id") or os.getenv("SHOPEE_PARTNER_ID")
    partner_key = credentials.get("partner_key") or config.get("partner_key") or os.getenv("SHOPEE_PARTNER_KEY")
    
    # Access/Refresh tokens
    access_token = integration.get("access_token") or credentials.get("access_token")
    refresh_token = integration.get("refresh_token") or credentials.get("refresh_token")
    
    # Shopee pode ser shop_id ou merchant_id (cross-border)
    shop_id = config.get("shop_id") or credentials.get("shop_id")
    merchant_id = config.get("merchant_id") or credentials.get("merchant_id")
    
    if not partner_id_raw or not partner_key:
        raise ValueError("Configuração da Shopee (partner_id ou partner_key) ausente.")

    if not refresh_token:
        raise ValueError("Refresh token ausente. A integração precisa ser reautorizada.")

    partner_id = int(partner_id_raw)
    host = "https://partner.shopeemobile.com"
    timestamp = int(time.time())
    
    # Define o path e o body com base no tipo de conta
    if shop_id:
        path = "/api/v2/auth/access_token/get"
        body = {
            "partner_id": partner_id,
            "shop_id": int(shop_id),
            "refresh_token": refresh_token
        }
    elif merchant_id:
        path = "/api/v2/auth/merchant/access_token/get"
        body = {
            "partner_id": partner_id,
            "merchant_id": int(merchant_id),
            "refresh_token": refresh_token
        }
    else:
        raise ValueError("A integração Shopee deve ter shop_id ou merchant_id configurado.")

    # Cálculo do sign (Public API level for token)
    # Base string: partner_id + path + timestamp
    base_string = f"{partner_id}{path}{timestamp}"
    sign = hmac.new(partner_key.encode(), base_string.encode(), hashlib.sha256).hexdigest()
    
    url = f"{host}{path}?partner_id={partner_id}&timestamp={timestamp}&sign={sign}"
    
    logger.info(f"Chamando API da Shopee para renovação (Instance: {integration.get('instance_name')})")
    
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, json=body, headers=headers)
    
    if response.status_code != 200:
        raise Exception(f"Erro na API da Shopee: {response.status_code} - {response.text}")

    data = response.json()
    
    # A Shopee retorna erro dentro do JSON com status 200 em alguns casos
    if data.get("error"):
        raise Exception(f"Erro reportado pela Shopee: {data.get('error')} - {data.get('message')}")

    # Retorna o dicionário formatado para atualização no Supabase
    return {
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token"),
        "expires_at": (datetime.utcnow() + timedelta(seconds=data.get("expire_in", 14400))).isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }

