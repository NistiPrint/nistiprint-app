"""Roteador de provedores de IA."""
import unittest
from unittest.mock import MagicMock, patch

import httpx

from nistiprint_shared.services.ai import (
    AIProviderError,
    AIResponseParseError,
    AIRouter,
    build_provider,
    extract_json,
    validate_model,
)
from nistiprint_shared.services.ai.openrouter_provider import OpenRouterProvider


def _config(**valores):
    return lambda chave, default=None: valores.get(chave, default)


class TestSelecaoDeProvedor(unittest.TestCase):
    def test_default_e_gemini(self):
        router = AIRouter(config_reader=_config())
        s = router.resolve_settings()
        self.assertEqual(s["provider"], "gemini")
        self.assertEqual(s["model"], "gemini-2.0-flash")

    def test_openrouter_auto_por_configuracao(self):
        router = AIRouter(
            config_reader=_config(ia_provider="openrouter", ia_model="openrouter/auto")
        )
        s = router.resolve_settings()
        self.assertEqual(s["provider"], "openrouter")
        self.assertEqual(s["model"], "openrouter/auto")

    def test_trocar_provedor_sem_modelo_usa_default_do_provedor(self):
        router = AIRouter(config_reader=_config(ia_provider="openrouter"))
        self.assertEqual(router.resolve_settings()["model"], "openrouter/auto")

    def test_provedor_desconhecido_cai_no_default(self):
        router = AIRouter(config_reader=_config(ia_provider="skynet"))
        self.assertEqual(router.resolve_settings()["provider"], "gemini")

    def test_fallback_igual_ao_primario_e_ignorado(self):
        router = AIRouter(
            config_reader=_config(ia_provider="gemini", ia_fallback_provider="gemini")
        )
        self.assertIsNone(router.resolve_settings()["fallback_provider"])

    def test_timeout_ilegivel_nao_quebra(self):
        router = AIRouter(config_reader=_config(ia_timeout_seconds="depois"))
        self.assertEqual(router.resolve_settings()["timeout_seconds"], 60.0)


class TestValidacaoDePar(unittest.TestCase):
    """Provedor e modelo sao validados juntos — isolados, ambos parecem ok."""

    def test_modelo_gemini_no_openrouter_e_aceito_como_vendor_model(self):
        # `gemini-2.0-flash` nao tem barra, entao nao passa no formato.
        with self.assertRaises(AIProviderError):
            validate_model("openrouter", "gemini-2.0-flash")

    def test_modelo_openrouter_no_gemini_e_rejeitado(self):
        with self.assertRaises(AIProviderError):
            validate_model("gemini", "openrouter/auto")

    def test_modelo_gemini_invalido_e_rejeitado(self):
        with self.assertRaises(AIProviderError):
            validate_model("gemini", "gemini-1.0-ultra")

    def test_vendor_model_arbitrario_e_aceito_no_openrouter(self):
        validate_model("openrouter", "anthropic/claude-sonnet-4")

    def test_provedor_inexistente(self):
        with self.assertRaises(AIProviderError):
            build_provider("skynet")


class TestFallback(unittest.TestCase):
    def test_fallback_assume_quando_primario_falha(self):
        router = AIRouter(
            config_reader=_config(
                ia_provider="gemini", ia_fallback_provider="openrouter"
            )
        )
        primario = MagicMock()
        primario.complete.side_effect = AIProviderError("sem credencial")
        secundario = MagicMock()
        secundario.complete.return_value = "resposta-do-fallback"

        with patch(
            "nistiprint_shared.services.ai.router.build_provider",
            side_effect=[primario, secundario],
        ):
            resultado = router.complete("sistema", "payload")

        self.assertEqual(resultado, "resposta-do-fallback")
        secundario.complete.assert_called_once()

    def test_sem_fallback_a_falha_propaga(self):
        router = AIRouter(config_reader=_config(ia_provider="gemini"))
        primario = MagicMock()
        primario.complete.side_effect = AIProviderError("sem credencial")
        with patch(
            "nistiprint_shared.services.ai.router.build_provider", return_value=primario
        ):
            with self.assertRaises(AIProviderError):
                router.complete("sistema", "payload")


class TestOpenRouterProvider(unittest.TestCase):
    def _provider(self, response):
        client = MagicMock()
        client.post.return_value = response
        return OpenRouterProvider(model="openrouter/auto", api_key="k", client=client)

    def _resposta(self, status=200, body=None, text=""):
        r = MagicMock()
        r.status_code = status
        r.json.return_value = body or {}
        r.text = text
        return r

    def test_captura_o_modelo_realmente_usado(self):
        """Com `auto`, so a resposta revela quem atendeu."""
        provider = self._provider(
            self._resposta(
                body={
                    "model": "anthropic/claude-sonnet-4",
                    "choices": [{"message": {"content": '{"nome": "Ana"}'}}],
                    "usage": {"total_tokens": 42},
                }
            )
        )
        resp = provider.complete("sistema", "payload")
        self.assertEqual(resp.model_requested, "openrouter/auto")
        self.assertEqual(resp.model_used, "anthropic/claude-sonnet-4")
        self.assertEqual(resp.usage["total_tokens"], 42)
        self.assertEqual(resp.provider, "openrouter")

    def test_sem_credencial_falha_com_mensagem_clara(self):
        provider = OpenRouterProvider(api_key=None, client=MagicMock())
        with self.assertRaises(AIProviderError) as ctx:
            provider.complete("s", "p")
        self.assertIn("OPENROUTER_API_KEY", str(ctx.exception))

    def test_erro_http_vira_erro_de_provedor(self):
        provider = self._provider(self._resposta(status=402, text="sem credito"))
        with self.assertRaises(AIProviderError) as ctx:
            provider.complete("s", "p")
        self.assertIn("402", str(ctx.exception))

    def test_resposta_sem_choices(self):
        provider = self._provider(self._resposta(body={"choices": []}))
        with self.assertRaises(AIProviderError):
            provider.complete("s", "p")

    def test_falha_de_rede_vira_erro_de_provedor(self):
        client = MagicMock()
        client.post.side_effect = httpx.ConnectError("sem rota")
        provider = OpenRouterProvider(api_key="k", client=client)
        with self.assertRaises(AIProviderError):
            provider.complete("s", "p")


class TestExtracaoDeJson(unittest.TestCase):
    """Cada modelo tem seu vicio de formatacao; trocar de provedor multiplica."""

    def test_json_puro(self):
        self.assertEqual(extract_json('{"nome": "Ana"}'), {"nome": "Ana"})

    def test_cerca_com_rotulo(self):
        self.assertEqual(
            extract_json('```json\n{"nome": "Ana"}\n```'), {"nome": "Ana"}
        )

    def test_cerca_sem_rotulo(self):
        self.assertEqual(extract_json('```\n{"nome": "Ana"}\n```'), {"nome": "Ana"})

    def test_prosa_em_volta(self):
        texto = 'Claro! Aqui esta o resultado:\n{"nome": "Ana"}\nEspero ter ajudado.'
        self.assertEqual(extract_json(texto), {"nome": "Ana"})

    def test_lista_no_topo(self):
        self.assertEqual(extract_json('[{"nome": "Ana"}]'), [{"nome": "Ana"}])

    def test_resposta_vazia(self):
        with self.assertRaises(AIResponseParseError):
            extract_json("   ")

    def test_texto_sem_json(self):
        with self.assertRaises(AIResponseParseError):
            extract_json("Nao consegui identificar o nome.")


if __name__ == "__main__":
    unittest.main()
