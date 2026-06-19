import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nistiprint_shared.services import bling_order_processing_service as service


class TestBlingOrderProcessingService(unittest.TestCase):
    def test_materialize_marketplace_direct_order_marks_personalized_flags(self):
        detalhe = {
            "id": 987,
            "numero": "466320",
            "numeroLoja": "260618E2UXVM97",
            "loja": {"id": "204047801"},
            "contato": {"nome": "Sandro Gomes"},
            "situacao": {"id": 2},
            "itens": [
                {
                    "id": 1,
                    "descricao": "Caderneta de Vacinacao Personalizado C/ Nome",
                    "quantidade": 1,
                    "valor": 10,
                }
            ],
        }

        fake_client = MagicMock()
        fake_client.get_order_numbers_by_store_numbers.return_value = [{"id": 987, "numero": "466320"}]

        with patch("nistiprint_shared.services.bling.bling_client.BlingClient.create_client_for_integration_id", return_value=fake_client):
            with patch.object(service, "_fetch_bling_order_detail", return_value=detalhe):
                with patch.object(service, "_upsert_pedido_bling", return_value=321):
                    with patch.object(service, "_extract_bling_loja_id", return_value="204047801"):
                        with patch.object(service, "_resolve_canal_venda_id", return_value=27):
                            with patch.object(service, "_classify_fulfillment", return_value=SimpleNamespace(is_fulfillment=False, modalidade="STANDARD")):
                                with patch.object(service, "_classify_flex", return_value=SimpleNamespace(is_flex=False, modalidade="STANDARD")):
                                    with patch.object(service, "_upsert_pedido_master", return_value=26893):
                                        with patch.object(service, "_detect_and_mark_personalized") as detect_mock:
                                            result = service.materialize_marketplace_direct_order(
                                                source="shopee",
                                                external_order_id="260618E2UXVM97",
                                                marketplace_inst={"id": 12, "plataforma_slug": "shopee"},
                                                marketplace_detail={"buyer_username": "bruna.karoline_gomes"},
                                                marketplace_mirror_id=55,
                                                bling_integration_id=99,
                                                bling_loja_id="204047801",
                                            )

        self.assertEqual(result["status"], "success")
        detect_mock.assert_called_once_with(detalhe, 26893)


if __name__ == "__main__":
    unittest.main()
