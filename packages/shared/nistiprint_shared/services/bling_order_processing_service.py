import requests
import json
import logging
from datetime import datetime, timezone
from nistiprint_shared.services.conta_bling_service import conta_bling_service
from nistiprint_shared.database.database import db
from nistiprint_shared.database.supabase_db_service import get_db_session, supabase_db
from nistiprint_shared.database.supabase_db_service import get_current_database_mode
from nistiprint_shared.models.bling_pedidos import BlingPedidos
from nistiprint_shared.models.bling_pedido_itens import BlingPedidoItens
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.database.supabase_db_service import get_db_session
from nistiprint_shared.database.supabase_db_service import get_current_database_mode
from nistiprint_shared.models.bling_pedidos import BlingPedidos
from nistiprint_shared.models.bling_pedido_itens import BlingPedidoItens
from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
from nistiprint_shared.services import flex_classifier_service
from nistiprint_shared.services.platform_drivers import shopee as shopee_driver

logger = logging.getLogger(__name__)

class BlingOrderProcessingService:
    """
    Service to process Bling order webhooks, applying business logic
    and saving valid orders to the database using the new refactored model.
    """

    def __init__(self):
        # ID da Conta Bling 01 conforme solicitado (ID exato)
        self.BLING_ACCOUNT_01_ID = "4LkzB9yWc07whoPi4IbT"
        self._status_mapping_cache = {}
        self.supabase = supabase_db
        # Lazy load accounts to avoid circular dependencies
        self._bling_antiga_account = None
        self._bling_nova_account = None

    def _get_bling_status_mapping(self, situacao_id):
        """Resolve o comportamento do status Bling via tabela parametrizavel, com fallback local."""
        fallback = {
            6: {
                'external_status_name': 'Em Aberto',
                'internal_situacao_pedido_id': 1,
                'triggers_demand_consolidation': False,
                'config': {'action': 'sync'},
            },
            15: {
                'external_status_name': 'Em Andamento',
                'internal_situacao_pedido_id': 2,
                'triggers_demand_consolidation': True,
                'config': {'action': 'sync_and_consolidate'},
            },
            9: {
                'external_status_name': 'Atendido',
                'internal_situacao_pedido_id': 5,
                'triggers_demand_consolidation': False,
                'config': {'action': 'update_legacy'},
            },
            12: {
                'external_status_name': 'Cancelado',
                'internal_situacao_pedido_id': 7,
                'triggers_demand_consolidation': False,
                'config': {'action': 'cancel'},
            },
            24: {
                'external_status_name': 'Verificado',
                'internal_situacao_pedido_id': 4,
                'triggers_demand_consolidation': False,
                'config': {'action': 'update_legacy'},
            },
        }

        try:
            status_id = int(situacao_id)
        except (TypeError, ValueError):
            return None

        cache_key = f"bling:{status_id}"
        if cache_key in self._status_mapping_cache:
            return self._status_mapping_cache[cache_key]

        mapping = None
        try:
            result = supabase_db.table('integration_status_mappings').select('*') \
                .eq('module_id', 'bling') \
                .eq('external_status_id', str(status_id)) \
                .eq('is_active', True) \
                .execute()
            rows = result.data or []
            mapping = next((row for row in rows if row.get('integration_id') is None), rows[0] if rows else None)
        except Exception as e:
            print(f"⚠️ Falha ao carregar integration_status_mappings para Bling status {status_id}: {e}")

        if not mapping:
            mapping = fallback.get(status_id)

        if mapping:
            self._status_mapping_cache[cache_key] = mapping
        return mapping

    def _get_status_action(self, status_mapping):
        if not status_mapping:
            return None
        config = status_mapping.get('config') or {}
        action = config.get('action')
        if action:
            return action

        internal_status_id = status_mapping.get('internal_situacao_pedido_id')
        if status_mapping.get('triggers_demand_consolidation'):
            return 'sync_and_consolidate'
        if internal_status_id in (1, 2):
            return 'sync'
        if internal_status_id in (4, 5):
            return 'update_legacy'
        if internal_status_id == 7:
            return 'cancel'
        return None

    def _get_bling_client_for_details(self):
        """Retorna um BlingClient configurado para a Conta 01."""
        from nistiprint_shared.services.bling.bling_client import BlingClient
        from nistiprint_shared.services.conta_bling_service import conta_bling_service
        
        # Busca pelo ID exato fornecido pelo usuário na tabela contas_bling
        account = conta_bling_service.get_by_id(self.BLING_ACCOUNT_01_ID)
        
        if account:
            return BlingClient(account)
            
        raise Exception(f"Conta Bling 01 (ID {self.BLING_ACCOUNT_01_ID}) não encontrada para obter detalhes.")

    def process_webhook(self, webhook_payload: dict):
        """
        Main method to process an incoming order webhook.
        """
        from nistiprint_shared.services.order_sync_service import order_sync_service
        from nistiprint_shared.services.integracao_canal_service import integracao_canal_service
        
        # --- LOG PAYLOAD COMPLETO DO WEBHOOK ---
        print(f"DEBUG: [WEBHOOK PAYLOAD] {json.dumps(webhook_payload, indent=2)}")

        # O Bling envia no formato: {"data": {"id": 123, "situacao": {"id": 15, "valor": 3}, ...}}
        data = webhook_payload.get('data', webhook_payload)
        order_id = data.get('id')
        situacao = data.get('situacao', {})
        situacao_id = situacao.get('id')
        status_mapping = self._get_bling_status_mapping(situacao_id)
        status_action = self._get_status_action(status_mapping)
        status_name = (status_mapping or {}).get('external_status_name') or str(situacao_id)

        if not order_id:
            return {"status": "skipped", "message": "No order ID in payload."}

        print(f"📄 Processando Evento Bling - Pedido: {order_id}, Situação: {situacao_id}")

        # REGRAS DE NEGÓCIO POR SITUAÇÃO:

        # 1. Status que exigem detalhes do pedido para sincronizar ou atualizar legado.
        if status_action in ('sync', 'sync_and_consolidate', 'update_legacy'):
            print(f"🚀 Pedido {order_id} em {status_name}. Buscando detalhes para validação...")
            try:
                client = self._get_bling_client_for_details()
                full_order_data = client.get_order(order_id)

                if not full_order_data:
                    return {"status": "failed", "message": f"Could not fetch details for order {order_id}."}

                # --- LOG DADOS CRUS BLING ---
                print(f"DEBUG: [BLING RAW DATA] Pedido {order_id}: {json.dumps(full_order_data, indent=2)}")

                # Extrair loja_id para verificação de origem do pedido
                loja_id = full_order_data.get('loja', {}).get('id')

                sync_result = None

                # Verificar se é Shopee via erp_marketplace_links (fonte de verdade)
                is_shopee = False
                shopee_marketplace_integration_id = None
                try:
                    erp_link_result = supabase_db.table('erp_marketplace_links') \
                        .select('marketplace_integration_id') \
                        .eq('erp_store_id', str(loja_id)) \
                        .execute()
                    if erp_link_result.data:
                        link = erp_link_result.data[0]
                        shopee_marketplace_integration_id = link.get('marketplace_integration_id')
                        # marketplace_integration_id 6 = Shopee
                        is_shopee = (shopee_marketplace_integration_id == 6)
                        print(f"🔍 Loja ID {loja_id} identificado como Shopee via erp_marketplace_links: {is_shopee}")
                except Exception as e:
                    print(f"⚠️ Erro ao verificar erp_marketplace_links: {e}")

                # Status de sincronizacao salvam/atualizam o pedido na base unificada.
                if status_action in ('sync', 'sync_and_consolidate'):
                    canal_config = integracao_canal_service.get_canal_by_bling_loja_id(loja_id)
                    bling_integration_id = canal_config.get('bling_integration_id') if canal_config else None
                    marketplace_integration_id = canal_config.get('marketplace_integration_id') if canal_config else None
                    plataforma = (canal_config.get('plataforma_nome') or '').lower() if canal_config else ''
                    print(f"💾 Sincronizando pedido {order_id} na base unificada (situação {situacao_id})...")

                    # Se for Shopee (via erp_marketplace_links ou canal_config), sincroniza dados do Bling E Shopee
                    if (
                        status_action == 'sync_and_consolidate'
                        and full_order_data.get('numeroLoja')
                        and (is_shopee or plataforma == 'shopee')
                        and (shopee_marketplace_integration_id or marketplace_integration_id)
                    ):
                        # Primeiro sincroniza Bling para garantir numero_pedido e dados do cliente
                        sync_result = order_sync_service.sync_bling_order(
                            full_order_data,
                            bling_integration_id=bling_integration_id
                        )
                        # Depois sincroniza Shopee para dados enriquecidos (ship_by_date, Flex real)
                        order_sync_service.sync_shopee_order(
                            full_order_data.get('numeroLoja'),
                            instance_id=str(shopee_marketplace_integration_id or marketplace_integration_id),
                            channel_id=canal_config.get('canal_venda_id'),
                            marketplace_integration_id=shopee_marketplace_integration_id or marketplace_integration_id,
                            bling_loja_id=loja_id
                        )
                    else:
                        sync_result = order_sync_service.sync_bling_order(
                            full_order_data,
                            bling_integration_id=bling_integration_id
                        )

                    # Salva no banco legado (BlingPedidos) para manter compatibilidade
                    self._save_order_to_db(full_order_data)

                    # ✅ NOVO: Classificação e Consolidação Automática via Task Celery
                    # Após sincronizar o pedido, dispara task que:
                    #   1. Classifica o pedido em grupo de consolidação existente
                    #   2. Consolida os itens na demanda
                    #   3. Vincula pedido → demanda
                    if status_action == 'sync_and_consolidate' and sync_result and sync_result.get('id'):
                        try:
                            from tasks.auto_consolidation_tasks import classificar_e_consolidar_pedido
                            print(f"🔄 [WORKER:CONSOLID] Classificando+consolidando pedido {sync_result['id']}...")
                            classificar_e_consolidar_pedido.delay(sync_result['id'])
                            print(f"✅ [WORKER:CONSOLID] Task enfileirada para pedido {sync_result['id']}")
                        except ImportError:
                            # Fallback síncrono (ex: ambiente sem tasks/)
                            try:
                                from nistiprint_shared.services.consolidation_service import consolidation_service
                                print(f"🔄 [CONSOLIDAÇÃO] Fallback síncrono - pedido {sync_result['id']}...")
                                consolidation_service.consolidar_pedido(sync_result['id'])
                            except Exception as e:
                                print(f"⚠️ [WORKER:CONSOLID] Erro no fallback: {e}")
                        except Exception as e:
                            print(f"⚠️ [WORKER:CONSOLID] Erro ao enfileirar task: {e}")

                    return {"status": "success", "message": f"Order {order_id} processed fully (situação {situacao_id}).", "core_id": sync_result.get('id')}
                
                # Status sem sincronizacao completa apenas atualizam o legado.
                elif status_action == 'update_legacy':
                    print(f"✓ Pedido {order_id} {status_name} - apenas atualizando status...")
                    self._update_legacy_status(order_id, situacao_id)
                    return {"status": "success", "message": f"Details logged and status updated to {status_name}."}

            except Exception as e:
                print(f"❌ Erro ao processar detalhes do pedido {order_id}: {e}")
                return {"status": "error", "message": str(e)}

        # 2. Status de cancelamento -> atualiza status e limpa demandas associadas
        elif status_action == 'cancel':
            print(f"🛑 Pedido {order_id} CANCELADO no Bling. Iniciando limpeza de demandas...")
            try:
                # Busca detalhes para saber qual é o numeroLoja (pedido_externo_id)
                client = self._get_bling_client_for_details()
                full_order_data = client.get_order(order_id)
                
                if not full_order_data:
                    # Se não conseguir detalhes, tenta usar o que veio no webhook se tiver numeroLoja
                    pedido_externo_id = data.get('numeroLoja') or str(data.get('numero'))
                else:
                    pedido_externo_id = full_order_data.get('numeroLoja') or str(full_order_data.get('numero'))

                # Processa o cancelamento
                result = self._handle_order_cancellation(order_id, pedido_externo_id, data)
                return result
            except Exception as e:
                print(f"❌ Erro ao processar cancelamento do pedido {order_id}: {e}")
                return {"status": "error", "message": str(e)}

        # 3. OUTROS STATUS
        else:
            print(f"⏭️ Pedido {order_id} ignorado (Situação {situacao_id} sem action parametrizada).")
            return {"status": "skipped", "message": f"Status {situacao_id} ignored."}

    def _handle_order_cancellation(self, bling_id, pedido_externo_id, raw_data):
        """
        Trata o cancelamento de um pedido:
        1. Atualiza status no banco unificado (pedidos -> 7)
        2. Atualiza status no banco legado (pedidos_bling -> 12)
        3. Remove vinculos em demandas_pedidos
        4. Marca demandas impactadas para revisao
        5. Notifica em tempo real
        """
        from nistiprint_shared.services.order_service import order_service
        from nistiprint_shared.services.notification_service import notification_service
        
        try:
            # 1. Atualizar Pedido Unificado (Status 7 = Cancelado)
            # Precisamos do ID interno do pedido
            res_core = supabase_db.table('pedidos').select('id').eq('codigo_pedido_externo', str(pedido_externo_id)).execute()
            core_id = None
            if res_core.data:
                core_id = res_core.data[0]['id']
                supabase_db.table('pedidos').update({
                    'situacao_pedido_id': 7,
                    'updated_at': datetime.utcnow().isoformat()
                }).eq('id', core_id).execute()
                
                # Registrar evento
                order_service.register_event(
                    core_id, 
                    'ORDER_CANCELLED', 
                    f"Pedido cancelado via Webhook Bling (Status 12)",
                    raw_data,
                    status_para="7"
                )

            # 2. Atualizar Pedido Legado
            supabase_db.table('pedidos_bling').update({
                'situacao_pedido': 'Cancelado',
                'atualizado_em': datetime.utcnow().isoformat()
            }).eq('bling_id', str(bling_id)).execute()

            # 3. Processar Demandas Associadas
            # Buscamos todos os itens de demanda que vieram deste pedido
            # IMPORTANTE: Pode haver mais de uma plataforma se o numeroLoja colidir, 
            # mas aqui o contexto é Bling.
            res_origens = supabase_db.table('demandas_pedidos')\
                .select('id, demanda_id')\
                .eq('pedido_id', core_id)\
                .execute() if core_id else None
            
            affected_demandas = set()
            if res_origens and res_origens.data:
                for orig in res_origens.data:
                    orig_id = orig['id']
                    dem_id = orig['demanda_id']
                    affected_demandas.add(dem_id)
                    supabase_db.table('demandas_pedidos').delete().eq('id', orig_id).execute()
                    supabase_db.table('demandas_producao').update({
                        'requer_revisao': True,
                        'updated_at': datetime.utcnow().isoformat()
                    }).eq('id', dem_id).execute()

            # 4. Notificação em Tempo Real
            msg = f"🚫 Pedido {pedido_externo_id} CANCELADO no Bling."
            if affected_demandas:
                msg += f" {len(affected_demandas)} demanda(s) impactada(s): {list(affected_demandas)}."
            
            notification_service.broadcast_notification({
                'event_type': 'ORDER_CANCELLED',
                'message': msg,
                'pedido_externo_id': pedido_externo_id,
                'bling_id': bling_id,
                'affected_demandas': list(affected_demandas),
                'timestamp': datetime.utcnow().isoformat()
            })

            return {
                "status": "success", 
                "message": f"Order {pedido_externo_id} cancelled and demands updated.",
                "affected_demandas": list(affected_demandas)
            }

        except Exception as e:
            print(f"❌ Erro ao processar logic de cancelamento: {e}")
            raise e

    def _update_legacy_status(self, bling_id, situacao_id):
        """Atualiza o status no banco legado (BlingPedidos) e na tabela unificada (pedidos)."""
        try:
            # Buscar o mapeamento de status para obter o internal_situacao_pedido_id
            status_mapping = self._get_bling_status_mapping(situacao_id)
            internal_status_id = status_mapping.get('internal_situacao_pedido_id') if status_mapping else None

            # Atualizar tabela legada (pedidos_bling)
            res = supabase_db.table('pedidos_bling').select('id, numero_loja').eq('bling_id', str(bling_id)).execute()
            if res.data:
                legacy_id = res.data[0]['id']
                numero_loja = res.data[0].get('numero_loja')
                supabase_db.table('pedidos_bling').update({
                    'situacao_pedido': str(situacao_id),
                    'atualizado_em': datetime.utcnow().isoformat()
                }).eq('id', legacy_id).execute()

                # Atualizar tabela unificada (pedidos) se tiver mapeamento e numero_loja
                if internal_status_id and numero_loja:
                    res_core = supabase_db.table('pedidos').select('id').eq('codigo_pedido_externo', str(numero_loja)).execute()
                    if res_core.data:
                        core_id = res_core.data[0]['id']
                        supabase_db.table('pedidos').update({
                            'situacao_pedido_id': internal_status_id,
                            'updated_at': datetime.utcnow().isoformat()
                        }).eq('id', core_id).execute()
                        print(f"✓ Pedido {bling_id} atualizado: legado={situacao_id}, unificado={internal_status_id}")
        except Exception as e:
            print(f"⚠️ Erro ao atualizar status legado para {bling_id}: {e}")

    def _save_order_to_db(self, order_data: dict):
        """Saves the order and its items to the database (UPSERT logic)."""
        # Check if order exists by numero_loja, which is more unique than numero
        numero_loja = order_data.get('numeroLoja')
        if not numero_loja:
            # Fallback para numero se numeroLoja não existir
            numero_loja = str(order_data.get('numero'))

        # Mapeamento de dados do contato
        contato = order_data.get('contato', {})
        nome_cliente = contato.get('nome')
        email_cliente = contato.get('email') # Nem sempre vem no resumo, mas pode vir no detalhe
        # No Bling V3, documentos e telefones podem estar dentro do contato ou em sub-objetos
        telefone_cliente = contato.get('telefone')
        
        # Endereço de entrega (do transporte)
        transporte = order_data.get('transporte', {})
        endereco_entrega = transporte.get('etiqueta', {})

        # SQLAlchemy fallback ou Supabase direto
        if get_current_database_mode().name != 'SUPABASE':
            # ... (manter compatibilidade legada se necessário, mas focar no Supabase que é o que está sendo usado no log)
            order_record = BlingPedidos.query.filter_by(numeroLoja=numero_loja).first()
            # ... (código legado)
        else:
            # Supabase Upsert logic
            res = supabase_db.table('pedidos_bling').select('id').eq('numero_loja', numero_loja).execute()
            
            # Preparar payload distribuído
            order_payload = {
                'numero_pedido': str(order_data.get('numero')),
                'numero_loja': numero_loja,
                'loja_id': order_data.get('loja', {}).get('id'),
                'situacao_pedido': str(order_data.get('situacao', {}).get('id')),
                'data_pedido': order_data.get('data'), # 'data' no Bling API é a data do pedido
                'valor_total': float(order_data.get('total', 0)),
                'nome_cliente': nome_cliente,
                'email_cliente': email_cliente,
                'telefone_cliente': telefone_cliente,
                'endereco_entrega': endereco_entrega, # JSONB
                'itens': order_data.get('itens', []), # JSONB
                'contato': json.dumps(contato), # Texto/JSON para backup conforme solicitado
                'bling_id': str(order_data['id']),
                'personalizado': False,  # Será atualizado pelo personalized_order_identifier
                'atualizado_em': datetime.utcnow().isoformat()
            }
            
            if res.data:
                order_id = res.data[0]['id']
                supabase_db.table('pedidos_bling').update(order_payload).eq('id', order_id).execute()
            else:
                order_payload['criado_em'] = datetime.utcnow().isoformat()
                res_ins = supabase_db.table('pedidos_bling').insert(order_payload).execute()
                order_id = res_ins.data[0]['id']

            # Sync items (tabela detalhada de itens para relatórios/consolidação)
            supabase_db.table('itens_pedido_bling').delete().eq('pedido_bling_id', order_id).execute()
            items_to_insert = []
            for item_data in order_data.get('itens', []):
                items_to_insert.append({
                    'pedido_bling_id': order_id,
                    'codigo': item_data.get('codigo'),
                    'sku': item_data.get('codigo'), # Usando codigo como SKU
                    'unidade': item_data.get('unidade', 'UN'),
                    'quantidade': int(item_data['quantidade']),
                    'valor': float(item_data['valor']),
                    'preco_unitario': float(item_data['valor']),
                    'descricao': item_data['descricao'],
                    'produto': item_data.get('produto', {}), # Supabase handle dict to JSONB
                    'personalizado': False # Será atualizado abaixo se for personalizado
                })
            if items_to_insert:
                supabase_db.table('itens_pedido_bling').insert(items_to_insert).execute()

            # NOVO: Identificar e marcar itens personalizados
            # ATENÇÃO: Isso APENAS marca itens com personalizado=true baseado em palavras-chave
            # na descrição (ex: "personaliza"). NÃO executa processamento IA.
            # O processamento IA (extração de nomes via Gemini) roda EXCLUSIVAMENTE sob
            # demanda manual do usuário via UI.
            try:
                from nistiprint_shared.services.personalized_order_identifier import (
                    personalized_order_identifier
                )

                result = personalized_order_identifier.process_order(order_data)

                if result.get('success') and result.get('personalized_items'):
                    print(f"✓ Pedido {order_data.get('numero')}: {len(result['personalized_items'])} itens personalizados identificados")
                elif result.get('error'):
                    print(f"⚠️ Pedido {order_data.get('numero')}: Erro ao identificar personalizados: {result['error']}")

            except Exception as e:
                print(f"⚠️ Erro ao identificar itens personalizados: {e}")

        # --- GERAÇÃO DE DEMANDA DESATIVADA (AGORA É MANUAL PELO USUÁRIO) ---
        # print(f"🏭 [LOG] Gerando Demanda de Produção para o pedido {order_data.get('numero')}...")
        # demanda_producao_service.create_from_order(order_data)

    def import_single_order_by_shop_id(self, shopee_order_sn: str):
        """
        Importa manualmente um pedido baseado no numeroLoja (Shopee SN).
        Utiliza a Conta 01 para buscar os detalhes.
        """
        print(f"🚀 [MANUAL] Iniciando importação para o pedido Shopee SN: {shopee_order_sn}")
        try:
            client = self._get_bling_client_for_details()
            
            # 1. Buscar o pedido pelo numeroLoja na Conta 01
            url = f"pedidos/vendas?numerosLojas[]={shopee_order_sn}"
            response = client._request('GET', url)
            
            if not response or not response.get('data'):
                return False, f"Pedido {shopee_order_sn} não encontrado na conta Bling 01."
            
            order_summary = response['data'][0]
            order_id = order_summary.get('id')
            
            # 2. Buscar detalhes completos
            full_order_data = client.get_order(order_id)
            if not full_order_data:
                return False, f"Não foi possível obter os detalhes do pedido {order_id}."
            
            # 3. Sincronizar (Isso já salva no banco unificado e gera demanda)
            from nistiprint_shared.services.order_sync_service import order_sync_service
            order_sync_service.sync_bling_order(full_order_data)
            
            # 4. Salva no banco legado
            self._save_order_to_db(full_order_data)
            
            return True, f"Pedido {shopee_order_sn} importado com sucesso!"
            
        except Exception as e:
            print(f"❌ Erro na importação manual: {e}")
            return False, str(e)

# Global instance for use throughout the application
bling_order_processing_service = BlingOrderProcessingService()

# Expose the function at the module level for easy import (Used by routes.ferramentas)
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            return response.json().get('data', {})
        except requests.RequestException as e:
            logger.error(f"❌ Erro ao buscar detalhes do pedido {order_id} no Bling: {e}")
            return None

    def _get_bling_order_by_shopee_id(self, shopee_order_id: str, api_key: str) -> dict:
        """Fetches an order from Bling API using the numeroLoja (Shopee ID)."""
        url = f"https://api.bling.com.br/Api/v3/pedidos/vendas?numerosLojas[]={shopee_order_id}"
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
        try:
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            data = response.json().get('data', [])
            return data[0] if data else None
        except requests.RequestException as e:
            logger.error(f"❌ Erro ao buscar pedido Shopee ID {shopee_order_id} no Bling: {e}")
            return None

    def _get_bling_product_details(self, product_id: str, api_key: str) -> dict:
        """Fetches product details from the Bling API."""
        url = f"https://api.bling.com.br/Api/v3/produtos/{product_id}"
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
        try:
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            return response.json().get('data', {})
        except requests.RequestException as e:
            logger.error(f"❌ Erro ao buscar detalhes do produto {product_id} no Bling: {e}")
            return None

    def _upsert_pedido_bling(self, payload, integracao_instancia_id):
        """UPSERT em pedidos_bling (RAW fiel do payload)"""
        bling_id = payload.get('id')
        if not bling_id:
            return None
            
        data = {
            'bling_id': bling_id,
            'numero': str(payload.get('numero', '')),
            'numero_loja': payload.get('numeroLoja'),
            'situacao_id': payload.get('situacao', {}).get('id'),
            'situacao_valor': payload.get('situacao', {}).get('valor'),
            'contato': payload.get('contato'),
            'itens': payload.get('itens'),
            'transporte': payload.get('transporte'),
            'intermediador_cnpj': payload.get('intermediador', {}).get('cnpj'),
            'loja_id': payload.get('loja', {}).get('id'),
            'observacoes': payload.get('observacoes'),
            'observacoes_internas': payload.get('observacoesInternas'),
            'raw_payload': payload,
            'integracao_instancia_id': integracao_instancia_id,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        res = self.supabase.table('pedidos_bling').upsert(data, on_conflict='bling_id').execute()
        return res.data[0]['id'] if res.data else None

    def _find_channel_connection(self, bling_integration_id, aggregator_store_id):
        """Consulta channel_connections para mapear loja Bling → integração Shopee + canal"""
        res = self.supabase.rpc('find_shopee_connection', {
            'p_bling_integration_id': bling_integration_id,
            'p_aggregator_store_id': str(aggregator_store_id),
        }).execute()
        return res.data[0] if res.data else None

    def _upsert_pedido_shopee(self, shopee_data, shop_id):
        """UPSERT em pedidos_shopee com campos crus"""
        if not shopee_data:
            return None
            
        order_sn = shopee_data.get('order_sn')
        if not order_sn:
            return None
            
        # Converte pay_time de timestamp para ISO
        pay_time = None
        if shopee_data.get('pay_time'):
            pay_time = datetime.fromtimestamp(shopee_data['pay_time'], tz=timezone.utc).isoformat()
            
        data = {
            'order_sn': order_sn,
            'order_status': shopee_data.get('order_status'),
            'fulfillment_flag': shopee_data.get('fulfillment_flag'),
            'shipping_carrier': shopee_data.get('shipping_carrier'),
            'package_list': shopee_data.get('package_list'),
            'pay_time': pay_time,
            'recipient_address': shopee_data.get('recipient_address'),
            'item_list': shopee_data.get('item_list'),
            'shop_id': shop_id,
            'raw_payload': shopee_data,
            'enriched_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        res = self.supabase.table('pedidos_shopee').upsert(data, on_conflict='order_sn').execute()
        return res.data[0]['id'] if res.data else None

    def _upsert_pedido_master(self, payload, **kwargs):
        """UPSERT em pedidos (tabela centralizadora)"""
        bling_numero = str(payload.get('numero', ''))
        numero_loja = payload.get('numeroLoja')
        codigo_externo = numero_loja if numero_loja else bling_numero
        
        data = {
            'codigo_pedido_externo': codigo_externo,
            'numero_pedido': bling_numero,
            'pedido_bling_id': kwargs.get('pedido_bling_id'),
            'pedido_shopee_id': kwargs.get('pedido_shopee_id'),
            'shop_id_shopee': kwargs.get('shop_id_shopee'),
            'is_flex': kwargs.get('is_flex', False),
            'modalidade_logistica': kwargs.get('modalidade_logistica', 'STANDARD'),
            'canal_venda_id': kwargs.get('canal_venda_id'),
            'cliente_nome': payload.get('contato', {}).get('nome'),
            'data_venda': payload.get('data'),
            'origem': 'BLING',
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        # Mapping situation to situacao_pedido_id (placeholder, should use integration_status_mappings)
        # For now, let's try to map some common ones or keep null
        
        res = self.supabase.table('pedidos').upsert(data, on_conflict='codigo_pedido_externo').execute()
        return res.data[0]['id'] if res.data else None

    def _volume_servico(self, payload):
        volumes = payload.get('transporte', {}).get('volumes', [])
        return volumes[0].get('servico') if volumes else None

    def _save_order_to_db(self, payload, integracao_bling_id):
        """Fluxo refatorado de salvamento de pedido conforme Parte A do plano"""
        # 1. UPSERT em pedidos_bling
        pedido_bling_id = self._upsert_pedido_bling(payload, integracao_bling_id)

        # 2. Detectar Shopee via channel_connections
        pedido_shopee_id, shop_id_shopee, shopee_data = None, None, None
        aggregator_store_id = payload.get('loja', {}).get('id')
        
        conn = self._find_channel_connection(
            bling_integration_id=integracao_bling_id,
            aggregator_store_id=aggregator_store_id,
        )
        
        canal_venda_id = conn['channel_id'] if conn else None

        # 3. Se Shopee, enriquecer
        if conn and conn.get('marketplace_integration_id'):
            integration_shopee = {
                'id': conn['marketplace_integration_id'],
                'config': conn.get('shopee_config', {}),
                'credentials': conn.get('shopee_credentials', {}),
                'shop_id': conn.get('shopee_config', {}).get('shop_id') or conn.get('shopee_credentials', {}).get('shop_id')
            }
            
            try:
                order_sn = payload.get('numeroLoja')
                shopee_details = shopee_driver.get_order_detail(
                    integration=integration_shopee,
                    order_ids=[order_sn]
                )
                
                if shopee_details and len(shopee_details) > 0:
                    shopee_data = shopee_details[0].get('raw')
                    shop_id_shopee = integration_shopee['shop_id']
                    pedido_shopee_id = self._upsert_pedido_shopee(shopee_data, shop_id_shopee)
            except Exception as e:
                logger.error(f"Erro ao enriquecer pedido Shopee {payload.get('numeroLoja')}: {e}")

        # 4. Classificação Flex
        fields = {
            'servico_logistico': self._volume_servico(payload),
            'shipping_carrier': (shopee_data or {}).get('shipping_carrier'),
            'fulfillment_flag': (shopee_data or {}).get('fulfillment_flag'),
        }
        
        if not fields['shipping_carrier'] and shopee_data and shopee_data.get('package_list'):
            fields['shipping_carrier'] = shopee_data['package_list'][0].get('shipping_carrier')

        flex = flex_classifier_service.classify(
            self.supabase,
            fields=fields,
            integracao_instancia_id=(conn or {}).get('marketplace_integration_id') or integracao_bling_id,
            canal_venda_id=canal_venda_id,
        )

        # 5. UPSERT em pedidos Master
        pedido_id = self._upsert_pedido_master(
            payload,
            pedido_bling_id=pedido_bling_id,
            pedido_shopee_id=pedido_shopee_id,
            shop_id_shopee=shop_id_shopee,
            canal_venda_id=canal_venda_id,
            is_flex=flex.is_flex,
            modalidade_logistica=flex.modalidade
        )

        # 6. Criar demanda de produção
        demanda_producao_service.create_from_order(
            order_data=payload,
            is_flex=flex.is_flex,
            modalidade_logistica=flex.modalidade,
            canal_venda_id=canal_venda_id
        )
        
        return pedido_id

    def process_webhook(self, webhook_payload: dict):
        """
        Main method to process an incoming order webhook.
        Updated to use the new refactored flow.
        """
        logger.info("Processing Bling order webhook with refactored flow...")

        if not self.bling_antiga_account:
            raise Exception("Bling account (antiga) not found. Check CNPJ 13597 in contas_bling.")

        # O payload do webhook contém um objeto 'data' com os dados do evento
        inner_payload = webhook_payload.get('data', {})
        order_id = inner_payload.get('id')

        if not order_id:
            logger.warning("⚠️ Webhook sem ID de pedido. Pulando.")
            return {"status": "skipped", "message": "No order ID in payload."}

        # 1. Get full order details from Bling API using the "antiga" account
        api_key_antiga = self.bling_antiga_account.get('access_token')
        if not api_key_antiga:
            raise Exception("API key for Bling Antiga account not found.")

        full_order_data = self._get_bling_order_details(order_id, api_key_antiga)

        if not full_order_data:
            return {"status": "failed", "message": f"Could not fetch details for order {order_id}."}
        
        # 2. Apply filters
        # Status "Em andamento" (id 15)
        situacao_id = full_order_data.get('situacao', {}).get('id')
        if situacao_id != 15:
            logger.info(f"⏭️ Pedido {order_id} ignorado. Status é {situacao_id}, esperado 15.")
            return {"status": "skipped", "message": f"Order status is {situacao_id}, expected 15."}

        # Nome do contato não pode conter '**'
        contact_name = full_order_data.get('contato', {}).get('nome', '')
        if '**' in contact_name:
            logger.info(f"⏭️ Pedido {order_id} ignorado. Nome do contato contém '**'.")
            return {"status": "skipped", "message": "Contact name contains '**'."}
        
        # 3. Cross-check with Bling Nova account
        if not self.bling_nova_account:
            logger.warning("Bling Nova account not found for cross-check.")
        else:
            api_key_nova = self.bling_nova_account.get('access_token')
            shopee_order_id = full_order_data.get('numeroLoja')
            if shopee_order_id:
                order_from_nova = self._get_bling_order_by_shopee_id(shopee_order_id, api_key_nova)
                if order_from_nova:
                    situacao_id_nova = order_from_nova.get('situacao', {}).get('id')
                    if situacao_id_nova != 15:
                        logger.info(f"⏭️ Pedido {shopee_order_id} ignorado (Nova status {situacao_id_nova}).")
                        return {"status": "skipped", "message": "Nova account status not 15."}
                    
                    # Update data with Nova info (mirroring legacy logic)
                    nova_items = order_from_nova.get('itens', [])
                    if not nova_items:
                         order_from_nova['itens'] = full_order_data.get('itens', [])
                    full_order_data = order_from_nova

        # 4. Check for personalized items
        has_personalized_item, processed_items = self._check_for_personalized_items(
            full_order_data.get('itens', []),
            api_key_antiga
        )

        if not has_personalized_item:
            logger.info(f"⏭️ Pedido {full_order_data.get('numero')} ignorado. Sem itens personalizados.")
            return {"status": "skipped", "message": "No personalized items found."}

        full_order_data['itens'] = processed_items

        # 5. Save to database using refactored flow
        try:
            # integracao_bling_id is the ID of the "antiga" account
            pedido_id = self._save_order_to_db(full_order_data, self.bling_antiga_account['id'])
            return {"status": "success", "pedido_id": pedido_id}
        except Exception as e:
            logger.error(f"❌ Erro ao salvar pedido {full_order_data.get('numero')}: {e}")
            return {"status": "failed", "message": str(e)}

    def _check_for_personalized_items(self, items: list, api_key: str):
        """Checks a list of items for personalized products."""
        has_personalized_item = False
        processed_items = []
        ID_CAMPO_CUSTOMIZADO_PERSONALIZADO = 2797770

        for item in items:
            is_personalized = False
            item_description = item.get('descricao', '')
            product_id = item.get('produto', {}).get('id')

            if product_id:
                product_details = self._get_bling_product_details(product_id, api_key)
                if product_details and 'camposCustomizados' in product_details:
                    for field in product_details.get('camposCustomizados', []):
                        if (field.get('idCampoCustomizado') == ID_CAMPO_CUSTOMIZADO_PERSONALIZADO and
                                str(field.get('valor', '')).lower() == 'true'):
                            is_personalized = True
                            break
            
            if not is_personalized and 'personaliza' in item_description.lower():
                is_personalized = True

            if is_personalized:
                has_personalized_item = True
            
            item['_is_personalized'] = is_personalized
            processed_items.append(item)
            
        return has_personalized_item, processed_items

    def import_single_order_by_shop_id(self, shopee_order_sn: str):
        """Manual import using refactored flow."""
        if not self.bling_antiga_account:
            return False, "Conta Bling Antiga não configurada."

        api_key_antiga = self.bling_antiga_account.get('access_token')
        order_summary = self._get_bling_order_by_shopee_id(shopee_order_sn, api_key_antiga)

        if not order_summary:
            return False, f"Pedido {shopee_order_sn} não encontrado na Bling Antiga."

        full_order_data = self._get_bling_order_details(order_summary['id'], api_key_antiga)
        if not full_order_data:
            return False, "Não foi possível obter detalhes do pedido."

        has_personalized_item, items_to_save = self._check_for_personalized_items(
            full_order_data.get('itens', []),
            api_key_antiga
        )
        full_order_data['itens'] = items_to_save

        try:
            pedido_id = self._save_order_to_db(full_order_data, self.bling_antiga_account['id'])
            return True, f"Pedido {shopee_order_sn} importado com sucesso (ID: {pedido_id})."
        except Exception as e:
            return False, str(e)

# Global instance
bling_order_processing_service = BlingOrderProcessingService()

def import_single_order_by_shop_id(shopee_order_sn: str):
    return bling_order_processing_service.import_single_order_by_shop_id(shopee_order_sn)
