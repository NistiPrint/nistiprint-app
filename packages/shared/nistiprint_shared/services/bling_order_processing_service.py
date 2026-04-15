import requests
import json
from datetime import datetime
from nistiprint_shared.services.conta_bling_service import conta_bling_service
from nistiprint_shared.database.database import db
from nistiprint_shared.database.supabase_db_service import get_db_session, supabase_db
from nistiprint_shared.database.supabase_db_service import get_current_database_mode
from nistiprint_shared.models.bling_pedidos import BlingPedidos
from nistiprint_shared.models.bling_pedido_itens import BlingPedidoItens


class BlingOrderProcessingService:
    """
    Service to process Bling order webhooks, applying business logic
    and saving valid orders to the database.
    """

    def __init__(self):
        # ID da Conta Bling 01 conforme solicitado (ID exato)
        self.BLING_ACCOUNT_01_ID = "4LkzB9yWc07whoPi4IbT"
        self._status_mapping_cache = {}

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
def import_single_order_by_shop_id(shopee_order_sn: str):
    return bling_order_processing_service.import_single_order_by_shop_id(shopee_order_sn)
