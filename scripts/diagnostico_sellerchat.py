"""
Sonda do endpoint SellerChat `get_message` da Shopee.

Uso:
    /opt/nistiprint/.venv/bin/python scripts/diagnostico_sellerchat.py [--conversa ID]

A chamada base (sem `message_id_list`) ja respondeu 200 em producao: endpoint,
permissao, token, assinatura, `page_size` e `business_type` estao corretos. O que
falta descobrir e como a Shopee quer o parametro de lista -- tanto a codificacao
quanto a interacao dela com `page_size`, ja que o cliente derivava o `page_size`
do tamanho do lote e pode estar mandando um valor abaixo do minimo aceito.

A sonda tira os IDs de teste da propria resposta da chamada base, entao nunca
mais fica sem o que testar.

Nao grava nada. So imprime status e corpo de cada tentativa.
"""
import argparse
import json
import logging
import os
import sys
import time

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _candidato in (_PROJECT_ROOT, os.path.join(_PROJECT_ROOT, "packages", "shared")):
    if _candidato not in sys.path:
        sys.path.insert(0, _candidato)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("diagnostico_sellerchat")

HOST = "https://partner.shopeemobile.com"
PATH = "/api/v2/sellerchat/get_message"


def _carregar_env():
    caminho = next((c for c in (os.path.join(os.getcwd(), ".env"),
                                os.path.join(_PROJECT_ROOT, ".env")) if os.path.exists(c)), None)
    if not caminho:
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=caminho)
    except ModuleNotFoundError:
        pass


def _resumo(resposta):
    try:
        corpo = resposta.json()
    except ValueError:
        return f"HTTP {resposta.status_code} corpo nao-JSON: {(resposta.text or '')[:200]}"
    erro = str(corpo.get("error") or "")
    if erro:
        return f"HTTP {resposta.status_code} FALHOU  {erro}: {corpo.get('message')}"
    mensagens = ((corpo.get("response") or {}).get("messages")) or []
    return f"HTTP {resposta.status_code} OK       {len(mensagens)} mensagem(ns)"


def _rodar(args):
    _carregar_env()
    import requests
    from nistiprint_shared.database.supabase_db_service import supabase_db
    from nistiprint_shared.services.credential_resolver_service import credential_resolver_service
    from nistiprint_shared.services.platform_drivers.shopee import _generate_sign, _resolve_credentials

    consulta = (supabase_db.table("conversas_chat_shopee")
                .select("conversation_id,installed_integration_id,ids_nao_recuperados")
                .order("ultima_mensagem_em", desc=True).limit(20))
    if args.conversa:
        consulta = consulta.eq("conversation_id", int(args.conversa))
    linhas = consulta.execute().data or []
    # Preferimos uma conversa que declara lacuna: e nela que o parametro importa.
    linhas.sort(key=lambda linha: -len(linha.get("ids_nao_recuperados") or []))
    if not linhas:
        logger.error("Nenhuma conversa encontrada.")
        return 1
    alvo = linhas[0]
    conversation_id = str(alvo["conversation_id"])

    instalacoes = (supabase_db.table("installed_integrations")
                   .select("id,module_id,config,credentials,is_active,access_token,refresh_token")
                   .eq("id", int(alvo["installed_integration_id"])).eq("is_active", True)
                   .limit(1).execute().data or [])
    if not instalacoes:
        logger.error("Integracao %s nao encontrada ou inativa.", alvo["installed_integration_id"])
        return 1
    integration = credential_resolver_service.hydrate_integration(instalacoes[0])
    resolvido = _resolve_credentials(integration)
    if not all(resolvido.values()):
        logger.error("Credenciais incompletas: %s", [k for k, v in resolvido.items() if not v])
        return 1
    partner_id, shop_id = int(resolvido["partner_id"]), int(resolvido["shop_id"])

    def base():
        timestamp = int(time.time())
        return {"partner_id": partner_id, "timestamp": timestamp,
                "sign": _generate_sign(partner_id, resolvido["partner_key"], PATH, timestamp,
                                       resolvido["access_token"], shop_id),
                "access_token": resolvido["access_token"], "shop_id": shop_id,
                "conversation_id": conversation_id, "business_type": 0}

    print(f"\nconversa={conversation_id}  partner_id={partner_id}  shop_id={shop_id}")

    # Chamada base: valida o resto do contrato e fornece IDs reais para testar.
    print("\n=== BASE (sem message_id_list) ===")
    resposta = requests.get(f"{HOST}{PATH}", params={**base(), "page_size": 30}, timeout=15)
    print(f"    {_resumo(resposta)}")
    if resposta.status_code != 200:
        print(f"    corpo: {(resposta.text or '')[:600]}")
        print("\nA chamada base falhou -- o problema nao e o parametro de lista.")
        return 1

    ids = [str(v) for v in (alvo.get("ids_nao_recuperados") or [])][:3]
    if not ids:
        # Sem lacuna declarada, tiramos os IDs de um bundle da propria resposta.
        for mensagem in ((resposta.json().get("response") or {}).get("messages") or []):
            referencias = (mensagem.get("content") or {}).get("messages")
            if mensagem.get("message_type") == "bundle_message" and isinstance(referencias, list):
                ids = [str(v) for v in referencias][:3]
                break
    if not ids:
        print("\nNenhum id de teste disponivel nesta conversa. Rode com --conversa <id>.")
        return 1
    print(f"    ids de teste: {ids}")

    # Matriz: codificacao x page_size. O cliente derivava page_size do tamanho do
    # lote, entao um minimo nao documentado explicaria a falha tanto quanto a
    # codificacao errada.
    variantes = [
        ("A  repetido        page_size=len", ids, len(ids)),
        ("B  virgula         page_size=len", ",".join(ids), len(ids)),
        ("C  virgula         page_size=30", ",".join(ids), 30),
        ("D  virgula         sem page_size", ",".join(ids), None),
        ("E  json            sem page_size", json.dumps(ids), None),
        ("F  json de inteiros sem page_size", "[" + ",".join(ids) + "]", None),
        ("G  repetido        sem page_size", ids, None),
    ]

    print("\n=== VARIANTES DE message_id_list ===")
    for rotulo, valor, page_size in variantes:
        params = {**base(), "message_id_list": valor}
        if page_size is not None:
            params["page_size"] = page_size
        try:
            r = requests.get(f"{HOST}{PATH}", params=params, timeout=15)
            print(f"  {rotulo}  ->  {_resumo(r)}")
        except Exception as exc:
            print(f"  {rotulo}  ->  excecao: {exc}")
        time.sleep(1)

    print("\nAdote a primeira variante que responder OK com mensagens.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--conversa", type=int, default=None,
                        help="conversation_id especifica; por padrao a que tem mais ids ausentes")
    return _rodar(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
