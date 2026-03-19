from datetime import datetime, timedelta
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.auditoria_service import auditoria_service
from nistiprint_shared.services.estoque_service import estoque_service
from nistiprint_shared.services.system_log_service import system_log_service
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.bom_service import bom_service
from nistiprint_shared.services.order_tracker_service import order_tracker_service
from nistiprint_shared.services.daily_production_log_service import daily_production_log_service
from nistiprint_shared.services.app_config_service import app_config_service
from nistiprint_shared.services.system_events_log_service import system_events_log_service
from nistiprint_shared.services.previsao_consumo_service import previsao_consumo_service
from nistiprint_shared.services.unit_of_work import UnitOfWork
from typing import List, Dict, Any, Optional
import uuid
from nistiprint_shared.utils.date_utils import get_now, get_now_iso

# Importar core service para métodos compartilhados
from ..demanda.core import DemandaCoreService, demanda_core_service


class DemandaAlocacaoQueueService:
    def __init__(self):
        self.demandas_table = supabase_db.table('demandas_producao')
        self.itens_table = supabase_db.table('itens_demanda')
        # Referência ao core service para métodos compartilhados
        self._core = demanda_core_service

    def _registrar_alocacao_estoque(
        self,
        demanda_id: str,
        item_id: str,
        produto_id: str,
        correlation_id: str,
        quantidade: float,
        tipo_alocacao: str,
        processo_origem: str,
        metadata: dict = None
    ):
        """
        Registra alocação de estoque na tabela demanda_alocacoes_estoque.
        """
        import uuid as uuid_lib

        print(f"DEBUG [_registrar_alocacao_estoque] INICIO: item={item_id}, produto={produto_id}, qtd={quantidade}, tipo={tipo_alocacao}")
        try:
            existing = supabase_db.table('demanda_alocacoes_estoque')\
                .select('id', 'status')\
                .eq('correlation_id', correlation_id)\
                .neq('status', 'CANCELADA')\
                .execute()

            if existing.data:
                print(f"DEBUG [_registrar_alocacao_estoque] Alocação {correlation_id} já existe, ignorando registro duplicado")
                return existing.data[0]

            demanda_uuid = str(demanda_id)
            item_uuid = str(item_id)
            produto_uuid = str(produto_id)

            payload = {
                'demanda_id': demanda_uuid,
                'item_id': item_uuid,
                'produto_id': produto_uuid,
                'correlation_id': correlation_id,
                'quantidade_alocada': float(quantidade),
                'tipo_alocacao': tipo_alocacao,
                'processo_origem': processo_origem,
                'status': 'PENDENTE',
                'metadata': metadata or {}
            }

            print(f"DEBUG [_registrar_alocacao_estoque] Insert payload: {payload}")
            result = supabase_db.table('demanda_alocacoes_estoque').insert(payload).execute()
            print(f"DEBUG [_registrar_alocacao_estoque] Result: {result.data is not None}")
            return result.data[0] if result.data else None

        except Exception as e:
            print(f"ERRO [_registrar_alocacao_estoque] {correlation_id}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _marcar_alocacao_cancelada(self, correlation_id: str, motivo: str = None):
        """Cancela alocação (ex: em caso de estorno)."""
        try:
            metadata_update = {'motivo_cancelamento': motivo} if motivo else {}
            metadata_result = supabase_db.table('demanda_alocacoes_estoque')\
                .select('metadata')\
                .eq('correlation_id', correlation_id)\
                .execute()
            current_metadata = metadata_result.data[0].get('metadata', {}) if metadata_result.data else {}

            supabase_db.table('demanda_alocacoes_estoque')\
                .update({
                    'status': 'CANCELADA',
                    'cancelled_at': get_now_iso(),
                    'metadata': current_metadata | metadata_update
                })\
                .eq('correlation_id', correlation_id)\
                .execute()
        except Exception as e:
            print(f"ERRO ao cancelar alocação {correlation_id}: {e}")

    def _calcular_saldo_a_processar(self, item_id: str, produto_id: str, quantidade_necessaria: float) -> float:
        """
        Calcula quanto ainda precisa ser processado (diferença entre necessário e já alocado).
        """
        try:
            print(f"DEBUG [_calcular_saldo_a_processar] item={item_id}, produto={produto_id}, necessario={quantidade_necessaria}")
            total_alocado = self._calcular_total_alocado(item_id, produto_id)
            saldo = float(quantidade_necessaria) - total_alocado
            print(f"DEBUG [_calcular_saldo_a_processar] alocado={total_alocado}, saldo={saldo}")
            return max(saldo, 0.0)
        except Exception as e:
            print(f"ERRO [_calcular_saldo_a_processar]: {e}")
            import traceback
            traceback.print_exc()
            return float(quantidade_necessaria)

    def _calcular_total_alocado(self, item_id: str, produto_id: str) -> float:
        """Calcula total já alocado para um item+produto (soma de todas alocações ativas)."""
        try:
            alocacoes = self._buscar_alocacoes_por_item(item_id, produto_id)
            total = sum(float(a.get('quantidade_alocada', 0)) for a in alocacoes)
            print(f"DEBUG [_calcular_total_alocado] item={item_id}, prod={produto_id}, total={total} ({len(alocacoes)} alocações)")
            return total
        except Exception as e:
            print(f"ERRO ao calcular total alocado: {e}")
            return 0.0

    def _buscar_alocacoes_por_item(self, item_id: str, produto_id: str = None) -> List[Dict[str, Any]]:
        """Busca todas as alocações ativas (não canceladas) para um item."""
        try:
            result = supabase_db.table('demanda_alocacoes_estoque')\
                .select('*')\
                .neq('status', 'CANCELADA')\
                .execute()

            if not result.data:
                return []

            alocacoes_filtradas = []
            for aloc in result.data:
                if str(aloc.get('item_id')) == str(item_id):
                    if produto_id is None or str(aloc.get('produto_id')) == str(produto_id):
                        alocacoes_filtradas.append(aloc)

            print(f"DEBUG [_buscar_alocacoes_por_item] item={item_id}, prod={produto_id}, encontradas={len(alocacoes_filtradas)}")
            return alocacoes_filtradas

        except Exception as e:
            print(f"ERRO ao buscar alocações para item {item_id}: {e}")
            return []

    def _atualizar_progresso_simples(self, item_id: str, campo: str, incremento: float) -> Optional[Dict[str, Any]]:
        """Atualiza o progresso de um item de demanda de forma simples (apenas visual)."""
        try:
            item_res = self.itens_table.select(campo).eq('id', item_id).execute()
            if not item_res.data:
                return None

            valor_atual = float(item_res.data[0].get(campo, 0) or 0)
            novo_valor = valor_atual + incremento

            update_result = self.itens_table.update({campo: novo_valor, 'updated_at': get_now_iso()}).eq('id', item_id).execute()

            return {
                'campo': campo,
                'valor_anterior': valor_atual,
                'novo_valor': novo_valor,
                'incremento': incremento
            }
        except Exception as e:
            print(f"ERRO ao atualizar progresso simples para item {item_id}, campo {campo}: {e}")
            return None

    def get_item_by_id(self, item_id):
        """Função auxiliar para buscar um item de demanda pelo ID."""
        if not item_id or item_id == 'None':
            raise ValueError(f"ID de item inválido: {item_id}")

        try:
            clean_id = int(item_id)
        except (ValueError, TypeError):
            raise ValueError(f"ID de item deve ser numérico: {item_id}")

        response = supabase_db.execute_with_retry(self.itens_table.select("*").eq('id', clean_id))
        if not response.data:
            raise ValueError(f"Item {clean_id} não encontrado")
        return response.data[0]

    def agendar_processamento_estoque(self, demanda_id, item_id, campo, incremento, user_id='System', correlation_id=None, created_at=None, produto_id=None, forcar_sincrono=False):
        """Agenda o processamento de estoque na fila e dispara o worker via Celery."""
        if incremento == 0:
            return
        try:
            now = get_now_iso()

            tipo_op = campo
            prioridade = 10 # Default: prioridade normal (reservas, estornos)

            if campo in ['ITEM_TOTAL_BOM_PROCESS', 'DEMANDA_TOTAL', 'CONSUMO_BOM', 'ESTORNO_BOM', 'PRODUCAO_AVULSA', 'ESTORNO_AVULSO']:
                tipo_op = campo
            else:
                tipo_op = f"ETAPA:{campo}"
                prioridade = 1 # Prioridade máxima para ações manuais no dashboard

            cid = correlation_id or str(uuid.uuid4())

            payload = {
                'demanda_id': demanda_id,
                'item_id': item_id,
                'produto_id': produto_id,
                'quantidade': incremento,
                'user_id': str(user_id),
                'status': 'PENDENTE',
                'tipo_operacao': tipo_op,
                'correlation_id': cid,
                'created_at': created_at or now,
                'prioridade': prioridade
            }

            payload = {k: v for k, v in payload.items() if v is not None}

            supabase_db.table('fila_processamento_estoque').insert(payload).execute()
            print(f"DEBUG: Tarefa agendada na fila: {cid} - {tipo_op} - {incremento}")

            celery_success = False
            try:
                from nistiprint_shared.services.celery_app import celery_app
                celery_app.send_task('tasks.stock_tasks.process_stock_queue', args=[], kwargs={'limit': 50})
                print(f"DEBUG: Tarefa Celery disparada com sucesso")
                celery_success = True
            except Exception as celery_err:
                print(f"AVISO: Falha ao disparar tarefa Celery: {celery_err}")

            if not celery_success:
                print(f"DEBUG: Executando fallback síncrono para {cid} (Celery falhou)")
                try:
                    if tipo_op == 'ITEM_TOTAL_BOM_PROCESS':
                        item_demanda = self.get_item_by_id(item_id)
                        produto_final_id = item_demanda['produto_id']
                        if produto_final_id:
                            self.processar_insumos_por_bom_recursivo(
                                produto_id=int(produto_final_id),
                                quantidade=abs(float(incremento)),
                                correlation_id=cid,
                                user_id=str(user_id),
                                tipo_operacao='CONSUMO_BOM' if float(incremento) > 0 else 'ESTORNO_BOM',
                                retroactive_date=created_at,
                                item_id_referencia=item_id
                            )
                            supabase_db.table('fila_processamento_estoque')\
                                .update({'status': 'CONCLUIDO', 'processed_at': now})\
                                .eq('correlation_id', cid)\
                                .execute()
                    elif tipo_op.startswith('ETAPA:'):
                        campo_etapa = tipo_op.replace('ETAPA:', '')
                        self.processar_alocacao_de_demanda(
                            item_id=item_id,
                            campo=campo_etapa,
                            incremento=float(incremento),
                            user_id=str(user_id),
                            skip_visual_update=True,
                            retroactive_date=created_at,
                            correlation_id=cid
                        )
                        supabase_db.table('fila_processamento_estoque')\
                            .update({'status': 'CONCLUIDO', 'processed_at': now})\
                            .eq('correlation_id', cid)\
                            .execute()
                    else:
                        print(f"DEBUG: Tipo {tipo_op} não suportado em fallback síncrono, mantém na fila")
                except Exception as fallback_err:
                    print(f"ERRO no fallback síncrono: {fallback_err}")

        except Exception as e:
            print(f"Erro ao agendar processamento de estoque para {campo} no item {item_id}: {e}")

    def agendar_reserva_inteligente(self, demanda_id: str, itens_payload: List[Dict[str, Any]], user_id: str = 'System'):
        """
        Agenda a reserva inteligente de estoque (Waterfall) para processamento assíncrono.
        """
        try:
            cid = str(uuid.uuid4())
            now = get_now_iso()
            
            # Buscar dados básicos da demanda para o log/metadata
            demanda_info = self.demandas_table.select('descricao, canal_venda:canais_venda(nome)').eq('id', demanda_id).single().execute()
            desc = "Reserva Inteligente"
            canal = "N/A"
            if demanda_info.data:
                desc = demanda_info.data.get('descricao', desc)
                canal = demanda_info.data.get('canal_venda', {}).get('nome', canal)

            # Serializa os itens para JSON
            import json
            itens_json = json.dumps(itens_payload, default=str)
            
            payload = {
                'demanda_id': demanda_id,
                'item_id': None,
                'produto_id': None,
                'quantidade': len(itens_payload), # Usamos a quantidade de SKUs diferentes como referência
                'user_id': str(user_id),
                'status': 'PENDENTE',
                'tipo_operacao': 'RESERVA_INTELIGENTE',
                'correlation_id': cid,
                'metadata': {
                    'itens_payload': itens_json,
                    'detalhes': f"Reserva para {len(itens_payload)} itens da demanda '{desc}' - Canal: {canal}",
                    'origem': 'CRIAÇÃO_DEMANDA_CONSOLIDADA'
                },
                'created_at': now,
                'prioridade': 10 # Reservas são background (prioridade normal)
            }
            
            supabase_db.table('fila_processamento_estoque').insert(payload).execute()
            print(f"DEBUG: Reserva inteligente agendada para demanda {demanda_id} (correlation_id: {cid})")
            
            # Dispara o worker Celery
            celery_success = False
            try:
                from nistiprint_shared.services.celery_app import celery_app
                celery_app.send_task('tasks.stock_tasks.process_stock_queue', args=[], kwargs={'limit': 50})
                print(f"DEBUG: Tarefa Celery disparada para reserva inteligente")
                celery_success = True
            except Exception as celery_err:
                print(f"AVISO: Falha ao disparar tarefa Celery para reserva inteligente: {celery_err}")
            
            return {'success': True, 'correlation_id': cid, 'queued': True}
            
        except Exception as e:
            print(f"Erro ao agendar reserva inteligente para demanda {demanda_id}: {e}")
            return {'success': False, 'error': str(e)}

    def processar_alocacao_de_demanda(self, item_id: str, campo: str, incremento: float, user_id: str, skip_visual_update: bool = False, origem_tipo: Optional[int] = None, retroactive_date: Optional[str] = None, correlation_id: Optional[str] = None):
        """
        Processa a alocação de estoque com base no estágio de produção.
        """
        from nistiprint_shared.config.production_stages import ESTAGIOS_PRODUCAO
        from nistiprint_shared.services.bom_service import bom_service

        cid = correlation_id or f"DASH-{uuid.uuid4().hex[:8]}"
        mov_date = retroactive_date or get_now_iso()

        if not item_id or item_id == 'None':
            raise ValueError(f"ID do item inválido para processamento de estoque: {item_id}")

        if campo not in ESTAGIOS_PRODUCAO:
            progresso_result = None
            if not skip_visual_update:
                progresso_result = self._atualizar_progresso_simples(item_id, campo, incremento)

            try:
                item_demanda = self.get_item_by_id(item_id)
                daily_production_log_service.create_log(
                    log_date=datetime.fromisoformat(mov_date[:10]).date() if mov_date else datetime.now().date(),
                    product_id=str(item_demanda.get('produto_id')),
                    product_name="Progresso Visual",
                    quantity=incremento,
                    production_order_id=None,
                    component_stock_snapshot=[],
                    user_email=user_id,
                    metadata={'demanda_id': item_demanda.get('demanda_id'), 'item_id': item_id, 'campo': campo, 'correlation_id': cid}
                )
            except: pass

            return {
                'campo': campo,
                'incremento': incremento,
                'status': 'VISUAL_ONLY',
                'message': f"Atualização visual apenas para campo {campo}, não requer movimentação de estoque",
                'progresso_atualizacao': progresso_result,
                'correlation_id': cid
            }

        estagio = ESTAGIOS_PRODUCAO[campo]
        item_demanda = self.get_item_by_id(item_id)
        produto_final_id = item_demanda['produto_id']

        produto_intermediario = bom_service.get_component_by_role(produto_final_id, estagio['role_produto_gerado'])

        if not produto_intermediario:
            progresso_result = self._atualizar_progresso_simples(item_id, campo, incremento)
            return {
                'campo': campo,
                'incremento': incremento,
                'status': 'WARNING',
                'message': f"Produto intermediário com role '{estagio['role_produto_gerado']}' não encontrado na BOM do produto {produto_final_id}",
                'progresso_atualizacao': progresso_result,
                'correlation_id': cid
            }

        deposito_id = app_config_service.get_config('default_production_deposit_id')

        saldo_info = estoque_service.get_saldo_atual(produto_intermediario['id'], deposito_id)
        saldo_disponivel = float(saldo_info.get('quantidade_disponivel', 0))

        if not origem_tipo:
            origem_tipo = 1 if incremento > 0 else 2

        qtd_do_estoque = 0.0
        qtd_a_produzir = 0.0

        if incremento > 0:
            qtd_do_estoque = min(incremento, max(0.0, saldo_disponivel))
            qtd_a_produzir = incremento - qtd_do_estoque
        else:
            qtd_do_estoque = incremento

        try:
            if qtd_do_estoque != 0:
                if qtd_do_estoque > 0:
                    estoque_service.registrar_saida(
                        produto_id=int(produto_intermediario['id']),
                        deposito_id=deposito_id,
                        quantidade=qtd_do_estoque,
                        motivo=f"Consumo de estoque para {campo} - Item {item_id}",
                        user_context={'user_id': user_id},
                        documento_referencia=item_demanda.get('demanda_id'),
                        correlation_id=cid,
                        data_movimento=mov_date,
                        origem_tipo=origem_tipo
                    )
                else:
                    estoque_service.registrar_entrada(
                        produto_id=int(produto_intermediario['id']),
                        deposito_id=deposito_id,
                        quantidade=abs(qtd_do_estoque),
                        observacao=f"Estorno de {campo} - Item {item_id}",
                        user_context={'user_id': user_id},
                        correlation_id=cid,
                        data_movimento=mov_date,
                        origem_tipo=origem_tipo
                    )

            if qtd_a_produzir > 0:
                self._executar_movimentacao_estoque_recursiva(
                    item_id=item_id,
                    produto_id=int(produto_intermediario['id']),
                    quantidade=qtd_a_produzir,
                    demanda_id=item_demanda.get('demanda_id'),
                    saldos_produtos={},
                    boms_produtos={},
                    deve_sair_no_final=True
                )

            if incremento > 0 and qtd_do_estoque > 0:
                self._registrar_alocacao_estoque(
                    demanda_id=str(item_demanda.get('demanda_id')),
                    item_id=item_id,
                    produto_id=str(produto_intermediario['id']),
                    correlation_id=cid,
                    quantidade=qtd_do_estoque,
                    tipo_alocacao='MANUAL_DASHBOARD',
                    processo_origem='DASHBOARD',
                    metadata={'campo': campo, 'qtd_saida_imediata': qtd_do_estoque, 'qtd_fila_producao': qtd_a_produzir}
                )
            elif incremento < 0:
                self._marcar_alocacao_cancelada(cid, f"Estorno de {abs(incremento)} unidades no campo {campo}")

        except Exception as e:
            print(f"ERRO na movimentação de estoque para item {item_id}, campo {campo}: {e}")
            system_events_log_service.log_event(
                event_type='ERRO_ESTOQUE_PRODUCAO',
                details={'item_id': item_id, 'campo': campo, 'erro': str(e)},
                user_id=user_id
            )

        progresso_result = None
        if not skip_visual_update:
            progresso_result = self._atualizar_progresso_simples(item_id, campo, incremento)

        try:
            daily_production_log_service.create_log(
                log_date=datetime.fromisoformat(mov_date[:10]).date() if mov_date else datetime.now().date(),
                product_id=str(produto_intermediario['id']),
                product_name=produto_intermediario.get('nome') or produto_intermediario.get('name', 'Produto'),
                quantity=abs(incremento),
                production_order_id=None,
                component_stock_snapshot=[],
                user_email=user_id,
                metadata={'demanda_id': item_demanda.get('demanda_id'), 'item_id': item_id, 'campo': campo, 'correlation_id': cid}
            )
        except Exception as log_error:
            print(f"Erro ao registrar log diário de produção: {log_error}")

        return {
            'campo': campo,
            'incremento': incremento,
            'status': 'SUCCESS',
            'message': f"Processamento concluído para campo {campo}",
            'progresso_atualizacao': progresso_result,
            'correlation_id': cid
        }

    def _executar_movimentacao_estoque_recursiva(self, item_id, produto_id, quantidade, demanda_id,
                                               saldos_produtos, boms_produtos, deve_sair_no_final=True):
        """
        Motor de movimentação de estoque com suporte a produção JIT recursiva.
        """
        deposito_id = app_config_service.get_config('default_production_deposit_id')
        produto = product_service.get_by_id(produto_id)
        nome_produto = produto.get('name', f"Produto {produto_id}")

        saldo_info = saldos_produtos.get(str(produto_id))
        if saldo_info:
            saldo_disponivel = float(saldo_info.get('quantidade_disponivel', 0))
        else:
            res_saldo = estoque_service.get_saldo_atual(produto_id, deposito_id)
            saldo_disponivel = float(res_saldo.get('quantidade_disponivel', 0))

        qtd_do_estoque = min(saldo_disponivel, quantidade)
        qtd_a_produzir = max(0.0, quantidade - qtd_do_estoque)

        if qtd_do_estoque > 0 and deve_sair_no_final:
            estoque_service.registrar_saida(
                produto_id=produto_id,
                deposito_id=deposito_id,
                quantidade=qtd_do_estoque,
                motivo=f"Consumo de estoque para produção" if not demanda_id else f"Alocação item {item_id} demanda {demanda_id}",
                documento_referencia=demanda_id
            )

        if qtd_a_produzir > 0:
            componentes = boms_produtos.get(str(produto_id), [])
            if not componentes:
                componentes = bom_service.get_bom_for_produto(int(produto_id))

            if componentes:
                for comp in componentes:
                    comp_id = str(comp.componente_id)
                    qtd_comp_necessaria = float(comp.quantidade) * qtd_a_produzir

                    role_comp = product_service.identify_product_role(comp_id)

                    if role_comp in ['MIOLO', 'CAPA_IMPRESSAO', 'CAPA_ACABADA']:
                        self._executar_movimentacao_estoque_recursiva(
                            item_id=item_id,
                            produto_id=comp_id,
                            quantidade=qtd_comp_necessaria,
                            demanda_id=demanda_id,
                            saldos_produtos=saldos_produtos,
                            boms_produtos=boms_produtos,
                            deve_sair_no_final=True
                        )
                    else:
                        estoque_service.registrar_saida(
                            produto_id=comp_id,
                            deposito_id=deposito_id,
                            quantidade=qtd_comp_necessaria,
                            motivo=f"Consumo insumo para: {nome_produto}",
                            documento_referencia=demanda_id
                        )

                estoque_service.registrar_entrada(
                    produto_id=produto_id,
                    deposito_id=deposito_id,
                    quantidade=qtd_a_produzir,
                    observacao=f"Produção JIT automática: {nome_produto}" if demanda_id else f"Entrada de produção: {nome_produto}"
                )

                if deve_sair_no_final:
                    estoque_service.registrar_saida(
                        produto_id=produto_id,
                        deposito_id=deposito_id,
                        quantidade=qtd_a_produzir,
                        motivo=f"Consumo JIT produção" if not demanda_id else f"Alocação JIT demanda {demanda_id}",
                        documento_referencia=demanda_id
                    )

        return True

    def processar_insumos_por_bom_recursivo(self, produto_id: int, quantidade: float, correlation_id: str, user_id: str, tipo_operacao: str = 'CONSUMO_BOM', retroactive_date: Optional[str] = None, item_id_referencia: str = None, qtd_a_produzir_forcada: float = None):
        """
        Motor de Produção Waterfall.
        """
        print(f"DEBUG [WATERFALL] Processando Produto {produto_id}, Qtd: {quantidade}, Operacao: {tipo_operacao}, Correlation: {correlation_id}, ItemRef: {item_id_referencia}")
        from nistiprint_shared.services.bom_service import bom_service

        default_deposito_id = app_config_service.get_config('default_production_deposit_id')

        quantidade_original = quantidade
        qtd_a_produzir = quantidade

        if item_id_referencia and tipo_operacao == 'CONSUMO_BOM' and qtd_a_produzir_forcada is None:
            saldo_a_processar = self._calcular_saldo_a_processar(
                item_id=item_id_referencia,
                produto_id=str(produto_id),
                quantidade_necessaria=quantidade
            )
            if saldo_a_processar < quantidade:
                print(f"DEBUG [WATERFALL] Delta detectado: Original={quantidade}, Alocado={quantidade - saldo_a_processar}, AProcessar={saldo_a_processar}")
                quantidade = saldo_a_processar
                qtd_a_produzir = saldo_a_processar

                if quantidade <= 0:
                    print(f"DEBUG [WATERFALL] Produto {produto_id} já foi totalmente alocado manualmente. Pulando processamento.")
                    return

        qtd_estoque = 0.0

        if tipo_operacao == 'CONSUMO_BOM':
            if qtd_a_produzir_forcada is not None:
                qtd_a_produzir = qtd_a_produzir_forcada
            else:
                saldo_info = estoque_service.get_saldo_atual(produto_id, default_deposito_id)
                disponivel = float(saldo_info.get('quantidade_disponivel', 0) or 0)

                qtd_estoque = min(max(0.0, disponivel), quantidade)
                qtd_a_produzir = quantidade - qtd_estoque

            if qtd_estoque > 0:
                estoque_service.registrar_saida(
                    produto_id=produto_id,
                    deposito_id=default_deposito_id,
                    quantidade=qtd_estoque,
                    motivo=f"[WATERFALL_ESTOQUE] Saída de saldo existente para Correlation: {correlation_id}",
                    usuario_id=None,
                    correlation_id=correlation_id,
                    origem_tipo=0,
                    data_movimento=retroactive_date
                )

                if item_id_referencia:
                    self._registrar_alocacao_estoque(
                        demanda_id='UNKNOWN',
                        item_id=item_id_referencia,
                        produto_id=str(produto_id),
                        correlation_id=correlation_id,
                        quantidade=qtd_estoque,
                        tipo_alocacao='FINALIZACAO',
                        processo_origem='WORKER_FINALIZACAO',
                        metadata={'qtd_estoque': qtd_estoque, 'qtd_a_produzir': qtd_a_produzir, 'quantidade_original': quantidade_original}
                    )
        elif tipo_operacao == 'PRODUCAO_AVULSA':
            qtd_estoque = 0.0
            qtd_a_produzir = quantidade

        if qtd_a_produzir <= 0:
            print(f"DEBUG [WATERFALL] Produto {produto_id}: qtd_a_produzir={qtd_a_produzir}. Pulando explosão BOM.")
            return

        componentes = bom_service.get_bom_for_produto(produto_id)

        if componentes and tipo_operacao in ['CONSUMO_BOM', 'PRODUCAO_AVULSA']:
            for comp in componentes:
                qtd_comp_necessaria = float(comp.quantidade) * qtd_a_produzir
                print(f"DEBUG [WATERFALL] Componente {comp.componente_id}: {comp.quantidade} x {qtd_a_produzir} = {qtd_comp_necessaria}")
                self.processar_insumos_por_bom_recursivo(
                    produto_id=int(comp.componente_id),
                    quantidade=qtd_comp_necessaria,
                    correlation_id=correlation_id,
                    user_id=user_id,
                    tipo_operacao='CONSUMO_BOM',
                    retroactive_date=retroactive_date,
                    item_id_referencia=None
                )

            estoque_service.registrar_entrada(
                produto_id=produto_id,
                deposito_id=default_deposito_id,
                quantidade=qtd_a_produzir,
                observacao=f"[WATERFALL_PROD] Entrada de item produzido para Correlation: {correlation_id}",
                usuario_id=None,
                correlation_id=correlation_id,
                origem_tipo=8,
                data_movimento=retroactive_date
            )

            if tipo_operacao == 'CONSUMO_BOM':
                estoque_service.registrar_saida(
                    produto_id=produto_id,
                    deposito_id=default_deposito_id,
                    quantidade=qtd_a_produzir,
                    motivo=f"[WATERFALL_CONSUMO] Saída de item produzido para Correlation: {correlation_id}",
                    usuario_id=None,
                    correlation_id=correlation_id,
                    origem_tipo=0,
                    data_movimento=retroactive_date
                )
        else:
            if tipo_operacao in ['CONSUMO_BOM', 'ESTORNO_AVULSO_CONSUMO']:
                print(f"DEBUG [WATERFALL] Produto {produto_id} SEM BOM. Registrando SAIDA DIRETA: {qtd_a_produzir}")
                estoque_service.registrar_saida(
                    produto_id=produto_id,
                    deposito_id=default_deposito_id,
                    quantidade=qtd_a_produzir,
                    motivo=f"[WATERFALL_DIRETO] Saída direta (sem BOM) para Correlation: {correlation_id}",
                    usuario_id=None,
                    correlation_id=correlation_id,
                    origem_tipo=0,
                    data_movimento=retroactive_date
                )
            elif tipo_operacao in ['ESTORNO_BOM', 'ESTORNO_AVULSO']:
                print(f"DEBUG [WATERFALL] Estornando {produto_id}: {quantidade}")
                estoque_service.registrar_entrada(
                    produto_id=produto_id,
                    deposito_id=default_deposito_id,
                    quantidade=quantidade,
                    observacao=f"[WATERFALL_ESTORNO] Estorno para Correlation: {correlation_id}",
                    usuario_id=None,
                    correlation_id=correlation_id,
                    origem_tipo=0,
                    data_movimento=retroactive_date
                )

    def _baixar_estoque_demanda(self, demanda_id, user_id='System'):
        """Baixa o estoque de produto acabado para uma demanda concluída."""
        try:
            demanda = self._core.get_demanda_with_itens(demanda_id)
            if not demanda:
                return

            deposito_id = app_config_service.get_config('default_production_deposit_id')
            correlation_id = f"BAIXA_DEMANDA-{demanda_id}-{uuid.uuid4().hex[:8]}"

            for item in demanda.get('itens', []):
                produto_id_demanda = item.get('produto_id')
                quantidade_a_baixar = float(item.get('quantidade', 0))

                if produto_id_demanda and quantidade_a_baixar > 0:
                    estoque_service.registrar_saida(
                        produto_id=produto_id_demanda,
                        deposito_id=deposito_id,
                        quantidade=quantidade_a_baixar,
                        motivo=f"Baixa automática - Demanda {demanda_id} concluída",
                        usuario_id=None,
                        correlation_id=correlation_id,
                        origem_tipo=0
                    )

                    try:
                        estoque_service.liberar_reserva(
                            produto_id=produto_id_demanda,
                            quantidade=quantidade_a_baixar
                        )
                    except: pass

            auditoria_service.log_event('ESTOQUE_BAIXADO_DEMANDA', {
                'demanda_id': demanda_id,
                'status': 'Sucesso',
                'correlation_id': correlation_id
            }, user_id)
        except Exception as e:
            print(f"Erro ao baixar estoque da demanda {demanda_id}: {e}")

    def get_demanda_with_itens(self, demanda_id: str):
        """Busca uma demanda com seus itens."""
        response = supabase_db.execute_with_retry(
            self.demandas_table.select("*, canal_venda:canais_venda(nome, color, plataformas(nome))").eq('id', demanda_id)
        )
        if not response.data:
            response = supabase_db.execute_with_retry(
                self.demandas_table.select("*, canal_venda:canais_venda(nome, color, plataformas(nome))").eq('demanda_id', demanda_id)
            )
            if not response.data:
                return None

        raw_demanda = response.data[0]
        internal_id = raw_demanda['id']
        itens_response = supabase_db.execute_with_retry(
            self.itens_table.select("*").eq('demanda_id', internal_id).order('id')
        )

        return {
            **raw_demanda,
            'itens': itens_response.data
        }

    def processar_fila_estoque(self, limit=10):
        """
        Processa as tarefas pendentes na fila de processamento de estoque (Modelo Outbox Atômico).
        Utiliza RPC fetch_and_lock_stock_tasks para garantir consumo exclusivo por worker.
        """
        import socket
        import uuid
        worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"

        try:
            print(f"DEBUG: Worker '{worker_id}' tentando buscar até {limit} tarefas na fila...")
            res = supabase_db.rpc('fetch_and_lock_stock_tasks', {
                'p_worker_id': worker_id,
                'p_limit': limit
            }).execute()

            if not res.data:
                return 0

            print(f"DEBUG: Worker '{worker_id}' obteve {len(res.data)} tarefas para processar.")
            processed_count = 0
            for tarefa in res.data:
                tarefa_id = tarefa['id']
                try:
                    t_correlation_id = tarefa.get('correlation_id')

                    existing_mov = supabase_db.table('movimentacoes_estoque')\
                        .select('id', count='exact')\
                        .eq('correlation_id', t_correlation_id)\
                        .execute()

                    if existing_mov.data and len(existing_mov.data) > 0:
                        print(f"DEBUG: Tarefa {t_correlation_id} JÁ FOI PROCESSADA (idempotência). Marcando como CONCLUIDO.")
                        supabase_db.table('fila_processamento_estoque')\
                            .update({
                                'status': 'CONCLUIDO',
                                'processed_at': get_now_iso(),
                                'locked_at': None,
                                'mensagem_erro': None
                            })\
                            .eq('id', tarefa_id)\
                            .execute()
                        processed_count += 1
                        continue

                    t_retroactive_date = tarefa.get('created_at')
                    t_tipo = tarefa.get('tipo_operacao', '')

                    if t_tipo in ['CONSUMO_BOM', 'ESTORNO_BOM', 'PRODUCAO_AVULSA', 'ESTORNO_AVULSO']:
                        self.processar_insumos_por_bom_recursivo(
                            produto_id=tarefa['produto_id'],
                            quantidade=float(tarefa['quantidade']),
                            correlation_id=t_correlation_id,
                            user_id=tarefa.get('user_id', 'System'),
                            tipo_operacao=t_tipo,
                            retroactive_date=t_retroactive_date
                        )
                    elif t_tipo == 'DEMANDA_TOTAL':
                        self._baixar_estoque_demanda(tarefa['demanda_id'], tarefa.get('user_id', 'System'))
                    
                    elif t_tipo == 'RESERVA_INTELIGENTE':
                        # Processa reserva inteligente em cascata (Waterfall) para todos os itens da demanda
                        import json
                        metadata = tarefa.get('metadata', {})
                        itens_json = metadata.get('itens_payload') if isinstance(metadata, dict) else None
                        
                        if itens_json:
                            itens_payload = json.loads(itens_json)
                            # Chama o método do core service para executar a reserva inteligente
                            self._core._processar_reserva_inteligente_demanda(
                                demanda_id=tarefa['demanda_id'],
                                itens_payload=itens_payload,
                                user_id=tarefa.get('user_id', 'System')
                            )
                            print(f"DEBUG: Reserva inteligente processada para demanda {tarefa['demanda_id']}")
                        else:
                            raise ValueError("Metadata itens_payload não encontrado na tarefa RESERVA_INTELIGENTE")
                    
                    elif t_tipo == 'ITEM_TOTAL_BOM_PROCESS':
                        item_demanda = self.get_item_by_id(tarefa['item_id'])
                        produto_final_id = item_demanda['produto_id']

                        if produto_final_id:
                            self.processar_insumos_por_bom_recursivo(
                                produto_id=int(produto_final_id),
                                quantidade=abs(float(tarefa['quantidade'])),
                                correlation_id=t_correlation_id,
                                user_id=tarefa.get('user_id', 'System'),
                                tipo_operacao='CONSUMO_BOM' if float(tarefa['quantidade']) > 0 else 'ESTORNO_BOM',
                                retroactive_date=t_retroactive_date,
                                item_id_referencia=tarefa['item_id']
                            )

                    elif t_tipo == 'ITEM_TOTAL_PROCESSO':
                        etapas_estoque = ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd', 'miolos_prontos_retirada_qtd']
                        for campo_etapa in etapas_estoque:
                            self.processar_alocacao_de_demanda(
                                item_id=tarefa['item_id'],
                                campo=campo_etapa,
                                incremento=float(tarefa['quantidade']),
                                user_id=tarefa.get('user_id', 'System'),
                                skip_visual_update=True,
                                retroactive_date=t_retroactive_date,
                                correlation_id=t_correlation_id
                            )
                    elif t_tipo.startswith('ETAPA:'):
                        campo_etapa = t_tipo.replace('ETAPA:', '')
                        from nistiprint_shared.config.production_stages import ESTAGIOS_PRODUCAO
                        estagio = ESTAGIOS_PRODUCAO.get(campo_etapa)

                        if estagio and estagio.get('role_produto_gerado'):
                            item_demanda = self.get_item_by_id(tarefa['item_id'])
                            produto_final_id = item_demanda['produto_id']

                            produto_intermediario = None
                            if estagio['role_produto_gerado'] == 'MIOLO' and item_demanda.get('id_produto_miolo'):
                                produto_intermediario = {'id': item_demanda['id_produto_miolo']}
                            else:
                                produto_intermediario = bom_service.get_component_by_role(produto_final_id, estagio['role_produto_gerado'])

                            if produto_intermediario:
                                self.processar_insumos_por_bom_recursivo(
                                    produto_id=int(produto_intermediario['id']),
                                    quantidade=abs(float(tarefa['quantidade'])),
                                    correlation_id=t_correlation_id,
                                    user_id=tarefa.get('user_id', 'System'),
                                    tipo_operacao='CONSUMO_BOM' if float(tarefa['quantidade']) > 0 else 'ESTORNO_BOM',
                                    retroactive_date=t_retroactive_date,
                                    item_id_referencia=tarefa['item_id']
                                )
                    else:
                        pass

                    supabase_db.table('fila_processamento_estoque')\
                        .update({
                            'status': 'CONCLUIDO',
                            'processed_at': get_now_iso(),
                            'locked_at': None,
                            'mensagem_erro': None
                        })\
                        .eq('id', tarefa_id)\
                        .execute()

                    processed_count += 1
                except Exception as e:
                    error_msg = str(e)
                    tentativas = tarefa.get('tentativas', 1)

                    is_temporary = any(term in error_msg.upper() for term in ['SALDO', 'INSUFICIENTE', 'ESTOQUE', 'CONEXÃO', 'TIMEOUT'])

                    update_payload = {
                        'locked_at': None,
                        'mensagem_erro': f"Tentativa {tentativas}: {error_msg}"
                    }

                    if is_temporary and tentativas < 5:
                        intervals = [1, 5, 15, 30, 60]
                        delay = intervals[min(tentativas-1, len(intervals)-1)]

                        update_payload['status'] = 'ERRO'
                        update_payload['proxima_execucao_at'] = (datetime.now() + timedelta(minutes=delay)).isoformat()
                    else:
                        update_payload['status'] = 'ERRO'
                        update_payload['proxima_execucao_at'] = None

                    supabase_db.table('fila_processamento_estoque').update(update_payload).eq('id', tarefa_id).execute()

            return processed_count
        except Exception as e:
            print(f"Erro global no Atomic Stock Worker: {e}")
            return 0


demanda_alocacao_queue_service = DemandaAlocacaoQueueService()
