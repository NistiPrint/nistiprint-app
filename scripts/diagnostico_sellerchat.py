"""
Sonda do endpoint SellerChat `get_message` da Shopee.

Uso:
    /opt/nistiprint/.venv/bin/python scripts/diagnostico_sellerchat.py [--conversa ID]

Existe porque o backfill devolveu HTTP 491 em todas as conversas e 491 nao e um
codigo padrao: quem sabe o motivo e o corpo da resposta, que o cliente descartava.

A sonda separa duas hipoteses que produzem a mesma falha:

  A) o endpoint ou a permissao estao errados
     -> a chamada A (sem message_id_list) tambem falha
  B) so a codificacao do parametro de lista esta errada
     -> a chamada A passa e as variantes B/C/D e que falham

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


def _mostrar(rotulo, resposta):
    corpo = (resposta.text or "")[:1200]
    print(f"\n--- {rotulo}")
    print(f"    HTTP {resposta.status_code}")
    for cabecalho in ("Retry-After", "X-Ratelimit-Remaining", "Content-Type"):
        if cabecalho in resposta.headers:
            print(f"    {cabecalho}: {resposta.headers[cabecalho]}")
    print(f"    corpo: {corpo or '(vazio)'}")


def _rodar(args):
    _carregar_env()
    import requests
    from nistiprint_shared.database.supabase_db_service import supabase_db
    from nistiprint_shared.services.credential_resolver_service import credential_resolver_service
    from nistiprint_shared.services.platform_drivers.shopee import _generate_sign, _resolve_credentials

    # Uma conversa com lacuna declarada, e os IDs que faltam nela.
    consulta = (supabase_db.table("conversas_chat_shopee")
                .select("conversation_id,installed_integration_id,ids_nao_recuperados")
                .order("ultima_mensagem_em", desc=True).limit(1))
    if args.conversa:
        consulta = consulta.eq("conversation_id", int(args.conversa))
    else:
        consulta = consulta.eq("status_completude", "pendente")
    linhas = consulta.execute().data or []
    if not linhas:
        logger.error("Nenhuma conversa pendente encontrada.")
        return 1
    alvo = linhas[0]
    conversation_id = str(alvo["conversation_id"])
    ids = [str(v) for v in (alvo.get("ids_nao_recuperados") or [])][:3]
    print(f"conversa={conversation_id}  ids_ausentes={ids}")

    instalacoes = (supabase_db.table("installed_integrations")
                   .select("id,module_id,config,credentials,is_active,access_token,refresh_token")
                   .eq("id", int(alvo["installed_integration_id"])).eq("is_active", True)
                   .limit(1).execute().data or [])
    if not instalacoes:
        logger.error("Integracao %s nao encontrada ou inativa.", alvo["installed_integration_id"])
        return 1
    integration = credential_resolver_service.hydrate_integration(instalacoes[0])

    resolvido = _resolve_credentials(integration)
    faltando = [k for k, v in resolvido.items() if not v]
    if faltando:
        logger.error("Credenciais incompletas: %s", faltando)
        return 1
    partner_id, shop_id = int(resolvido["partner_id"]), int(resolvido["shop_id"])
    print(f"partner_id={partner_id}  shop_id={shop_id}  "
          f"access_token={'presente' if resolvido['access_token'] else 'AUSENTE'}")

    def base():
        timestamp = int(time.time())
        return {
            "partner_id": partner_id, "timestamp": timestamp,
            "sign": _generate_sign(partner_id, resolvido["partner_key"], PATH, timestamp,
                                   resolvido["access_token"], shop_id),
            "access_token": resolvido["access_token"], "shop_id": shop_id,
            "conversation_id": conversation_id, "business_type": 0,
        }

    # A) Sem message_id_list. Isola endpoint/permissao da codificacao do parametro.
    params = {**base(), "page_size": 20}
    _mostrar("A) get_message paginado, sem message_id_list", requests.get(f"{HOST}{PATH}", params=params, timeout=15))

    if not ids:
        print("\n(sem ids ausentes nesta conversa; variantes B/C/D ignoradas)")
        return 0

    time.sleep(1)
    # B) Lista como parametros repetidos -- o que o cliente faz hoje.
    params = {**base(), "page_size": len(ids), "message_id_list": ids}
    _mostrar("B) message_id_list como parametros repetidos (comportamento atual)",
             requests.get(f"{HOST}{PATH}", params=params, timeout=15))

    time.sleep(1)
    # C) Lista como JSON.
    params = {**base(), "page_size": len(ids), "message_id_list": json.dumps(ids)}
    _mostrar("C) message_id_list como string JSON",
             requests.get(f"{HOST}{PATH}", params=params, timeout=15))

    time.sleep(1)
    # D) Lista separada por virgula.
    params = {**base(), "page_size": len(ids), "message_id_list": ",".join(ids)}
    _mostrar("D) message_id_list separado por virgula",
             requests.get(f"{HOST}{PATH}", params=params, timeout=15))

    time.sleep(1)
    # E) Repetidos, mas com page_size folgado -- descarta page_size pequeno como causa.
    params = {**base(), "page_size": 20, "message_id_list": ids}
    _mostrar("E) parametros repetidos com page_size=20",
             requests.get(f"{HOST}{PATH}", params=params, timeout=15))

    print("\nLeitura: se (A) passar e B/C/D falharem, o problema e so a codificacao "
          "da lista -- adote a variante que responder 200. Se (A) tambem falhar, o "
          "problema e endpoint, permissao do app ou token, e o corpo acima diz qual.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--conversa", type=int, default=None,
                        help="conversation_id especifica; por padrao usa a pendente mais recente")
    return _rodar(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
