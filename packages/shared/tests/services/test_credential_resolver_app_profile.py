"""Resolucao do aplicativo OAuth de uma instalacao.

O caso que estes testes existem para impedir: uma instalacao do Mercado Livre
sem `app_profile_id` herdando o aplicativo padrao do modulo. O refresh token do
ML e rotativo — renovar com o aplicativo da outra conta devolve `invalid_grant`
E consome a credencial, exigindo reautorizacao manual.
"""
from unittest import TestCase
from unittest.mock import patch

from nistiprint_shared.services import credential_resolver_service as module
from nistiprint_shared.services.credential_resolver_service import (
    AmbiguousAppProfileError,
    credential_resolver_service,
)

PROFILE_A = {"id": 10, "module_id": "mercadolivre", "name": "ML CNPJ01", "is_active": True}
PROFILE_B = {"id": 11, "module_id": "mercadolivre", "name": "ML CNPJ03", "is_active": True}


def _installation(**overrides):
    base = {
        "id": 7091,
        "module_id": "mercadolivre",
        "config": {},
        "credentials": {},
    }
    base.update(overrides)
    return base


class ResolveAppProfileTest(TestCase):
    def setUp(self):
        module._WARNED_LEGACY_BOOTSTRAP.clear()

    def _resolve(self, installation, profiles, profile_by_id=None):
        with patch.object(
            module.integration_app_profile_service, "list_profiles", return_value=profiles
        ), patch.object(
            module.integration_app_profile_service,
            "get_profile",
            side_effect=lambda pid: (profile_by_id or {}).get(pid),
        ):
            return credential_resolver_service._resolve_app_profile(
                installation, installation["module_id"]
            )

    def test_vinculo_explicito_vence(self):
        resolved = self._resolve(
            _installation(app_profile_id=11),
            [PROFILE_A, PROFILE_B],
            profile_by_id={11: PROFILE_B},
        )
        self.assertEqual(resolved["id"], 11)

    def test_profile_unico_dispensa_vinculo(self):
        resolved = self._resolve(_installation(), [PROFILE_A])
        self.assertEqual(resolved["id"], 10)

    def test_dois_profiles_sem_vinculo_levanta(self):
        with self.assertRaises(AmbiguousAppProfileError) as ctx:
            self._resolve(_installation(), [PROFILE_A, PROFILE_B])
        self.assertEqual(ctx.exception.error_type, "app_profile_ambiguous")
        self.assertEqual(sorted(ctx.exception.candidate_ids), [10, 11])

    def test_profile_inativo_nao_conta_como_candidato(self):
        inativo = {**PROFILE_B, "is_active": False}
        resolved = self._resolve(_installation(), [PROFILE_A, inativo])
        self.assertEqual(resolved["id"], 10)

    def test_sem_profile_algum_devolve_none(self):
        self.assertIsNone(self._resolve(_installation(), []))


class LegacyEnvBootstrapTest(TestCase):
    def setUp(self):
        module._WARNED_LEGACY_BOOTSTRAP.clear()

    def test_ambiente_preenche_enquanto_nao_ha_profile(self):
        with patch.dict(
            module.os.environ,
            {"ML_CNPJ01_CLIENT_ID": "app-a", "ML_CNPJ01_CLIENT_SECRET": "segredo-a"},
            clear=False,
        ):
            resolved = credential_resolver_service._legacy_env_bootstrap(
                "mercadolivre", {}
            )
        self.assertEqual(resolved["client_id"], "app-a")
        self.assertEqual(resolved["client_secret"], "segredo-a")

    def test_segredo_do_profile_nunca_e_sobrescrito_pelo_ambiente(self):
        with patch.dict(
            module.os.environ,
            {"ML_CNPJ01_CLIENT_ID": "app-a", "ML_CNPJ01_CLIENT_SECRET": "segredo-a"},
            clear=False,
        ):
            resolved = credential_resolver_service._legacy_env_bootstrap(
                "mercadolivre", {"client_id": "do-profile", "client_secret": "tambem"}
            )
        self.assertEqual(resolved, {})

    def test_modulo_fora_da_rampa_nao_le_ambiente(self):
        self.assertEqual(
            credential_resolver_service._legacy_env_bootstrap("shopee", {}), {}
        )

    def test_bootstrap_nao_e_alcancado_quando_ha_profile(self):
        """Com profile resolvido, `resolve_for_installation` nem chama o bootstrap."""
        with patch.object(
            module.integration_app_profile_service, "list_profiles", return_value=[PROFILE_A]
        ), patch.object(
            module.integration_secret_service, "get_secret_map", return_value={}
        ), patch.object(
            credential_resolver_service, "_legacy_env_bootstrap"
        ) as bootstrap:
            credential_resolver_service.resolve_for_installation(_installation())
        bootstrap.assert_not_called()
