from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ProviderSecretFieldSpec:
    secret_kind: str
    label: str
    required: bool = True
    input_type: str = "text"
    placeholder: str | None = None
    help_text: str | None = None
    aliases: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ProviderCredentialSpec:
    module_id: str
    display_name: str
    auth_type: str
    supports_pkce: bool
    account_identifier_kind: str | None
    app_profile_secret_fields: tuple[ProviderSecretFieldSpec, ...]
    installation_secret_kinds: tuple[str, ...]

    @property
    def app_profile_secret_kinds(self) -> tuple[str, ...]:
        return tuple(field.secret_kind for field in self.app_profile_secret_fields)

    def to_dict(self) -> dict:
        return {
            "module_id": self.module_id,
            "display_name": self.display_name,
            "auth_type": self.auth_type,
            "supports_pkce": self.supports_pkce,
            "account_identifier_kind": self.account_identifier_kind,
            "app_profile_secret_fields": [
                field.to_dict() for field in self.app_profile_secret_fields
            ],
            "installation_secret_kinds": list(self.installation_secret_kinds),
        }


PROVIDER_SPECS: dict[str, ProviderCredentialSpec] = {
    "bling": ProviderCredentialSpec(
        module_id="bling",
        display_name="Bling",
        auth_type="oauth2",
        supports_pkce=True,
        account_identifier_kind="cnpj",
        app_profile_secret_fields=(
            ProviderSecretFieldSpec(
                secret_kind="client_id",
                label="Client ID",
                placeholder="Client ID do app no Bling",
            ),
            ProviderSecretFieldSpec(
                secret_kind="client_secret",
                label="Client Secret",
                input_type="password",
                placeholder="Client Secret do app no Bling",
            ),
        ),
        installation_secret_kinds=("access_token", "refresh_token"),
    ),
    "mercadolivre": ProviderCredentialSpec(
        module_id="mercadolivre",
        display_name="Mercado Livre",
        auth_type="oauth2",
        supports_pkce=True,
        account_identifier_kind="user_id",
        app_profile_secret_fields=(
            ProviderSecretFieldSpec(
                secret_kind="client_id",
                label="Client ID",
                placeholder="APP ID / Client ID do Mercado Livre",
            ),
            ProviderSecretFieldSpec(
                secret_kind="client_secret",
                label="Client Secret",
                input_type="password",
                placeholder="Client Secret do Mercado Livre",
            ),
        ),
        installation_secret_kinds=("access_token", "refresh_token"),
    ),
    "shopee": ProviderCredentialSpec(
        module_id="shopee",
        display_name="Shopee",
        auth_type="oauth2_partner",
        supports_pkce=False,
        account_identifier_kind="shop_id",
        app_profile_secret_fields=(
            ProviderSecretFieldSpec(
                secret_kind="partner_id",
                label="Partner ID",
                placeholder="Partner ID da Shopee",
                aliases=("app_id", "client_id"),
            ),
            ProviderSecretFieldSpec(
                secret_kind="partner_key",
                label="Partner Key",
                input_type="password",
                placeholder="Partner Key da Shopee",
                aliases=("app_secret", "client_secret", "secret"),
            ),
        ),
        installation_secret_kinds=("access_token", "refresh_token"),
    ),
    "amazon": ProviderCredentialSpec(
        module_id="amazon",
        display_name="Amazon",
        auth_type="oauth2",
        supports_pkce=False,
        account_identifier_kind="seller_id",
        app_profile_secret_fields=(
            ProviderSecretFieldSpec(
                secret_kind="client_id",
                label="Client ID",
                placeholder="Client ID / LWA App ID",
            ),
            ProviderSecretFieldSpec(
                secret_kind="client_secret",
                label="Client Secret",
                input_type="password",
                placeholder="Client Secret / LWA Client Secret",
            ),
        ),
        installation_secret_kinds=("access_token", "refresh_token"),
    ),
}


def normalize_provider_module_id(module_id: str | None) -> str:
    value = str(module_id or "").strip().lower()
    if "shopee" in value:
        return "shopee"
    return value


def get_provider_spec(module_id: str | None) -> ProviderCredentialSpec | None:
    return PROVIDER_SPECS.get(normalize_provider_module_id(module_id))


def list_provider_specs() -> list[dict]:
    return [spec.to_dict() for spec in PROVIDER_SPECS.values()]

