import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

from nistiprint_shared.services import reliable_ingest_service as svc
from nistiprint_shared.services.webhook_secret_resolver import (
    SecretCandidate,
    WebhookSecretResolver,
    account_id_from_payload,
    is_usable_secret,
)

SECRET_A = "segredo-da-conta-a-0001"
SECRET_B = "segredo-da-conta-b-0002"
COMPANY_A = "fa3c40c3e6ec60129f2c1a063872b816"
COMPANY_B = "03b1405953835db73ec9129779ad5d3d"


def _bling_envelope(secret=None, company_id=COMPANY_A, body=None):
    payload = {"companyId": company_id, "event": "order.updated", "data": {"id": 1}}
    raw = json.dumps(body if body is not None else payload)
    headers = {}
    if secret:
        headers["x-bling-signature-256"] = hmac.new(
            secret.encode(), raw.encode(), hashlib.sha256
        ).hexdigest()
    return {
        "source": "bling", "event_id": "evt-1", "raw_body": raw,
        "parsed_payload": json.loads(raw), "headers": headers,
    }


def _resolver(rows):
    resolver = WebhookSecretResolver()
    patcher = patch.object(resolver, "_load", return_value=rows)
    patcher.start()
    resolver._from_db("bling")
    patcher.stop()
    with patch.object(resolver, "_load", return_value=rows):
        return resolver


class UsableSecretTest(unittest.TestCase):
    def test_placeholder_is_not_a_secret(self):
        # O incidente de 30/07: `.env.example` traz literalmente tres pontos.
        # Copiado para producao, a lista fica nao-vazia e todo evento vira
        # descarte terminal em vez de nao-verificado.
        for value in ("...", "changeme", "TODO", "", "   ", None, "curto"):
            with self.subTest(value=value):
                self.assertFalse(is_usable_secret(value))

    def test_real_secret_is_usable(self):
        self.assertTrue(is_usable_secret(SECRET_A))

    def test_env_secrets_drop_placeholders(self):
        with patch.dict("os.environ", {"INGEST_WEBHOOK_SECRETS_BLING": "..."}):
            self.assertEqual(svc._env_secrets("bling"), [])
        with patch.dict("os.environ", {"INGEST_WEBHOOK_SECRETS_BLING": f'["...","{SECRET_A}"]'}):
            self.assertEqual(svc._env_secrets("bling"), [SECRET_A])


class AccountFromPayloadTest(unittest.TestCase):
    def test_bling_company_id(self):
        self.assertEqual(
            account_id_from_payload("bling", {"companyId": COMPANY_A}), COMPANY_A
        )

    def test_missing_account_is_none(self):
        self.assertIsNone(account_id_from_payload("bling", {}))


class CandidateOrderingTest(unittest.TestCase):
    def test_known_account_narrows_to_a_single_secret(self):
        # Testar todos os segredos deixaria a conta A assinar evento da conta B.
        resolver = _resolver([
            SecretCandidate(SECRET_A, 1, COMPANY_A, "db"),
            SecretCandidate(SECRET_B, 2, COMPANY_B, "db"),
        ])
        chosen = resolver.candidates("bling", account_hint=COMPANY_B)
        self.assertEqual([c.integration_id for c in chosen], [2])

    def test_unknown_account_falls_back_to_all(self):
        resolver = _resolver([
            SecretCandidate(SECRET_A, 1, None, "db"),
            SecretCandidate(SECRET_B, 2, None, "db"),
        ])
        chosen = resolver.candidates("bling", account_hint=COMPANY_A)
        self.assertEqual(len(chosen), 2)

    def test_env_secret_complements_database(self):
        resolver = _resolver([SecretCandidate(SECRET_A, 1, None, "db")])
        chosen = resolver.candidates("bling", env_secrets=[SECRET_B, "..."])
        self.assertEqual([c.origin for c in chosen], ["db", "env"])


class ValidateSignatureTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {"INGEST_WEBHOOK_SECRETS_BLING": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def _with_db(self, rows):
        return patch.object(svc.webhook_secret_resolver, "_load", return_value=rows)

    def test_valid_signature_from_database_secret(self):
        rows = [SecretCandidate(SECRET_A, 1, COMPANY_A, "db")]
        svc.webhook_secret_resolver.invalidate()
        with self._with_db(rows), patch.object(
            svc.webhook_secret_resolver, "remember_account"
        ):
            result = svc.validate_signature(_bling_envelope(SECRET_A))
        self.assertEqual(result.status, "signature_valid")
        self.assertTrue(result.valid)

    def test_wrong_signature_is_discarded(self):
        rows = [SecretCandidate(SECRET_A, 1, COMPANY_A, "db")]
        svc.webhook_secret_resolver.invalidate()
        with self._with_db(rows):
            result = svc.validate_signature(_bling_envelope("outro-segredo-qualquer"))
        self.assertEqual(result.status, "discarded_invalid_signature")
        self.assertTrue(result.terminal)

    def test_no_usable_secret_is_unverified_not_discarded(self):
        # A regressao central: sem segredo utilizavel o evento passa como nao
        # verificado, nunca como invalido. Politica `optional` volta a proteger
        # o caso de erro de configuracao.
        svc.webhook_secret_resolver.invalidate()
        with self._with_db([]), patch.dict(
            "os.environ", {"INGEST_WEBHOOK_SECRETS_BLING": "..."}
        ):
            result = svc.validate_signature(_bling_envelope(SECRET_A))
        self.assertEqual(result.status, "signature_unverified")
        self.assertTrue(result.valid)
        self.assertFalse(result.terminal)
        self.assertEqual(result.reason, "no_usable_secret")

    def test_account_is_learned_only_after_a_valid_signature(self):
        rows = [SecretCandidate(SECRET_A, 1, None, "db")]
        svc.webhook_secret_resolver.invalidate()
        with self._with_db(rows), patch.object(
            svc.webhook_secret_resolver, "remember_account"
        ) as remember:
            svc.validate_signature(_bling_envelope(SECRET_A))
        remember.assert_called_once_with("bling", COMPANY_A, 1)

    def test_account_is_not_learned_from_an_invalid_signature(self):
        rows = [SecretCandidate(SECRET_A, 1, None, "db")]
        svc.webhook_secret_resolver.invalidate()
        with self._with_db(rows), patch.object(
            svc.webhook_secret_resolver, "remember_account"
        ) as remember:
            svc.validate_signature(_bling_envelope("segredo-que-nao-bate"))
        remember.assert_not_called()

    def test_secret_of_another_account_does_not_validate_once_mapped(self):
        # Conta B ja mapeada: um evento que se declara da B mas foi assinado
        # com o segredo da A e rejeitado.
        rows = [
            SecretCandidate(SECRET_A, 1, COMPANY_A, "db"),
            SecretCandidate(SECRET_B, 2, COMPANY_B, "db"),
        ]
        svc.webhook_secret_resolver.invalidate()
        with self._with_db(rows):
            result = svc.validate_signature(
                _bling_envelope(SECRET_A, company_id=COMPANY_B)
            )
        self.assertEqual(result.status, "discarded_invalid_signature")

    def test_policy_disabled_short_circuits(self):
        with patch.dict("os.environ", {"INGEST_SIGNATURE_POLICY_BLING": "disabled"}):
            result = svc.validate_signature(_bling_envelope())
        self.assertEqual(result.status, "signature_disabled")


if __name__ == "__main__":
    unittest.main()
