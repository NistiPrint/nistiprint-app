"""
Service for handling platform-specific authentication flows (OAuth, signatures, etc.)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import Any, Dict, Optional
from urllib.parse import quote_plus

import requests

from nistiprint_shared.services.credential_resolver_service import CredentialContext


class PlatformAuthService:
    """
    Handles authentication logic for different platforms.
    """

    def _context_values(self, context: Any) -> tuple[Dict, Dict, Dict]:
        if isinstance(context, CredentialContext):
            return context.config, context.app_secrets, context.installation_secrets
        if isinstance(context, dict) and "app_secrets" in context:
            return (
                dict(context.get("config") or {}),
                dict(context.get("app_secrets") or {}),
                dict(context.get("installation_secrets") or {}),
            )
        return dict(context or {}), dict(context or {}), dict(context or {})

    def generate_pkce_pair(self) -> tuple[str, str]:
        code_verifier = secrets.token_urlsafe(64)
        challenge = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        code_challenge = (
            base64.urlsafe_b64encode(challenge).decode("ascii").rstrip("=")
        )
        return code_verifier, code_challenge

    def generate_auth_url(
        self,
        module_id: str,
        context: Any,
        redirect_uri: str,
        state: str = None,
        code_challenge: str = None,
    ) -> str:
        """
        Generates the authorization URL for a specific platform.
        """
        if module_id == "shopee" or "shopee" in module_id:
            return self._generate_shopee_auth_url(context, redirect_uri, state)
        if module_id == "mercadolivre":
            return self._generate_mercadolivre_auth_url(
                context, redirect_uri, state, code_challenge=code_challenge
            )
        if module_id == "bling":
            return self._generate_bling_auth_url(
                context, redirect_uri, state, code_challenge=code_challenge
            )
        return ""

    def _generate_bling_auth_url(
        self,
        context: Any,
        redirect_uri: str,
        state: str = None,
        code_challenge: str = None,
    ) -> str:
        _config, app_secrets, _install = self._context_values(context)
        client_id = app_secrets.get("client_id")
        if not client_id:
            return ""
        url = (
            "https://www.bling.com.br/Api/v3/oauth/authorize"
            f"?response_type=code&client_id={quote_plus(client_id)}"
            f"&redirect_uri={quote_plus(redirect_uri)}"
        )
        if state:
            url += f"&state={state}"
        if code_challenge:
            url += f"&code_challenge_method=S256&code_challenge={code_challenge}"
        return url

    def _generate_shopee_auth_url(
        self, context: Any, redirect_uri: str, state: str = None
    ) -> str:
        """
        Generates Shopee Auth URL V2 with signature.
        """
        _config, app_secrets, _install = self._context_values(context)
        partner_id_raw = app_secrets.get("partner_id") or app_secrets.get("client_id")
        partner_key = app_secrets.get("partner_key", "")

        if not partner_id_raw or not partner_key:
            return ""

        partner_id = int(partner_id_raw)
        base_url = "https://partner.shopeemobile.com/api/v2/shop/auth_partner"

        timestamp = int(time.time())
        path = "/api/v2/shop/auth_partner"
        base_string = f"{partner_id}{path}{timestamp}"
        sign = hmac.new(
            partner_key.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        url = (
            f"{base_url}?partner_id={partner_id}&timestamp={timestamp}"
            f"&sign={sign}&redirect={quote_plus(redirect_uri)}"
        )
        if state:
            url += f"&state={state}"

        return url

    def _generate_mercadolivre_auth_url(
        self,
        context: Any,
        redirect_uri: str,
        state: str = None,
        code_challenge: str = None,
    ) -> str:
        _config, app_secrets, _install = self._context_values(context)
        client_id = app_secrets.get("client_id")
        if not client_id:
            return ""
        url = (
            "https://auth.mercadolibre.com.br/authorization"
            f"?response_type=code&client_id={quote_plus(client_id)}"
            f"&redirect_uri={quote_plus(redirect_uri)}"
        )
        if state:
            url += f"&state={state}"
        if code_challenge:
            url += f"&code_challenge_method=S256&code_challenge={code_challenge}"
        return url

    def exchange_code_for_token(
        self,
        module_id: str,
        context: Any,
        code: str,
        shop_id: str = None,
        redirect_uri: str = None,
        code_verifier: str = None,
    ) -> Dict:
        """
        Exchanges authorization code for access tokens.
        """
        if module_id == "shopee" or "shopee" in module_id:
            return self._exchange_shopee_token(context, code, shop_id)
        if module_id == "mercadolivre":
            return self._exchange_mercadolivre_token(
                context,
                code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
            )
        if module_id == "bling":
            return self._exchange_bling_token(
                context,
                code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
            )
        return {}

    def _exchange_bling_token(
        self,
        context: Any,
        code: str,
        redirect_uri: str = None,
        code_verifier: str = None,
    ) -> Dict:
        config, app_secrets, _install = self._context_values(context)
        client_id = app_secrets.get("client_id") or config.get("client_id")
        client_secret = app_secrets.get("client_secret") or config.get("client_secret")

        if not client_id or not client_secret:
            raise ValueError("Bling client_id or client_secret missing.")

        url = "https://www.bling.com.br/Api/v3/oauth/token"
        auth_str = f"{client_id}:{client_secret}"
        auth_b64 = base64.b64encode(auth_str.encode()).decode()

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {auth_b64}",
        }

        payload = {
            "grant_type": "authorization_code",
            "code": code,
        }
        if redirect_uri:
            payload["redirect_uri"] = redirect_uri
        if code_verifier:
            payload["code_verifier"] = code_verifier

        resp = requests.post(url, data=payload, headers=headers)
        data = resp.json()

        if data.get("error"):
            raise Exception(
                f"Bling Auth Error: {data.get('error_description', data.get('error'))}"
            )

        return {
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "expires_in": data.get("expires_in"),
            "user_id": data.get("user_id"),
            "raw_response": data,
        }

    def _exchange_mercadolivre_token(
        self,
        context: Any,
        code: str,
        redirect_uri: str = None,
        code_verifier: str = None,
    ) -> Dict:
        config, app_secrets, _install = self._context_values(context)
        client_id = app_secrets.get("client_id") or config.get("client_id")
        client_secret = app_secrets.get("client_secret") or config.get("client_secret")

        if not client_id or not client_secret:
            raise ValueError("Mercado Livre client_id or client_secret missing.")

        url = "https://api.mercadolibre.com/oauth/token"
        payload = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri or config.get("redirect_uri"),
        }
        if code_verifier:
            payload["code_verifier"] = code_verifier

        resp = requests.post(url, data=payload)
        data = resp.json()

        if data.get("error"):
            raise Exception(f"ML Auth Error: {data.get('message', data.get('error'))}")

        return {
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "expires_in": data.get("expires_in"),
            "raw_response": data,
        }

    def _exchange_shopee_token(
        self, context: Any, code: str, shop_id_raw: str
    ) -> Dict:
        """
        Exchanges code for token using Shopee V2 API.
        """
        config, app_secrets, _install = self._context_values(context)
        partner_id_raw = app_secrets.get("partner_id") or config.get("partner_id")
        partner_key = app_secrets.get("partner_key") or config.get("partner_key", "")

        if not partner_id_raw or not partner_key:
            raise ValueError(
                "Configuracao incompleta: partner_id ou partner_key ausentes."
            )

        partner_id = int(partner_id_raw)
        shop_id = int(shop_id_raw) if shop_id_raw else 0

        timestamp = int(time.time())
        path = "/api/v2/auth/token/get"
        base_string = f"{partner_id}{path}{timestamp}"
        sign = hmac.new(
            partner_key.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        url = (
            "https://partner.shopeemobile.com"
            f"{path}?partner_id={partner_id}&timestamp={timestamp}&sign={sign}"
        )

        payload = {
            "code": code,
            "shop_id": shop_id,
            "partner_id": partner_id,
        }

        resp = requests.post(url, json=payload)
        data = resp.json()

        if data.get("error"):
            raise Exception(f"Shopee Auth Error: {data.get('message')}")

        return {
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "expires_in": data.get("expire_in"),
            "shop_id": shop_id_raw or data.get("shop_id"),
            "raw_response": data,
        }

    def resolve_account_identity(
        self, module_id: str, tokens: Dict, explicit_identifier: str = None
    ) -> Optional[str]:
        """
        Returns the marketplace account identifier available after OAuth.
        """
        if explicit_identifier:
            return str(explicit_identifier).strip()

        raw_response = tokens.get("raw_response") or {}
        module = str(module_id or "").lower()
        if module == "shopee" or "shopee" in module:
            value = (
                tokens.get("shop_id")
                or raw_response.get("shop_id")
                or raw_response.get("shopid")
            )
            return str(value).strip() if value not in (None, "") else None

        if module == "mercadolivre":
            value = (
                tokens.get("user_id")
                or raw_response.get("user_id")
                or raw_response.get("seller_id")
            )
            if value not in (None, ""):
                return str(value).strip()

            access_token = tokens.get("access_token")
            if not access_token:
                return None
            try:
                resp = requests.get(
                    "https://api.mercadolibre.com/users/me",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    profile = resp.json()
                    value = profile.get("id")
                    return str(value).strip() if value not in (None, "") else None
            except Exception:
                return None

        if module == "bling":
            value = raw_response.get("company_id") or raw_response.get("user_id")
            return str(value).strip() if value not in (None, "") else None

        return None

    def refresh_access_token(self, module_id: str, integration: Any) -> Dict:
        """
        Refreshes the access token using the refresh token.
        """
        if isinstance(integration, CredentialContext):
            config = integration.config
            credentials = integration.credentials
            app_secrets = integration.app_secrets
            installation_secrets = integration.installation_secrets
            raw = integration.installation
        else:
            config = integration.get("config") or {}
            credentials = integration.get("credentials") or {}
            app_secrets = integration.get("app_secrets") or {}
            installation_secrets = integration.get("installation_secrets") or {}
            raw = integration
        refresh_token = (
            installation_secrets.get("refresh_token")
            or raw.get("refresh_token")
            or credentials.get("refresh_token")
        )

        if not refresh_token:
            raise ValueError("No refresh token available")

        if module_id == "shopee" or "shopee" in module_id:
            return self._refresh_shopee_token(
                config, credentials, app_secrets, refresh_token
            )
        if module_id == "mercadolivre":
            return self._refresh_mercadolivre_token(
                config, app_secrets, refresh_token
            )
        if module_id == "bling":
            return self._refresh_bling_token(config, app_secrets, refresh_token)

        raise ValueError(f"Refresh not implemented for {module_id}")

    def _refresh_shopee_token(
        self,
        config: Dict,
        credentials: Dict,
        app_secrets: Dict,
        refresh_token: str,
    ) -> Dict:
        partner_id_raw = (
            app_secrets.get("partner_id")
            or config.get("partner_id")
            or credentials.get("partner_id")
            or os.getenv("SHOPEE_PARTNER_ID")
        )
        partner_key = (
            app_secrets.get("partner_key")
            or config.get("partner_key")
            or credentials.get("partner_key")
            or os.getenv("SHOPEE_PARTNER_KEY")
        )
        shop_id_raw = config.get("shop_id") or credentials.get("shop_id")

        if not partner_id_raw or not partner_key:
            raise ValueError("Shopee config incomplete (partner_id, partner_key)")

        partner_id = int(partner_id_raw)
        shop_id = int(shop_id_raw) if shop_id_raw else 0

        timestamp = int(time.time())
        path = "/api/v2/auth/access_token/get"
        base_string = f"{partner_id}{path}{timestamp}"
        sign = hmac.new(
            partner_key.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        url = (
            "https://partner.shopeemobile.com"
            f"{path}?partner_id={partner_id}&timestamp={timestamp}&sign={sign}"
        )

        payload = {
            "refresh_token": refresh_token,
            "shop_id": shop_id,
            "partner_id": partner_id,
        }

        resp = requests.post(url, json=payload)
        data = resp.json()

        if data.get("error"):
            raise Exception(f"Shopee Refresh Error: {data.get('message')}")

        return {
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "expires_in": data.get("expire_in"),
            "raw_response": data,
        }

    def _refresh_mercadolivre_token(
        self, config: Dict, app_secrets: Dict, refresh_token: str
    ) -> Dict:
        client_id = (
            app_secrets.get("client_id")
            or config.get("client_id")
            or os.getenv("ML_CNPJ01_CLIENT_ID")
        )
        client_secret = (
            app_secrets.get("client_secret")
            or config.get("client_secret")
            or os.getenv("ML_CNPJ01_CLIENT_SECRET")
        )

        if not client_id or not client_secret:
            raise ValueError(
                "Credenciais Mercado Livre nao encontradas no profile/config/ambiente."
            )

        url = "https://api.mercadolibre.com/oauth/token"
        payload = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        }

        resp = requests.post(url, data=payload)
        data = resp.json()

        if data.get("error"):
            raise Exception(f"ML Refresh Error: {data.get('message', data.get('error'))}")

        return {
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "expires_in": data.get("expires_in"),
            "raw_response": data,
        }

    def _refresh_bling_token(
        self, config: Dict, app_secrets: Dict, refresh_token: str
    ) -> Dict:
        client_id = app_secrets.get("client_id") or config.get("client_id")
        client_secret = app_secrets.get("client_secret") or config.get("client_secret")

        url = "https://www.bling.com.br/Api/v3/oauth/token"

        auth_str = f"{client_id}:{client_secret}"
        auth_b64 = base64.b64encode(auth_str.encode()).decode()

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {auth_b64}",
        }

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        resp = requests.post(url, data=payload, headers=headers)
        data = resp.json()

        if data.get("error"):
            raise Exception(
                f"Bling Refresh Error: {data.get('error_description', data.get('error'))}"
            )

        return {
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "expires_in": data.get("expires_in"),
            "raw_response": data,
        }

    def call_test_endpoint(self, module_id: str, integration: Dict) -> Dict:
        """
        Executes a test call to the platform's test endpoint.
        """
        from nistiprint_shared.services.integration_module_service import (
            integration_module_service,
        )

        module = integration_module_service.get_module_by_id(module_id)

        if not module:
            raise ValueError(f"Module {module_id} not found")

        test_path = module.data_mapping_spec.get("test_endpoint")
        if not test_path:
            raise ValueError(f"No test endpoint defined for {module_id}")

        access_token = integration.get("access_token")
        if not access_token:
            access_token = (integration.get("credentials") or {}).get("access_token")

        if not access_token:
            raise ValueError("No access token found for integration")

        if module_id == "shopee" or "shopee" in module_id:
            return self._test_shopee(integration, test_path, access_token)
        if module_id == "mercadolivre":
            return self._test_mercadolivre(test_path, access_token)
        if module_id == "bling":
            return self._test_bling(test_path, access_token)

        return {"error": "Platform testing not implemented yet"}

    def _test_bling(self, path: str, access_token: str) -> Dict:
        url = f"https://www.bling.com.br/Api/v3{path}"
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = requests.get(url, headers=headers)
        return resp.json()

    def _test_shopee(self, integration: Dict, path: str, access_token: str) -> Dict:
        config = integration.get("config") or {}
        credentials = integration.get("credentials") or {}
        legacy_credentials = integration.get("_legacy_credentials") or {}

        def find_value(*keys):
            for container in (config, credentials, legacy_credentials, integration):
                if not isinstance(container, dict):
                    continue
                for key in keys:
                    value = container.get(key)
                    if value not in (None, ""):
                        return value
            return None

        def find_account_identifier(kind):
            for container in (config, credentials, legacy_credentials, integration):
                if not isinstance(container, dict):
                    continue
                account_identifiers = container.get("account_identifiers")
                if isinstance(account_identifiers, dict):
                    if (
                        account_identifiers.get("kind") == kind
                        and account_identifiers.get("primary") not in (None, "")
                    ):
                        return account_identifiers.get("primary")
                    if kind == "shop_id" and account_identifiers.get("primary") not in (
                        None,
                        "",
                    ):
                        return account_identifiers.get("primary")
            return None

        partner_id_raw = find_value("partner_id")
        partner_key = find_value("partner_key", "app_secret", "secret")
        shop_id_raw = (
            find_value("shop_id", "shopid", "shop_cipher")
            or find_account_identifier("shop_id")
        )

        if not partner_id_raw or not partner_key or not shop_id_raw:
            missing = []
            if not partner_id_raw:
                missing.append("partner_id")
            if not partner_key:
                missing.append("partner_key")
            if not shop_id_raw:
                missing.append("shop_id")
            hidden_keys = {
                "access_token",
                "refresh_token",
                "partner_key",
                "client_secret",
                "secret",
                "token",
            }
            visible_keys = {
                "config": sorted(
                    k for k in config.keys() if k not in hidden_keys
                )
                if isinstance(config, dict)
                else [],
                "credentials": sorted(
                    k for k in credentials.keys() if k not in hidden_keys
                )
                if isinstance(credentials, dict)
                else [],
                "legacy": sorted(
                    k for k in legacy_credentials.keys() if k not in hidden_keys
                )
                if isinstance(legacy_credentials, dict)
                else [],
                "top_level": sorted(
                    k for k in integration.keys() if k not in hidden_keys
                ),
            }
            raise ValueError(
                "Shopee configuration incomplete for testing. "
                f"Missing: {', '.join(missing)}. Available fields: {visible_keys}"
            )

        partner_id = int(partner_id_raw)
        shop_id = int(shop_id_raw)
        timestamp = int(time.time())
        base_string = f"{partner_id}{path}{timestamp}{access_token}{shop_id}"
        sign = hmac.new(
            partner_key.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        url = f"https://partner.shopeemobile.com{path}"
        params = {
            "partner_id": partner_id,
            "timestamp": timestamp,
            "sign": sign,
            "access_token": access_token,
            "shop_id": shop_id,
        }

        resp = requests.get(url, params=params)
        return resp.json()

    def _test_mercadolivre(self, path: str, access_token: str) -> Dict:
        url = f"https://api.mercadolibre.com{path}"
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            return {"success": True, "message": "Conexao estabelecida com sucesso."}
        return {
            "success": False,
            "message": f"Erro na conexao: {resp.status_code}",
            "details": resp.text,
        }


platform_auth_service = PlatformAuthService()
