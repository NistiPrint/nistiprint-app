"""Classificacao, resolucao e persistencia idempotente do SellerChat da Shopee.

O push nao entrega tudo. Mensagens digitadas dentro da sessao do chatbot chegam
como `bundle_message`, que e apenas uma lista de IDs sem corpo, e a resposta
enviada pela loja nao chega de forma alguma -- so o aviso `mark_as_replied`.
Como a Shopee oculta do vendedor a mensagem que passa 12h sem leitura, a
recuperacao precisa acontecer no ingest, em segundos. Deixar para buscar a
conversa no momento em que a IA precisa dela seria tarde demais: a medicao em
producao mostrou 42% das execucoes ocorrendo mais de 12h depois da ultima
mensagem do comprador.

Dois modos de reconciliacao, com custos muito diferentes:

- pontual   `resolver_bundle` -- uma chamada com `message_id_list`, sem
            paginacao. E o caminho quente, disparado pelo proprio bundle, que ja
            informa exatamente quais IDs faltam.
- completo  `reconcile_conversation` -- paginado, parando ao sair da janela de
            sete dias. Usado quando nao se sabe o que falta: resposta da loja,
            varredura de pendencias e backfill.

A janela e de sete dias em todo lugar porque so interessa o pedido mais recente,
que e o que ainda precisa ser atendido.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence
import logging
import os
import time

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.integration_resolution_service import integration_resolution_service
from nistiprint_shared.services.shopee_chat_api import get_all_chat_messages, get_chat_messages

logger = logging.getLogger(__name__)

SHOPEE_CHAT_CODE = 10
SHOPEE_ORDER_CODE = 3

JANELA_DIAS = max(1, int(os.getenv("SELLERCHAT_JANELA_DIAS", "7")))
# A Shopee nao documenta teto para `message_id_list`. 50 e conservador: um bundle
# real tem 3 a 10 mensagens, entao o lote quase nunca e dividido.
MAX_IDS_POR_CHAMADA = max(1, int(os.getenv("SELLERCHAT_MAX_IDS_POR_CHAMADA", "50")))
MAX_PAGINAS = max(1, int(os.getenv("SELLERCHAT_MAX_PAGINAS", "20")))
CACHE_INTEGRACAO_SEGUNDOS = max(30, int(os.getenv("SELLERCHAT_CACHE_INTEGRACAO_SEGUNDOS", "300")))

CONFLITO_MENSAGEM = "installed_integration_id,provider_message_id"

_CACHE_INTEGRACOES: dict[int, tuple[float, dict]] = {}


def _body(payload: dict) -> dict:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def classify_shopee_webhook(payload: dict) -> str:
    if not isinstance(payload, dict):
        return "unknown"
    body = _body(payload)
    code = body.get("code", payload.get("code"))
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = None
    if code == SHOPEE_CHAT_CODE:
        return "chat"
    if code == SHOPEE_ORDER_CODE:
        return "order"
    if {"conversation_id", "message_id", "messages", "message", "msg_id"}.intersection(body):
        return "chat"
    return "unknown"


def extract_chat_push(payload: dict) -> tuple[str, dict]:
    body = _body(payload)
    push_type = str(body.get("type") or "").strip().lower()
    content = body.get("content")
    return push_type, content if isinstance(content, dict) else {}


def extract_chat_provider_event_id(payload: dict) -> str | None:
    push_type, content = extract_chat_push(payload)
    value = content.get("message_id") if push_type == "message" else None
    return str(value) if value not in (None, "") else None


def _iso_timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _inteiro(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return None


def _lotes(itens: Sequence[str], tamanho: int) -> Iterable[list[str]]:
    for inicio in range(0, len(itens), tamanho):
        yield list(itens[inicio:inicio + tamanho])


def _corte_da_janela(janela_dias: int | None = None) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=janela_dias or JANELA_DIAS)


def identidade_do_comprador(raw: dict, shop_id: Any) -> tuple[Any, Any]:
    """Comprador e o participante que nao e a nossa loja.

    Na Shopee o comprador tambem carrega um `shop_id` proprio, entao nao da para
    identificar por presenca do campo: e preciso comparar com o shop da loja.
    Sem esse cuidado, no dia em que a mensagem da loja passar a ser espelhada, o
    remetente seria gravado como comprador.
    """
    nosso = _inteiro(shop_id)
    if nosso is None:
        return None, None
    if _inteiro(raw.get("to_shop_id")) == nosso:
        return raw.get("from_id"), raw.get("from_user_name")
    if _inteiro(raw.get("from_shop_id")) == nosso:
        return raw.get("to_id"), raw.get("to_user_name")
    return None, None


def normalize_chat_message(raw: dict, *, integration_id: int, shop_id: Any = None,
                           webhook_event_id: int | None = None,
                           ingestion_source: str = "webhook") -> dict:
    provider_id = raw.get("id") or raw.get("message_id") or raw.get("msg_id")
    if provider_id in (None, ""):
        raise ValueError("mensagem Shopee sem id")
    created = _iso_timestamp(raw.get("created_timestamp") or raw.get("created_at") or raw.get("timestamp"))
    return {
        "id": str(provider_id), "installed_integration_id": integration_id,
        "provider_message_id": str(provider_id), "webhook_event_id": webhook_event_id,
        "shop_id": raw.get("shop_id", shop_id), "request_id": raw.get("request_id"),
        "from_id": raw.get("from_id"), "to_id": raw.get("to_id"),
        "from_shop_id": raw.get("from_shop_id"), "to_shop_id": raw.get("to_shop_id"),
        "from_user_name": raw.get("from_user_name"), "to_user_name": raw.get("to_user_name"),
        "type": raw.get("message_type") or raw.get("type") or "text",
        "conversation_id": str(raw.get("conversation_id")) if raw.get("conversation_id") is not None else None,
        "created_timestamp": created, "created_at": created, "status": raw.get("status"),
        "message_option": raw.get("message_option"), "source": raw.get("source") or ingestion_source,
        "content": raw.get("content"), "faq_info": raw.get("faq_info"),
        "source_content": raw.get("source_content"), "raw_json": raw, "raw_payload": raw,
        "business_type": int(raw.get("business_type") or 0), "region": raw.get("region"),
        "is_in_chatbot_session": raw.get("is_in_chatbot_session"),
        "quoted_msg": raw.get("quoted_msg"), "sub_account_id": raw.get("sub_account_id"),
        "sub_account_name": raw.get("sub_account_name"),
        "shopee_chatbot_replied": raw.get("shopee_chatbot_replied"),
        "received_at": datetime.now(timezone.utc).isoformat(), "ingestion_source": ingestion_source,
    }


class ShopeeChatIngestService:

    # ------------------------------------------------------------------
    # Estado de completude
    # ------------------------------------------------------------------
    def _atualizar_completude(self, conversation_id: Any, *, tentativa: bool = False,
                              sincronizou: bool = False, erro: str | None = None) -> dict:
        """Recalcula o estado da conversa. Nunca levanta.

        Contabilidade de completude nao pode derrubar o ingest: se o recalculo
        falhar, a mensagem ja foi gravada e a varredura reavalia depois.
        """
        cid = _inteiro(conversation_id)
        if cid is None:
            return {}
        try:
            resposta = supabase_db.rpc("recalcular_completude_conversa", {
                "p_conversation_id": cid,
                "p_janela_dias": JANELA_DIAS,
                "p_tentativa": bool(tentativa),
                "p_sincronizou": bool(sincronizou),
                "p_erro": erro,
            }).execute()
            dados = getattr(resposta, "data", None)
            return dados if isinstance(dados, dict) else {}
        except Exception:
            logger.exception("falha ao recalcular completude conversation_id=%s", cid)
            return {}

    def _registrar_identidade(self, conversation_id: Any, integration_id: Any,
                              buyer_id: Any, buyer_username: Any) -> None:
        cid = _inteiro(conversation_id)
        if cid is None:
            return
        campos: dict[str, Any] = {}
        if buyer_id not in (None, "", 0):
            campos["buyer_user_id"] = buyer_id
        if buyer_username not in (None, ""):
            campos["buyer_username"] = buyer_username
        if _inteiro(integration_id) is not None:
            campos["installed_integration_id"] = _inteiro(integration_id)
        if not campos:
            return
        try:
            (supabase_db.table("conversas_chat_shopee").update(campos)
             .eq("conversation_id", cid).execute())
        except Exception:
            logger.exception("falha ao registrar identidade conversation_id=%s", cid)

    def solicitar_sincronizacao(self, conversation_id: Any, *, integration_id: Any = None) -> bool:
        """Marca que a conversa precisa de varredura completa.

        Usado quando o evento avisa que houve mudanca mas nao diz qual: resposta
        da loja, backfill, gate da IA. Pedir e barato; quem paga a chamada e a
        varredura, que agrupa no maximo uma reconciliacao por conversa por ciclo.
        """
        cid = _inteiro(conversation_id)
        if cid is None:
            return False
        linha: dict[str, Any] = {
            "conversation_id": cid,
            "sincronizacao_solicitada_em": datetime.now(timezone.utc).isoformat(),
        }
        if _inteiro(integration_id) is not None:
            linha["installed_integration_id"] = _inteiro(integration_id)
        try:
            (supabase_db.table("conversas_chat_shopee")
             .upsert(linha, on_conflict="conversation_id").execute())
            return True
        except Exception:
            logger.exception("falha ao solicitar sincronizacao conversation_id=%s", cid)
            return False

    def _limpar_solicitacao(self, conversation_id: int) -> None:
        try:
            (supabase_db.table("conversas_chat_shopee")
             .update({"sincronizacao_solicitada_em": None})
             .eq("conversation_id", conversation_id).execute())
        except Exception:
            logger.exception("falha ao limpar solicitacao conversation_id=%s", conversation_id)

    def _adiar_solicitacao(self, conversation_id: int, tentativas: Any) -> None:
        """Empurra a solicitacao para o futuro depois de uma falha.

        Sem isso, uma conversa cuja varredura falha ficaria elegivel a cada ciclo
        e o papel `chatsync` viraria um laco quente contra uma API indisponivel --
        justamente quando ela menos aguenta.
        """
        atraso = min(3600, 30 * (2 ** min(int(_inteiro(tentativas) or 0), 7)))
        quando = datetime.now(timezone.utc) + timedelta(seconds=atraso)
        try:
            (supabase_db.table("conversas_chat_shopee")
             .update({"sincronizacao_solicitada_em": quando.isoformat()})
             .eq("conversation_id", conversation_id).execute())
        except Exception:
            logger.exception("falha ao adiar solicitacao conversation_id=%s", conversation_id)

    # ------------------------------------------------------------------
    # Credenciais
    # ------------------------------------------------------------------
    def _integracao_hidratada(self, integration_id: Any) -> dict | None:
        """Instalacao com credenciais resolvidas, com cache curto.

        O cache existe porque o caminho quente resolve um bundle por push e a
        resolucao de segredos e mais cara que a propria chamada a Shopee. O TTL e
        curto e a entrada e descartada em erro de autenticacao, para que a
        rotacao de token nao fique presa no cache.
        """
        ident = _inteiro(integration_id)
        if ident is None:
            return None
        agora = time.monotonic()
        em_cache = _CACHE_INTEGRACOES.get(ident)
        if em_cache and agora - em_cache[0] < CACHE_INTEGRACAO_SEGUNDOS:
            return em_cache[1]
        try:
            from nistiprint_shared.services.credential_resolver_service import credential_resolver_service
            linhas = (supabase_db.table("installed_integrations")
                      .select("id,module_id,config,credentials,is_active,access_token,refresh_token")
                      .eq("id", ident).eq("is_active", True).limit(1).execute().data or [])
            if not linhas:
                return None
            hidratada = credential_resolver_service.hydrate_integration(linhas[0])
        except Exception:
            logger.exception("falha ao hidratar integracao %s", ident)
            return None
        _CACHE_INTEGRACOES[ident] = (agora, hidratada)
        return hidratada

    def carregar_integracao(self, integration_id: Any) -> dict | None:
        """Instalacao com credenciais, para quem precisa reconciliar de fora."""
        return self._integracao_hidratada(integration_id)

    def _descartar_cache(self, integration_id: Any) -> None:
        ident = _inteiro(integration_id)
        if ident is not None:
            _CACHE_INTEGRACOES.pop(ident, None)

    def _resolver_integracao(self, payload: dict, content: dict,
                             integration_id: int | None) -> dict | None:
        if integration_id is not None:
            return {"id": integration_id, "plataforma_slug": "shopee"}
        # `shop_id` vem 0 dentro do push de SellerChat; o valor util esta no
        # envelope e, em ultimo caso, em `to_shop_id` (a loja e sempre o destino
        # da mensagem do comprador).
        for candidato in (content.get("shop_id"), payload.get("shop_id"), content.get("to_shop_id")):
            if candidato in (None, "", 0, "0"):
                continue
            resolvida = integration_resolution_service.resolve_marketplace_by_shop_id(str(candidato))
            if resolvida:
                return resolvida
        return None

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------
    def _persistir(self, mensagens: Iterable[dict], *, integration_id: int, shop_id: Any,
                   ingestion_source: str, webhook_event_id: int | None = None) -> list[dict]:
        # Deduplica dentro do lote: o Postgres recusa um ON CONFLICT que afete a
        # mesma linha duas vezes, e a paginacao da Shopee pode repetir mensagens
        # entre paginas.
        por_id: dict[str, dict] = {}
        for raw in mensagens:
            if int(raw.get("business_type") or 0) != 0:
                continue
            try:
                linha = normalize_chat_message(
                    raw, integration_id=integration_id, shop_id=shop_id,
                    webhook_event_id=webhook_event_id, ingestion_source=ingestion_source,
                )
            except ValueError:
                logger.warning("mensagem SellerChat sem id descartada conversa=%s",
                               raw.get("conversation_id"))
                continue
            por_id[linha["provider_message_id"]] = linha
        linhas = list(por_id.values())
        if linhas:
            (supabase_db.table("mensagem_chat_shopee")
             .upsert(linhas, on_conflict=CONFLITO_MENSAGEM).execute())
        return linhas

    def _ids_ausentes(self, ids: Sequence[str]) -> list[str]:
        presentes: set[str] = set()
        for lote in _lotes(list(ids), 100):
            linhas = (supabase_db.table("mensagem_chat_shopee").select("id")
                      .in_("id", lote).execute().data or [])
            presentes.update(str(linha["id"]) for linha in linhas)
        return [str(ident) for ident in ids if str(ident) not in presentes]

    # ------------------------------------------------------------------
    # Modo pontual
    # ------------------------------------------------------------------
    def resolver_bundle(self, integration: dict, conversation_id: Any,
                        message_ids: Sequence[Any], *, business_type: int = 0,
                        webhook_event_id: int | None = None,
                        timeout_seconds: float = 10.0) -> dict:
        """Busca por ID as mensagens que um bundle referencia.

        Uma chamada, sem paginacao e sem risco de laco de offset: o bundle ja diz
        exatamente o que falta. E o unico modo rapido o bastante para rodar
        dentro do consumidor da fila de chat.
        """
        integration_id = _inteiro(integration.get("id"))
        cid = _inteiro(conversation_id)
        if integration_id is None or cid is None:
            return {"status": "error", "error_type": "invalid_chat_message",
                    "message": "bundle sem integracao ou conversa"}

        ids = [str(valor).strip() for valor in (message_ids or []) if str(valor or "").strip()]
        if not ids:
            return {"status": "success", "event_status": "bundle_sem_ids",
                    "messages_upserted": 0, "conversation_id": str(cid)}

        try:
            faltantes = self._ids_ausentes(ids)
        except Exception:
            logger.exception("falha ao conferir ids do bundle conversa=%s", cid)
            faltantes = ids
        if not faltantes:
            estado = self._atualizar_completude(cid)
            return {"status": "success", "event_status": "bundle_ja_resolvido",
                    "messages_upserted": 0, "conversation_id": str(cid),
                    "status_completude": estado.get("status_completude")}

        obtidas: list[dict] = []
        for lote in _lotes(faltantes, MAX_IDS_POR_CHAMADA):
            # Sem `page_size`: os ids ja definem o conjunto, e manda-lo junto
            # nao foi validado contra a API.
            pagina = get_chat_messages(integration, str(cid),
                                       message_id_list=lote, business_type=business_type,
                                       timeout_seconds=timeout_seconds)
            if pagina.get("error"):
                if pagina.get("error_type") == "authentication_error":
                    self._descartar_cache(integration_id)
                self._atualizar_completude(cid, tentativa=True,
                                           erro=str(pagina.get("error"))[:500])
                return {"status": "error",
                        "error_type": pagina.get("error_type") or "chat_fetch_failed",
                        "message": pagina.get("error"),
                        "retryable": bool(pagina.get("retryable")),
                        "retry_after": pagina.get("retry_after"),
                        "conversation_id": str(cid),
                        "messages_upserted": 0}
            obtidas.extend(pagina.get("messages") or [])

        linhas = self._persistir(
            obtidas, integration_id=integration_id,
            shop_id=(integration.get("config") or {}).get("shop_id"),
            ingestion_source="sellerchat_api", webhook_event_id=webhook_event_id,
        )
        estado = self._atualizar_completude(cid, tentativa=True, sincronizou=True)
        return {"status": "success", "event_status": "bundle_resolvido",
                "conversation_id": str(cid),
                "messages_fetched": len(obtidas), "messages_upserted": len(linhas),
                "ids_solicitados": len(faltantes),
                "status_completude": estado.get("status_completude"),
                "ids_nao_recuperados": estado.get("ids_nao_recuperados") or []}

    # ------------------------------------------------------------------
    # Modo completo
    # ------------------------------------------------------------------
    def reconcile_conversation(self, integration: dict, conversation_id: str, *,
                               max_pages: int = MAX_PAGINAS,
                               janela_dias: int | None = None) -> dict:
        """Varre a conversa inteira dentro da janela.

        Usado quando nao se sabe o que falta. A paginacao para ao sair da janela
        de sete dias: o historico antigo nao interessa e paginar ate o inicio da
        conversa e exatamente a lentidao que impede fazer isso no caminho quente.
        """
        integration_id = _inteiro(integration.get("id"))
        if integration_id is None:
            return {"status": "error", "error_type": "integration_not_found",
                    "message": "Integracao Shopee sem id"}
        cid = _inteiro(conversation_id)
        corte = _corte_da_janela(janela_dias)
        fetched = get_all_chat_messages(
            integration, str(conversation_id), business_type=0, max_pages=max_pages,
            desde_epoch=int(corte.timestamp()),
        )
        if fetched.get("error"):
            if fetched.get("error_type") == "authentication_error":
                self._descartar_cache(integration_id)
            self._atualizar_completude(cid, tentativa=True, erro=str(fetched.get("error"))[:500])
            return {"status": "error", "error_type": fetched.get("error_type") or "chat_fetch_failed",
                    "message": fetched.get("error"), "retryable": bool(fetched.get("retryable")),
                    "retry_after": fetched.get("retry_after"),
                    "conversation_id": str(conversation_id),
                    "messages_fetched": len(fetched.get("messages") or [])}

        # Grava tudo que veio, inclusive fora da janela: ja foi pago na chamada e
        # o upsert e idempotente. A janela governa a paginacao e o calculo de
        # completude, nao o descarte de dado em maos.
        mensagens = [linha for linha in (fetched.get("messages") or [])
                     if int(linha.get("business_type") or 0) == 0]
        linhas = self._persistir(
            mensagens, integration_id=integration_id,
            shop_id=(integration.get("config") or {}).get("shop_id"),
            ingestion_source="sellerchat_api",
        )
        estado = self._atualizar_completude(cid, tentativa=True, sincronizou=True)
        return {"status": "success", "event_status": "chat_reconciled",
                "messages_fetched": len(mensagens), "messages_upserted": len(linhas),
                "conversation_id": str(conversation_id),
                "parou_na_janela": bool(fetched.get("parou_na_janela")),
                "status_completude": estado.get("status_completude"),
                "ids_nao_recuperados": estado.get("ids_nao_recuperados") or []}

    # ------------------------------------------------------------------
    # Varredura
    # ------------------------------------------------------------------
    def varrer_conversas_pendentes(self, *, limite: int = 25) -> dict:
        """Fecha as lacunas que o caminho quente nao conseguiu fechar.

        Le a fila de `conversas_chat_shopee` e escolhe o modo por informacao
        disponivel: sabendo quais IDs faltam, resolve pontualmente; sem saber,
        varre a janela.
        """
        agora = datetime.now(timezone.utc).isoformat()
        colunas = ("conversation_id,installed_integration_id,ids_nao_recuperados,"
                   "status_completude,sincronizacao_solicitada_em,tentativas")
        candidatas: dict[int, dict] = {}
        try:
            solicitadas = (supabase_db.table("conversas_chat_shopee").select(colunas)
                           .not_.is_("sincronizacao_solicitada_em", "null")
                           .lte("sincronizacao_solicitada_em", agora)
                           .order("sincronizacao_solicitada_em").limit(limite)
                           .execute().data or [])
            vencidas = (supabase_db.table("conversas_chat_shopee").select(colunas)
                        .in_("status_completude", ["pendente", "erro"])
                        .lte("proxima_tentativa_em", agora)
                        .order("proxima_tentativa_em").limit(limite)
                        .execute().data or [])
        except Exception:
            logger.exception("falha ao ler a fila de conversas pendentes")
            return {"status": "error", "error_type": "fila_indisponivel", "processadas": 0}

        for linha in list(solicitadas) + list(vencidas):
            cid = _inteiro(linha.get("conversation_id"))
            if cid is not None and cid not in candidatas:
                candidatas[cid] = linha
            if len(candidatas) >= limite:
                break

        resumo = {"status": "success", "processadas": 0, "completas": 0,
                  "expiradas": 0, "ainda_pendentes": 0, "falhas": 0,
                  "sem_integracao": 0, "mensagens_recuperadas": 0}
        for cid, linha in candidatas.items():
            integration = self._integracao_hidratada(linha.get("installed_integration_id"))
            if not integration:
                resumo["sem_integracao"] += 1
                self._atualizar_completude(cid, tentativa=True, erro="integracao_indisponivel")
                continue

            solicitada = linha.get("sincronizacao_solicitada_em")
            ausentes = linha.get("ids_nao_recuperados") or []
            if solicitada or not ausentes:
                resultado = self.reconcile_conversation(integration, str(cid))
            else:
                resultado = self.resolver_bundle(integration, cid, ausentes)

            resumo["processadas"] += 1
            if resultado.get("status") != "success":
                resumo["falhas"] += 1
                if solicitada:
                    self._adiar_solicitacao(cid, linha.get("tentativas"))
                logger.warning("varredura falhou conversa=%s error_type=%s",
                               cid, resultado.get("error_type"))
                continue

            resumo["mensagens_recuperadas"] += int(resultado.get("messages_upserted") or 0)
            estado = str(resultado.get("status_completude") or "")
            if estado == "completa":
                resumo["completas"] += 1
            elif estado == "expirada":
                resumo["expiradas"] += 1
            else:
                resumo["ainda_pendentes"] += 1
            if solicitada:
                self._limpar_solicitacao(cid)
        return resumo

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------
    def _processar_notificacao(self, payload: dict, content: dict,
                               integration_id: int | None) -> dict:
        tipo = str(content.get("type") or "").strip().lower()
        aninhado = content.get("content") if isinstance(content.get("content"), dict) else {}
        conversation_id = content.get("conversation_id") or aninhado.get("conversation_id")
        cid = _inteiro(conversation_id)

        # `mark_as_replied` e o unico sinal de que a loja respondeu: a Shopee nao
        # faz push da mensagem enviada pelo vendedor. Descartar esse aviso, como
        # se fazia antes, e o motivo de nao haver uma unica mensagem da loja
        # espelhada. Ele nao traz IDs, entao pede varredura completa.
        if tipo != "mark_as_replied" or cid is None:
            return {"status": "skipped", "event_status": "skipped_chat_notification",
                    "provider_topic": content.get("type"), "conversation_id": conversation_id}

        integration = self._resolver_integracao(payload, content, integration_id)
        solicitou = self.solicitar_sincronizacao(
            cid, integration_id=(integration or {}).get("id")
        )
        return {"status": "success",
                "event_status": "chat_sincronizacao_solicitada" if solicitou
                                else "skipped_chat_notification",
                "provider_topic": tipo, "conversation_id": str(cid),
                "marketplace_integration_id": (integration or {}).get("id")}

    def process(self, payload: dict, *, integration_id: int | None = None,
                webhook_event_id: int | None = None) -> dict:
        if classify_shopee_webhook(payload) != "chat":
            return {"status": "skipped", "event_status": "not_chat"}
        push_type, content = extract_chat_push(payload)
        if push_type == "notification":
            return self._processar_notificacao(payload, content, integration_id)
        if push_type != "message":
            return {"status": "error", "error_type": "invalid_chat_push_type",
                    "message": "Push SellerChat sem data.type=message"}
        business_type = int(content.get("business_type") or 0)
        if business_type == 11:
            return {"status": "skipped", "event_status": "skipped_affiliate_chat",
                    "conversation_id": content.get("conversation_id")}
        if business_type != 0:
            return {"status": "error", "error_type": "unsupported_business_type",
                    "message": f"business_type SellerChat nao suportado: {business_type}"}

        shop_id = content.get("shop_id") or payload.get("shop_id")
        integration = self._resolver_integracao(payload, content, integration_id)
        if not integration or str(integration.get("plataforma_slug") or "").lower() != "shopee":
            return {"status": "error", "error_type": "integration_not_found",
                    "message": "Shop Shopee sem integracao ativa"}
        if not content.get("message_id") or not content.get("conversation_id"):
            return {"status": "error", "error_type": "invalid_chat_message",
                    "message": "Push SellerChat sem message_id ou conversation_id",
                    "marketplace_integration_id": integration.get("id")}

        rows = [normalize_chat_message(content, integration_id=int(integration["id"]),
                                       shop_id=shop_id, webhook_event_id=webhook_event_id)]
        supabase_db.table("mensagem_chat_shopee").upsert(rows, on_conflict=CONFLITO_MENSAGEM).execute()

        cid = _inteiro(content.get("conversation_id"))
        nosso_shop = payload.get("shop_id") or content.get("to_shop_id")
        buyer_id, buyer_username = identidade_do_comprador(content, nosso_shop)
        self._registrar_identidade(cid, integration.get("id"), buyer_id, buyer_username)

        resultado = {"status": "success", "event_status": "chat_persisted", "messages": len(rows),
                     "marketplace_integration_id": integration.get("id"),
                     "conversation_id": rows[0].get("conversation_id"),
                     "provider_topic": content.get("message_type"),
                     "provider_resource": "chat_message"}

        if str(content.get("message_type") or "").strip().lower() == "bundle_message":
            resultado.update(self._resolver_bundle_do_push(
                integration, cid, content, webhook_event_id=webhook_event_id))
        else:
            estado = self._atualizar_completude(cid)
            resultado["status_completude"] = estado.get("status_completude")
        return resultado

    def _resolver_bundle_do_push(self, integration: dict, cid: int | None, content: dict,
                                 *, webhook_event_id: int | None) -> dict:
        """Resolve o bundle recem-chegado sem deixar a falha derrubar o webhook.

        O push ja esta gravado e a conversa ja consta como pendente. Se a Shopee
        nao responder agora, a varredura tenta de novo com backoff -- devolver
        erro aqui so faria o evento repetir o mesmo caminho e, no limite, ir para
        a DLQ por indisponibilidade de terceiro.
        """
        referencias = content.get("content")
        ids = referencias.get("messages") if isinstance(referencias, dict) else None
        if not isinstance(ids, list) or not ids:
            estado = self._atualizar_completude(cid)
            return {"event_status": "chat_persisted_bundle_sem_ids",
                    "status_completude": estado.get("status_completude")}

        hidratada = self._integracao_hidratada(integration.get("id"))
        if not hidratada:
            estado = self._atualizar_completude(cid, erro="integracao_indisponivel")
            return {"event_status": "chat_persisted_bundle_pendente",
                    "status_completude": estado.get("status_completude"),
                    "bundle_erro": "integracao_indisponivel"}

        try:
            resolucao = self.resolver_bundle(hidratada, cid, ids,
                                             webhook_event_id=webhook_event_id)
        except Exception as exc:
            logger.exception("falha inesperada ao resolver bundle conversa=%s", cid)
            estado = self._atualizar_completude(cid, tentativa=True, erro=str(exc)[:500])
            return {"event_status": "chat_persisted_bundle_pendente",
                    "status_completude": estado.get("status_completude"),
                    "bundle_erro": type(exc).__name__}

        if resolucao.get("status") != "success":
            return {"event_status": "chat_persisted_bundle_pendente",
                    "status_completude": resolucao.get("status_completude"),
                    "bundle_erro": resolucao.get("error_type")}
        return {"event_status": "chat_persisted_bundle_resolvido",
                "bundle_messages_upserted": resolucao.get("messages_upserted", 0),
                "status_completude": resolucao.get("status_completude"),
                "ids_nao_recuperados": resolucao.get("ids_nao_recuperados") or []}


shopee_chat_ingest_service = ShopeeChatIngestService()
