from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from nistiprint_shared.database.supabase_db_service import supabase_db


logger = logging.getLogger("IntegrationSecretService")


class SecretStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class DecryptedSecret:
    owner_type: str
    owner_id: str
    secret_kind: str
    value: str
    key_version: str
    updated_at: str | None


class IntegrationSecretService:
    def __init__(self) -> None:
        self.schema_name = "private"
        self.table_name = "integration_secret_values"
        self.key_env_prefix = "INTEGRATION_SECRETS_MASTER_KEY_"
        self.default_key_version = "V1"

    def _table(self):
        if not supabase_db._ensure_client():
            raise SecretStorageError("Supabase client indisponivel para secrets.")
        return supabase_db.client.schema(self.schema_name).table(self.table_name)

    def _load_key(self, key_version: str | None = None) -> bytes:
        version = (key_version or self.default_key_version).upper()
        env_name = f"{self.key_env_prefix}{version}"
        raw_value = os.environ.get(env_name)
        if not raw_value:
            raise SecretStorageError(
                f"Chave mestra de secrets ausente: {env_name}."
            )

        try:
            key = base64.b64decode(raw_value)
        except Exception as exc:  # pragma: no cover - defensive
            raise SecretStorageError(
                f"Chave mestra invalida em {env_name}."
            ) from exc

        if len(key) != 32:
            raise SecretStorageError(
                f"Chave mestra invalida em {env_name}: esperado 32 bytes."
            )
        return key

    def encrypt_secret(
        self, value: str, key_version: str | None = None
    ) -> tuple[str, str, str]:
        if value is None:
            raise SecretStorageError("Nao e possivel criptografar secret nulo.")

        version = (key_version or self.default_key_version).upper()
        cipher = AESGCM(self._load_key(version))
        nonce = os.urandom(12)
        ciphertext = cipher.encrypt(nonce, value.encode("utf-8"), None)
        return (
            base64.b64encode(ciphertext).decode("ascii"),
            base64.b64encode(nonce).decode("ascii"),
            version,
        )

    def decrypt_secret(
        self, encrypted_value: str, nonce: str, key_version: str | None = None
    ) -> str:
        version = (key_version or self.default_key_version).upper()
        cipher = AESGCM(self._load_key(version))
        try:
            plaintext = cipher.decrypt(
                base64.b64decode(nonce),
                base64.b64decode(encrypted_value),
                None,
            )
        except Exception as exc:
            raise SecretStorageError("Falha ao descriptografar secret.") from exc
        return plaintext.decode("utf-8")

    def get_secret(
        self, owner_type: str, owner_id: Any, secret_kind: str
    ) -> DecryptedSecret | None:
        response = (
            self._table()
            .select("*")
            .eq("owner_type", owner_type)
            .eq("owner_id", str(owner_id))
            .eq("secret_kind", secret_kind)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None

        row = response.data[0]
        return DecryptedSecret(
            owner_type=row["owner_type"],
            owner_id=str(row["owner_id"]),
            secret_kind=row["secret_kind"],
            value=self.decrypt_secret(
                row["encrypted_value"],
                row["nonce"],
                row.get("key_version"),
            ),
            key_version=row.get("key_version") or self.default_key_version,
            updated_at=row.get("updated_at"),
        )

    def get_secret_map(self, owner_type: str, owner_id: Any) -> dict[str, str]:
        response = (
            self._table()
            .select("*")
            .eq("owner_type", owner_type)
            .eq("owner_id", str(owner_id))
            .execute()
        )
        secrets: dict[str, str] = {}
        for row in response.data or []:
            try:
                secrets[row["secret_kind"]] = self.decrypt_secret(
                    row["encrypted_value"],
                    row["nonce"],
                    row.get("key_version"),
                )
            except SecretStorageError:
                logger.warning(
                    "Falha ao ler secret %s/%s/%s",
                    owner_type,
                    owner_id,
                    row.get("secret_kind"),
                )
        return secrets

    def has_secret(self, owner_type: str, owner_id: Any, secret_kind: str) -> bool:
        response = (
            self._table()
            .select("id")
            .eq("owner_type", owner_type)
            .eq("owner_id", str(owner_id))
            .eq("secret_kind", secret_kind)
            .limit(1)
            .execute()
        )
        return bool(response.data)

    def put_secret(
        self,
        owner_type: str,
        owner_id: Any,
        secret_kind: str,
        value: str,
        *,
        rotated: bool = False,
        key_version: str | None = None,
    ) -> None:
        encrypted_value, nonce, version = self.encrypt_secret(value, key_version)
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "owner_type": owner_type,
            "owner_id": str(owner_id),
            "secret_kind": secret_kind,
            "encrypted_value": encrypted_value,
            "nonce": nonce,
            "key_version": version,
            "updated_at": now,
        }
        if rotated:
            payload["rotated_at"] = now

        existing = (
            self._table()
            .select("id")
            .eq("owner_type", owner_type)
            .eq("owner_id", str(owner_id))
            .eq("secret_kind", secret_kind)
            .limit(1)
            .execute()
        )
        if existing.data:
            (
                self._table()
                .update(payload)
                .eq("id", existing.data[0]["id"])
                .execute()
            )
            return

        payload["created_at"] = now
        self._table().insert(payload).execute()

    def rotate_secret(
        self, owner_type: str, owner_id: Any, secret_kind: str, value: str
    ) -> None:
        self.put_secret(
            owner_type,
            owner_id,
            secret_kind,
            value,
            rotated=True,
        )

    def delete_secret(self, owner_type: str, owner_id: Any, secret_kind: str) -> None:
        (
            self._table()
            .delete()
            .eq("owner_type", owner_type)
            .eq("owner_id", str(owner_id))
            .eq("secret_kind", secret_kind)
            .execute()
        )

    def encode_inline_secret(self, value: str, key_version: str | None = None) -> str:
        encrypted_value, nonce, version = self.encrypt_secret(value, key_version)
        return f"{version}:{nonce}:{encrypted_value}"

    def decode_inline_secret(self, encoded: str) -> str | None:
        if not encoded:
            return None
        try:
            version, nonce, encrypted_value = encoded.split(":", 2)
        except ValueError as exc:
            raise SecretStorageError("Secret inline invalido.") from exc
        return self.decrypt_secret(encrypted_value, nonce, version)


integration_secret_service = IntegrationSecretService()
