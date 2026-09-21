"""Contrato HTTP da publicacao de demandas de despacho."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routes.despacho as despacho_module  # noqa: E402


class TestPublicarDemandaEndpoint(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="test-secret")
        app.register_blueprint(
            despacho_module.despacho_bp,
            url_prefix="/api/v2/despacho",
        )
        self.client = app.test_client()

    def _publicar(self, body, banco):
        with (
            patch.object(despacho_module, "get_current_user", return_value={"id": 1}),
            patch.object(despacho_module, "supabase_db", banco),
        ):
            return self.client.post("/api/v2/despacho/publicar", json=body)

    def test_grade_intacta_usa_publicacao_comum(self):
        banco = MagicMock()
        banco.rpc.return_value.execute.return_value = SimpleNamespace(data=[{
            "out_demanda_codigo": "D-1",
            "out_total_pedidos": 2,
            "out_total_itens": 3,
        }])

        response = self._publicar({"demanda_id": 10}, banco)

        self.assertEqual(response.status_code, 200)
        banco.rpc.assert_called_once_with("despacho_publicar_demanda", {
            "p_demanda_id": 10,
            "p_user_id": "1",
        })

    def test_grade_editada_usa_rpc_com_controle_de_versao(self):
        banco = MagicMock()
        banco.rpc.return_value.execute.return_value = SimpleNamespace(data=[{
            "out_demanda_codigo": "D-2",
            "out_total_pedidos": 1,
            "out_total_itens": 2,
        }])
        linhas = [{"ordem": 1, "quantidade": 2}]

        response = self._publicar({
            "demanda_id": 11,
            "linhas": linhas,
            "previsao_versao": "abc",
        }, banco)

        self.assertEqual(response.status_code, 200)
        banco.rpc.assert_called_once_with("despacho_publicar_demanda_editada", {
            "p_demanda_id": 11,
            "p_user_id": "1",
            "p_previsao_versao": "abc",
            "p_linhas": linhas,
        })

    def test_rpc_ausente_nao_e_mascarada_como_escopo_alterado(self):
        banco = MagicMock()
        banco.rpc.return_value.execute.side_effect = RuntimeError(
            "Could not find function with parameter p_previsao_versao"
        )

        response = self._publicar({
            "demanda_id": 12,
            "linhas": [{"ordem": 1, "quantidade": 1}],
            "previsao_versao": "abc",
        }, banco)

        self.assertEqual(response.status_code, 500)
        self.assertIn("Could not find function", response.get_json()["error"])

    def test_conflito_real_de_escopo_continua_sendo_409(self):
        banco = MagicMock()
        banco.rpc.return_value.execute.side_effect = RuntimeError(
            "escopo mudou desde a previsao"
        )

        response = self._publicar({
            "demanda_id": 13,
            "linhas": [{"ordem": 1, "quantidade": 1}],
            "previsao_versao": "abc",
        }, banco)

        self.assertEqual(response.status_code, 409)
        self.assertIn("escopo mudou", response.get_json()["error"].lower())


if __name__ == "__main__":
    unittest.main()
