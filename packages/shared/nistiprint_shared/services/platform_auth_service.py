"""
Service for handling platform-specific authentication flows (OAuth, signatures, etc.)
"""
import hmac
import hashlib
import time
import requests
from typing import Dict, Optional

class PlatformAuthService:
    """
    Handles authentication logic for different platforms.
    """

    def generate_auth_url(self, module_id: str, config: Dict, redirect_uri: str, state: str = None) -> str:
        """
        Generates the authorization URL for a specific platform.
        """
        if module_id == 'shopee' or 'shopee' in module_id:
            return self._generate_shopee_auth_url(config, redirect_uri, state)
        elif module_id == 'mercadolivre':
            return self._generate_mercadolivre_auth_url(config, redirect_uri, state)
        elif module_id == 'bling':
            return self._generate_bling_auth_url(config, redirect_uri, state)
        # Add other platforms here
        return ""

    def _generate_bling_auth_url(self, config: Dict, redirect_uri: str, state: str = None) -> str:
        client_id = config.get('client_id')
        url = f"https://www.bling.com.br/Api/v3/oauth/authorize?response_type=code&client_id={client_id}&redirect_uri={redirect_uri}"
        if state:
            url += f"&state={state}"
        return url

    def _generate_shopee_auth_url(self, config: Dict, redirect_uri: str, state: str = None) -> str:
        """
        Generates Shopee Auth URL V2 with signature.
        """
        partner_id_raw = config.get('partner_id')
        partner_key = config.get('partner_key', '')

        if not partner_id_raw or not partner_key:
             return ""

        partner_id = int(partner_id_raw)
        # Usually for V2 auth: /api/v2/shop/auth_partner
        # But allow override from module definition if passed (not passed here, strictly logic)
        base_url = "https://partner.shopeemobile.com/api/v2/shop/auth_partner"
        
        timestamp = int(time.time())
        path = "/api/v2/shop/auth_partner"
        
        # V2 Sign: hmac-sha256(partner_key, partner_id + path + timestamp)
        base_string = f"{partner_id}{path}{timestamp}"
        sign = hmac.new(
            partner_key.encode('utf-8'),
            base_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        url = f"{base_url}?partner_id={partner_id}&timestamp={timestamp}&sign={sign}&redirect={redirect_uri}"
        if state:
            url += f"&state={state}"
            
        return url

    def _generate_mercadolivre_auth_url(self, config: Dict, redirect_uri: str, state: str = None) -> str:
        app_id = config.get('client_id')
        url = f"https://auth.mercadolibre.com.br/authorization?response_type=code&client_id={app_id}&redirect_uri={redirect_uri}"
        if state:
            url += f"&state={state}"
        return url

    def exchange_code_for_token(self, module_id: str, config: Dict, code: str, shop_id: str = None) -> Dict:
        """
        Exchanges authorization code for access tokens.
        """
        if module_id == 'shopee' or 'shopee' in module_id:
            return self._exchange_shopee_token(config, code, shop_id)
        elif module_id == 'mercadolivre':
            return self._exchange_mercadolivre_token(config, code)
        elif module_id == 'bling':
            return self._exchange_bling_token(config, code)
        # Add other platforms
        return {}

    def _exchange_bling_token(self, config: Dict, code: str) -> Dict:
        import base64
        client_id = config.get('client_id')
        client_secret = config.get('client_secret')
        
        if not client_id or not client_secret:
            raise ValueError("Bling client_id or client_secret missing.")

        url = "https://www.bling.com.br/Api/v3/oauth/token"
        
        # Bling V3 uses Basic Auth for token exchange
        auth_str = f"{client_id}:{client_secret}"
        auth_b64 = base64.b64encode(auth_str.encode()).decode()
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {auth_b64}"
        }
        
        payload = {
            "grant_type": "authorization_code",
            "code": code
        }
        
        resp = requests.post(url, data=payload, headers=headers)
        data = resp.json()
        
        if data.get("error"):
            raise Exception(f"Bling Auth Error: {data.get('error_description', data.get('error'))}")
            
        return {
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "expires_in": data.get("expires_in"),
            "raw_response": data
        }

    def _exchange_mercadolivre_token(self, config: Dict, code: str) -> Dict:
        client_id = config.get('client_id')
        client_secret = config.get('client_secret')
        
        if not client_id or not client_secret:
            raise ValueError("Mercado Livre client_id or client_secret missing.")

        url = "https://api.mercadolibre.com/oauth/token"
        payload = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": config.get('redirect_uri') # Passed in config during init_auth
        }
        
        resp = requests.post(url, data=payload)
        data = resp.json()
        
        if data.get("error"):
            raise Exception(f"ML Auth Error: {data.get('message', data.get('error'))}")
            
        return {
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "expires_in": data.get("expires_in"),
            "raw_response": data
        }

    def _exchange_shopee_token(self, config: Dict, code: str, shop_id_raw: str) -> Dict:
        """
        Exchanges code for token using Shopee V2 API.
        """
        partner_id_raw = config.get('partner_id')
        partner_key = config.get('partner_key', '')
        
        if not partner_id_raw or not partner_key:
            raise ValueError("Configuração incompleta: partner_id ou partner_key ausentes.")

        partner_id = int(partner_id_raw)
        shop_id = int(shop_id_raw) if shop_id_raw else 0
        
        timestamp = int(time.time())
        path = "/api/v2/auth/token/get"
        
        # V2 Sign: hmac-sha256(partner_key, partner_id + path + timestamp)
        base_string = f"{partner_id}{path}{timestamp}"
        sign = hmac.new(
            partner_key.encode('utf-8'),
            base_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        url = f"https://partner.shopeemobile.com{path}?partner_id={partner_id}&timestamp={timestamp}&sign={sign}"
        
        payload = {
            "code": code,
            "shop_id": shop_id,
            "partner_id": partner_id
        }
        
        resp = requests.post(url, json=payload)
        data = resp.json()
        
        if data.get("error"):
            raise Exception(f"Shopee Auth Error: {data.get('message')}")
            
        return {
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "expires_in": data.get("expire_in"),
            "raw_response": data
        }

    def refresh_access_token(self, module_id: str, integration: Dict) -> Dict:
        """
        Refreshes the access token using the refresh token.
        """
        config = integration.get("config") or {}
        credentials = integration.get("credentials") or {}
        refresh_token = integration.get("refresh_token") or credentials.get("refresh_token")
        
        if not refresh_token:
            raise ValueError("No refresh token available")

        if module_id == 'shopee' or 'shopee' in module_id:
            return self._refresh_shopee_token(config, credentials, refresh_token)
        elif module_id == 'mercadolivre':
            return self._refresh_mercadolivre_token(config, refresh_token)
        elif module_id == 'bling':
            return self._refresh_bling_token(config, refresh_token)
            
        raise ValueError(f"Refresh not implemented for {module_id}")

    def _refresh_shopee_token(self, config: Dict, credentials: Dict, refresh_token: str) -> Dict:
        import os
        partner_id_raw = config.get('partner_id') or credentials.get('partner_id') or os.getenv('SHOPEE_PARTNER_ID')
        partner_key = config.get('partner_key') or credentials.get('partner_key') or os.getenv('SHOPEE_PARTNER_KEY')
        shop_id_raw = config.get('shop_id') or credentials.get('shop_id')
        
        if not partner_id_raw or not partner_key:
            raise ValueError("Shopee config incomplete (partner_id, partner_key)")

        partner_id = int(partner_id_raw)
        shop_id = int(shop_id_raw) if shop_id_raw else 0
        
        timestamp = int(time.time())
        path = "/api/v2/auth/access_token/get"
        
        # V2 Sign: hmac-sha256(partner_key, partner_id + path + timestamp)
        base_string = f"{partner_id}{path}{timestamp}"
        sign = hmac.new(
            partner_key.encode('utf-8'),
            base_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        url = f"https://partner.shopeemobile.com{path}?partner_id={partner_id}&timestamp={timestamp}&sign={sign}"
        
        payload = {
            "refresh_token": refresh_token,
            "shop_id": shop_id,
            "partner_id": partner_id
        }
        
        resp = requests.post(url, json=payload)
        data = resp.json()
        
        if data.get("error"):
            raise Exception(f"Shopee Refresh Error: {data.get('message')}")
            
        return {
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "expires_in": data.get("expire_in"),
            "raw_response": data
        }

    def _refresh_mercadolivre_token(self, config: Dict, refresh_token: str) -> Dict:
        client_id = config.get('client_id')
        client_secret = config.get('client_secret')
        
        url = "https://api.mercadolibre.com/oauth/token"
        payload = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token
        }
        
        resp = requests.post(url, data=payload)
        data = resp.json()
        
        if data.get("error"):
            raise Exception(f"ML Refresh Error: {data.get('message', data.get('error'))}")
            
        return {
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "expires_in": data.get("expires_in"),
            "raw_response": data
        }

    def _refresh_bling_token(self, config: Dict, refresh_token: str) -> Dict:
        import base64
        client_id = config.get('client_id')
        client_secret = config.get('client_secret')
        
        url = "https://www.bling.com.br/Api/v3/oauth/token"
        
        auth_str = f"{client_id}:{client_secret}"
        auth_b64 = base64.b64encode(auth_str.encode()).decode()
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {auth_b64}"
        }
        
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        }
        
        resp = requests.post(url, data=payload, headers=headers)
        data = resp.json()
        
        if data.get("error"):
            raise Exception(f"Bling Refresh Error: {data.get('error_description', data.get('error'))}")
            
        return {
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "expires_in": data.get("expires_in"),
            "raw_response": data
        }

    def call_test_endpoint(self, module_id: str, integration: Dict) -> Dict:
        """
        Executes a test call to the platform's test endpoint.
        """
        from nistiprint_shared.services.integration_module_service import integration_module_service
        module = integration_module_service.get_module_by_id(module_id)
        
        if not module:
            raise ValueError(f"Module {module_id} not found")
            
        test_path = module.data_mapping_spec.get("test_endpoint")
        if not test_path:
            raise ValueError(f"No test endpoint defined for {module_id}")

        access_token = integration.get("access_token")
        if not access_token:
            # Fallback to credentials JSONB if not in top-level
            access_token = (integration.get("credentials") or {}).get("access_token")
            
        if not access_token:
            raise ValueError("No access token found for integration")

        if module_id == 'shopee' or 'shopee' in module_id:
            return self._test_shopee(integration, test_path, access_token)
        elif module_id == 'mercadolivre':
            return self._test_mercadolivre(test_path, access_token)
        elif module_id == 'bling':
            return self._test_bling(test_path, access_token)
            
        return {"error": "Platform testing not implemented yet"}

    def _test_bling(self, path: str, access_token: str) -> Dict:
        import requests
        url = f"https://www.bling.com.br/Api/v3{path}"
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = requests.get(url, headers=headers)
        return resp.json()

    def _test_shopee(self, integration: Dict, path: str, access_token: str) -> Dict:
        import hmac
        import hashlib
        import time
        import requests
        
        config = integration.get("config") or {}
        credentials = integration.get("credentials") or {}
        
        partner_id_raw = config.get("partner_id") or credentials.get("partner_id")
        partner_key = config.get("partner_key") or credentials.get("partner_key")
        shop_id_raw = config.get("shop_id") or credentials.get("shop_id")
        
        if not partner_id_raw or not partner_key or not shop_id_raw:
            raise ValueError("Shopee configuration (partner_id, partner_key, shop_id) incomplete for testing")
            
        partner_id = int(partner_id_raw)
        shop_id = int(shop_id_raw)
        timestamp = int(time.time())
        
        # V2 Signature for common APIs: hmac-sha256(partner_key, partner_id + path + timestamp + access_token + shop_id)
        base_string = f"{partner_id}{path}{timestamp}{access_token}{shop_id}"
        sign = hmac.new(
            partner_key.encode('utf-8'),
            base_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        url = f"https://partner.shopeemobile.com{path}"
        params = {
            "partner_id": partner_id,
            "timestamp": timestamp,
            "sign": sign,
            "access_token": access_token,
            "shop_id": shop_id
        }
        
        resp = requests.get(url, params=params)
        return resp.json()

    def _test_mercadolivre(self, path: str, access_token: str) -> Dict:
        import requests
        url = f"https://api.mercadolibre.com{path}"
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = requests.get(url, headers=headers)
        return resp.json()

platform_auth_service = PlatformAuthService()

