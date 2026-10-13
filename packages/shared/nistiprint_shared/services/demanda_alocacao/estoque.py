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
from nistiprint_shared.services.category_service import category_service
from typing import List, Dict, Any, Optional
import uuid
from nistiprint_shared.utils.date_utils import get_now, get_now_iso

# Importar core service para métodos compartilhados
from ..demanda.core import DemandaCoreService, demanda_core_service

class StockProcessingResult:
    def __init__(self, status: str, details: str = None, movements_created: List[str] = None, quantity_processed: float = 0.0):
        self.status = status  # 'SUCCESS', 'SKIPPED', 'PARTIAL', 'ERROR'
        self.details = details
        self.movements_created = movements_created or []
        self.quantity_processed = quantity_processed

class DemandaAlocacaoEstoqueService:
    """
    Serviço para gerenciamento de alocações de estoque por demanda.
    Arquitetura Event Sourcing: usa eventos_producao_v2 como fonte da verdade.
    """
    def __init__(self):
        self.demandas_table = supabase_db.table('demandas_producao')
        self.itens_table = supabase_db.table('itens_demanda')
        self._core = demanda_core_service

    def registrar_evento_producao(self, item_id, demanda_id, estagio, quantidade, tipo_evento='SINAL', user_id='System'):
        """
        Registra um evento de produção na tabela eventos_producao_v2.
        Este é o único ponto de entrada para processamento de estoque.

        Args:
            item_id: ID do item de demanda
            demanda_id: ID da demanda de produção. Pode vir como INT (FK para
                demandas_producao.id) OU como CÓDIGO alfanumérico (ex:
                '260508SYS9BRCV', valor da coluna demandas_producao.demanda_id).
                Resolvemos para INT antes do INSERT, pois eventos_producao_v2.demanda_id
                é INTEGER e tentar inserir uma string alfanumérica falha por type mismatch.
            estagio: Estágio da produção (ex: 'finalizados_qtd', 'capas_impressas_qtd')
            quantidade: Quantidade reportada
            tipo_evento: 'SINAL' para etapas intermediárias, 'LIQUIDACAO' para finalização
            user_id: ID do usuário

        Returns:
            dict: Evento registrado
        """
        try:
            demanda_id_int = self._resolver_demanda_id_int(demanda_id, item_id)

            cid = str(uuid.uuid4())
            evento = {
                'item_demanda_id': int(item_id) if item_id is not None else None,
                'demanda_id': demanda_id_int,
                'estagio': estagio,
                'quantidade_reportada': float(quantidade),
                'tipo_evento': tipo_evento,
                'processado': False,
                'correlation_id': cid,
                'usuario_id': user_id if isinstance(user_id, int) else None,
                'created_at': get_now_iso()
            }
            supabase_db.table('eventos_producao_v2').insert(evento).execute()
            return evento
        except Exception as e:
            import traceback
            print(f"Erro ao registrar evento de produção: {e}")
            traceback.print_exc()
            raise

    def _resolver_demanda_id_int(self, demanda_id, item_id=None):
        """
        Garante que o demanda_id seja a chave numérica (PK INT em demandas_producao.id).

        Aceita:
        - int / str numérica → retorna int direto
        - str alfanumérica (código demanda_id) → busca em demandas_producao
        - None → tenta resolver via item_id (FK em itens_demanda.demanda_id)
        """
        if demanda_id is None and item_id is not None:
            try:
                res = self.itens_table.select('demanda_id').eq('id', int(item_id)).execute()
                if res.data:
                    return int(res.data[0]['demanda_id'])
            except Exception:
                pass
            return None

        if isinstance(demanda_id, int):
            return demanda_id

        s = str(demanda_id).strip()
        if s.isdigit():
            return int(s)

        # Código alfanumérico — resolver via demandas_producao
        try:
            res = self.demandas_table.select('id').eq('demanda_id', s).execute()
            if res.data:
                return int(res.data[0]['id'])
        except Exception:
            pass
        return None

    def get_item_by_id(self, item_id):
        """Busca um item de demanda pelo ID."""
        try:
            clean_id = int(item_id)
        except (ValueError, TypeError):
            raise ValueError(f"ID de item deve ser numérico: {item_id}")

        response = supabase_db.execute_with_retry(self.itens_table.select("*").eq('id', clean_id))
        if not response.data:
            raise ValueError(f"Item {clean_id} não encontrado")
        return response.data[0]

    def agendar_reserva_inteligente(self, demanda_id, itens_payload, user_id):
        """
        Agenda o processamento de reserva inteligente de estoque.
        """
        from nistiprint_shared.services.demanda_alocacao.queue import demanda_alocacao_queue_service
        # Placeholder/Delegation
        return {"success": True, "correlation_id": str(uuid.uuid4())}

    def processar_insumos_por_bom_recursivo(self, produto_id: str, quantidade: float, correlation_id: str,
                                            user_id: str, tipo_operacao: str = 'CONSUMO_BOM',
                                            retroactive_date: Optional[str] = None,
                                            item_id_referencia: str = None,
                                            qtd_a_produzir_forcada: float = None):
        """
        Processa insumos por BOM recursivo. 
        Em modo síncrono, chama o motor de reconciliação diretamente.
        """
        from nistiprint_shared.services.motor_reconciliacao_estoque import motor_reconciliacao_estoque
        from nistiprint_shared.services.app_config_service import app_config_service
        from decimal import Decimal
        import asyncio

        # Determinar deposito padrão
        deposito_id = app_config_service.get_config('default_production_deposit_id') or 'principal'

        # Para produção avulsa (sem item de demanda), precisamos processar de forma síncrona
        # Chamamos o motor de reconciliação para processar a BOM recursivamente
        try:
            # Criar evento loop se não existir
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Determinar demanda_id (None para produção avulsa)
            demanda_id = item_id_referencia if item_id_referencia else None

            # Chamar o método de explosão de BOM do motor
            movimentos = loop.run_until_complete(
                motor_reconciliacao_estoque._explodir_bom_consumo(
                    produto_id=int(produto_id),
                    quantidade=Decimal(str(quantidade)),
                    demanda_id=demanda_id or 0,  # 0 se não tiver demanda
                    user_id=user_id,
                    deposito_padrao=deposito_id,
                    profundidade=0,
                    max_profundidade=10
                )
            )

            # Aplicar os movimentos de estoque
            print(f"DEBUG: {len(movimentos) if movimentos else 0} movimentos gerados pela BOM")
            if movimentos:
                for idx, mov in enumerate(movimentos):
                    try:
                        print(f"DEBUG: Aplicando movimento {idx+1}/{len(movimentos)}: produto_id={mov.produto_id}, quantidade={mov.quantidade}, motivo={mov.motivo}, deposito_id={mov.deposito_id}")
                        # Registrar entrada ou saída de estoque
                        if mov.quantidade > 0:
                            # Entrada (produção JIT)
                            print(f"DEBUG: Registrando ENTRADA para produto {mov.produto_id}")
                            mov_id = estoque_service.registrar_entrada(
                                produto_id=mov.produto_id,
                                deposito_id=mov.deposito_id,
                                quantidade=float(mov.quantidade),
                                observacao=mov.motivo,
                                usuario_id=None,
                                user_context={'user_id': user_id},
                                origem_tipo=3,
                                correlation_id=correlation_id
                            )
                            print(f"DEBUG: Entrada registrada com ID {mov_id}")
                        else:
                            # Saída (consumo)
                            print(f"DEBUG: Registrando SAÍDA para produto {mov.produto_id}")
                            mov_id = estoque_service.registrar_saida(
                                produto_id=mov.produto_id,
                                deposito_id=mov.deposito_id,
                                quantidade=float(abs(mov.quantidade)),
                                motivo=mov.motivo,
                                usuario_id=None,
                                user_context={'user_id': user_id},
                                origem_tipo=3,
                                correlation_id=correlation_id
                            )
                            print(f"DEBUG: Saída registrada com ID {mov_id}")
                    except Exception as e:
                        print(f"AVISO: Erro ao aplicar movimento {mov}: {e}")
                        import traceback
                        traceback.print_exc()
                        # Continua processando mesmo se houver erro em um movimento

            loop.close()
            return True

        except Exception as e:
            print(f"ERRO ao processar insumos por BOM recursivo: {e}")
            import traceback
            traceback.print_exc()
            return False

    def agendar_processamento_estoque(self, demanda_id, item_id, campo, incremento, user_id='System',
                                      correlation_id=None, created_at=None, produto_id=None, forcar_sincrono=False):
        """Compatibilidade: antes gravava na fila legada do motor v1.

        A fila foi aposentada; a chamada agora registra o evento no caminho unico
        (eventos_producao_v2 -> ConsolidadorDeEstoque). A assinatura foi preservada
        para nao quebrar os chamadores; correlation_id, created_at, produto_id e
        forcar_sincrono deixaram de ter efeito.
        """
        tipo_evento = 'LIQUIDACAO' if campo == 'finalizados_qtd' else 'SINAL'
        return self.registrar_evento_producao(
            item_id=item_id,
            demanda_id=demanda_id,
            estagio=campo,
            quantidade=float(incremento),
            tipo_evento=tipo_evento,
            user_id=user_id
        )

    def processar_alocacao_de_demanda(self, item_id, campo, incremento, user_id, skip_visual_update=False, 
                                      origem_tipo=None, retroactive_date=None, correlation_id=None):
        """
        Mapeia a chamada legada para o novo sistema de Event Sourcing.
        """
        item = self.get_item_by_id(item_id)
        return self.registrar_evento_producao(
            item_id=item_id,
            demanda_id=item.get('demanda_id'),
            estagio=campo,
            quantidade=incremento,
            tipo_evento='SINAL',
            user_id=user_id
        )

    def processar_alocacao_avulsa_otimizado(self, product_id, campo, quantidade, user_id, sincrono=False):
        """
        Distribui uma produção avulsa entre itens ativos compatíveis.

        Regras:
        - Normaliza alias de campo (capas_acabadas_qtd -> capas_produzidas_qtd)
        - Seleciona itens por produto (capa) ou miolo conforme o campo
        - Considera apenas demandas ativas
        - Atualiza via o caminho unico de estoque (eventos_producao_v2 + Consolidador)
        """
        # Import tardio: items.py importa este modulo, entao o import no topo seria circular.
        from nistiprint_shared.services.demanda.items import demanda_items_service

        campo_map = {
            'capas_acabadas_qtd': 'capas_produzidas_qtd',
            'capas_impressas_qtd': 'capas_impressas_qtd',
            'capas_produzidas_qtd': 'capas_produzidas_qtd',
            'miolos_prontos_retirada_qtd': 'miolos_prontos_retirada_qtd',
            'expedicao_capas_retiradas_qtd': 'expedicao_capas_retiradas_qtd',
            'expedicao_miolos_retirados_qtd': 'expedicao_miolos_retirados_qtd',
            'finalizados_qtd': 'finalizados_qtd',
        }
        campo_normalizado = campo_map.get(str(campo or '').strip())
        if not campo_normalizado:
            raise ValueError(f"Campo de alocacao nao suportado: {campo}")

        try:
            quantidade_total = float(quantidade or 0)
        except (TypeError, ValueError):
            raise ValueError(f"Quantidade invalida: {quantidade}")
        if quantidade_total <= 0:
            raise ValueError("Quantidade deve ser maior que zero")

        coluna_produto = (
            'id_produto_miolo'
            if campo_normalizado in ('miolos_prontos_retirada_qtd', 'expedicao_miolos_retirados_qtd')
            else 'produto_id'
        )

        itens_resp = supabase_db.execute_with_retry(
            self.itens_table.select('*').eq(coluna_produto, int(product_id))
        )
        itens = [row for row in (getattr(itens_resp, 'data', None) or []) if isinstance(row, dict)]
        if not itens:
            return {
                'success': True,
                'status': 'sem_alvo',
                'message': 'Nenhum item compativel encontrado para alocacao.',
                'campo': campo_normalizado,
                'quantidade_solicitada': quantidade_total,
                'quantidade_alocada': 0.0,
                'quantidade_nao_alocada': quantidade_total,
                'alocacoes': []
            }

        demanda_ids = sorted({item.get('demanda_id') for item in itens if item.get('demanda_id') is not None})
        if not demanda_ids:
            return {
                'success': True,
                'status': 'sem_alvo',
                'message': 'Itens sem demanda associada para alocacao.',
                'campo': campo_normalizado,
                'quantidade_solicitada': quantidade_total,
                'quantidade_alocada': 0.0,
                'quantidade_nao_alocada': quantidade_total,
                'alocacoes': []
            }

        demandas_resp = supabase_db.execute_with_retry(
            self.demandas_table.select('id,status,data_entrega,horario_coleta,prioridade_manual,modalidade_logistica,is_flex').in_('id', demanda_ids)
        )
        demandas_rows = [row for row in (getattr(demandas_resp, 'data', None) or []) if isinstance(row, dict)]

        status_map = {
            'PENDENTE': 'AGUARDANDO',
            'RASCUNHO': 'AGUARDANDO',
            'CRIADA': 'AGUARDANDO',
            'EM PRODUCAO': 'EM_PRODUCAO',
            'EM_ANDAMENTO': 'EM_PRODUCAO',
            'COLETA PARCIAL': 'COLETA_PARCIAL',
            'COLETA_PARCIAL': 'COLETA_PARCIAL',
            'FINALIZADO': 'CONCLUIDO',
            'CONCLUIDO': 'CONCLUIDO',
            'COLETADO': 'COLETADO',
            'CANCELADO': 'CANCELADO',
        }
        active_status = {'AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL'}

        demandas_ativas = {}
        for demanda in demandas_rows:
            raw_status = str(demanda.get('status') or '').strip().upper().replace('_', ' ')
            normalized = status_map.get(raw_status, str(demanda.get('status') or '').strip().upper().replace(' ', '_'))
            if normalized in active_status:
                demandas_ativas[demanda['id']] = demanda

        if not demandas_ativas:
            return {
                'success': True,
                'status': 'sem_alvo',
                'message': 'Nao ha demandas ativas para receber a alocacao.',
                'campo': campo_normalizado,
                'quantidade_solicitada': quantidade_total,
                'quantidade_alocada': 0.0,
                'quantidade_nao_alocada': quantidade_total,
                'alocacoes': []
            }

        itens_ativos = [item for item in itens if item.get('demanda_id') in demandas_ativas]
        itens_ativos.sort(
            key=lambda item: (
                0 if (demandas_ativas[item['demanda_id']].get('modalidade_logistica') == 'EXPRESS' or demandas_ativas[item['demanda_id']].get('is_flex')) else 1,
                -(float(demandas_ativas[item['demanda_id']].get('prioridade_manual') or 0)),
                demandas_ativas[item['demanda_id']].get('data_entrega') or '9999-12-31',
                demandas_ativas[item['demanda_id']].get('horario_coleta') or '23:59'
            )
        )

        restante = quantidade_total
        alocacoes = []
        for item in itens_ativos:
            if restante <= 0:
                break

            total_item = float(item.get('quantidade') or 0)
            atual_item = float(item.get(campo_normalizado) or 0)
            pendente = max(0.0, total_item - atual_item)
            if pendente <= 0:
                continue

            delta = min(restante, pendente)
            lote_id = str(uuid.uuid4())
            recon_result = demanda_items_service.registrar_producao_incremental(
                item.get('demanda_id'),
                int(item['id']),
                {campo_normalizado: delta},
                user_id=user_id,
                correlation_id=lote_id
            )

            alocacoes.append({
                'item_id': item['id'],
                'demanda_id': item.get('demanda_id'),
                'quantidade_alocada': delta,
                'campo': campo_normalizado,
                'motor_result': recon_result
            })
            restante -= delta

        qtd_alocada = quantidade_total - restante
        status = 'success' if restante <= 0 else ('partial' if qtd_alocada > 0 else 'sem_alvo')
        return {
            'success': True,
            'status': status,
            'campo': campo_normalizado,
            'sincrono': bool(sincrono),
            'quantidade_solicitada': quantidade_total,
            'quantidade_alocada': qtd_alocada,
            'quantidade_nao_alocada': restante,
            'alocacoes': alocacoes,
            'message': (
                'Alocacao avulsa concluida.'
                if status == 'success'
                else 'Alocacao avulsa parcial.'
                if status == 'partial'
                else 'Nenhuma alocacao avulsa realizada.'
            )
        }

    # ------------------------------------------------------------------
    # Alocacao por reserva (botao [-] da tela de Controle de Producao)
    #
    # O fluxo real e: producao -> alocacao na demanda -> saida fisica.
    # Alocar NAO e sair. O item continua fisicamente na empresa; ele apenas
    # deixa de estar disponivel para outra demanda. A saida fisica acontece na
    # reconciliacao, disparada pela finalizacao do item.
    #
    # Antes o endpoint chamava estoque_service.registrar_saida direto, e depois
    # a explosao de BOM da finalizacao consumia o mesmo componente de novo —
    # o ledger demanda_estoque_processado nao registrava a baixa da tela, entao
    # nada impedia a repeticao. Dupla baixa.
    # ------------------------------------------------------------------

    def reservar_alocacao_para_demanda(self, product_id, distributions: List[Dict[str, Any]],
                                       demanda_id=None, deposito_id=None,
                                       user_id: str = 'System', operation_id=None) -> Dict[str, Any]:
        """Reserva o produto para os itens de demanda informados.

        Incrementa `estoque_atual.reservado` (o disponivel cai, o fisico nao) e
        grava uma linha PENDENTE em `demanda_alocacoes_estoque` por item, para
        que a reconciliacao saiba o que ja estava separado para aquele item.
        """
        import hashlib
        import json

        correlation_id = str(uuid.UUID(str(operation_id))) if operation_id else str(uuid.uuid4())
        produto_id_norm = int(product_id) if str(product_id).isdigit() else product_id
        total = 0.0
        linhas = []

        for dist in distributions or []:
            item_id = dist.get('item_id')
            try:
                qtd = float(dist.get('quantidade') or 0)
            except (TypeError, ValueError):
                continue
            if not item_id or qtd <= 0:
                continue

            demanda_do_item = demanda_id
            if demanda_do_item is None:
                item_res = supabase_db.execute_with_retry(
                    self.itens_table.select('demanda_id').eq('id', item_id)
                )
                if item_res.data:
                    demanda_do_item = item_res.data[0].get('demanda_id')

            linhas.append({
                'demanda_id': str(demanda_do_item),
                'item_id': str(item_id),
                'produto_id': str(produto_id_norm),
                'correlation_id': correlation_id,
                'quantidade_alocada': qtd,
                'tipo_alocacao': 'RESERVA_PRODUCAO',
                'processo_origem': 'CONTROLE_PRODUCAO',
                'status': 'PENDENTE',
                'metadata': {'user_id': str(user_id)},
                'created_at': get_now_iso(),
            })
            total += qtd

        if not linhas:
            return {'success': False, 'message': 'Nenhuma distribuicao valida para reservar.',
                    'quantidade_reservada': 0.0}

        deposito_int = int(estoque_service._resolve_deposito(deposito_id))
        operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'nistiprint:reserva:{correlation_id}'))
        allocations = [{
            'demanda_id': row['demanda_id'],
            'item_id': row['item_id'],
            'produto_id': int(row['produto_id']),
            'quantidade': row['quantidade_alocada'],
            'correlation_id': correlation_id,
        } for row in linhas]
        allocations.sort(key=lambda row: (row['produto_id'], row['item_id'], row['demanda_id']))
        semantic = {'deposito_id': deposito_int, 'allocations': allocations}
        content_hash = hashlib.sha256(json.dumps(
            semantic, sort_keys=True, separators=(',', ':'), ensure_ascii=False
        ).encode('utf-8')).hexdigest()
        actor_id = int(user_id) if str(user_id).isdigit() else None
        response = supabase_db.rpc('reservar_alocacoes_estoque', {
            'p_operation_id': operation_id,
            'p_content_hash': content_hash,
            'p_source': {'correlation_id': correlation_id, 'processo': 'CONTROLE_PRODUCAO'},
            'p_actor_id': actor_id,
            'p_deposito_id': deposito_int,
            'p_allocations': allocations,
        }).execute()
        result = response.data[0] if isinstance(response.data, list) and response.data else response.data
        if not isinstance(result, dict) or result.get('status') != 'CONFIRMADO':
            raise RuntimeError(f'Falha ao confirmar reserva de estoque: {result!r}')

        return {
            'success': True,
            'correlation_id': correlation_id,
            'operation_id': operation_id,
            'quantidade_reservada': total,
            'itens': len(linhas),
        }

    # A antiga implementação não transacional foi removida; as versões ativas abaixo usam RPCs.

    def liberar_alocacao_item(self, item_id: int, quantidade: float, motivo: str = 'Liberação manual',
                              operation_id: str = None, user_id=None) -> Dict[str, Any]:
        """Libera somente o remanescente ainda reservado para um item."""
        import hashlib
        import json
        operation_id = str(uuid.UUID(operation_id)) if operation_id else str(uuid.uuid4())
        semantic = {'item_id': int(item_id), 'quantidade': str(float(quantidade)), 'motivo': motivo}
        content_hash = hashlib.sha256(json.dumps(
            semantic, sort_keys=True, separators=(',', ':'), ensure_ascii=False
        ).encode('utf-8')).hexdigest()
        actor_id = int(user_id) if str(user_id).isdigit() else None
        response = supabase_db.rpc('liberar_reserva_item_estoque', {
            'p_operation_id': operation_id,
            'p_content_hash': content_hash,
            'p_source': {'item_id': int(item_id), 'motivo': motivo},
            'p_actor_id': actor_id,
            'p_item_id': int(item_id),
            'p_quantidade': float(quantidade),
            'p_motivo': motivo,
        }).execute()
        result = response.data[0] if isinstance(response.data, list) and response.data else response.data
        if not isinstance(result, dict) or result.get('status') != 'CONFIRMADO':
            raise RuntimeError(f'Falha ao liberar alocação do item {item_id}: {result!r}')
        return result

    def consumir_alocacoes_do_item(self, item_id, deposito_id=None) -> float:
        raise RuntimeError(
            'Reservas são consumidas junto com o movimento CONS_INT na reconciliação; '
            'não libere a reserva antes do commit.'
        )

    def liberar_alocacao_por_demanda(self, demanda_id: int, quantidade: float,
                                     motivo: str = 'Liberação Automática', item_id=None,
                                     operation_id=None, user_id=None):
        """Compatibilidade segura: exige resolver um único item da demanda."""
        if item_id is None:
            rows = supabase_db.table('demanda_alocacoes_estoque').select('item_id').eq(
                'demanda_id', str(demanda_id)).eq('status', 'PENDENTE').execute().data or []
            ids = {row.get('item_id') for row in rows if row.get('item_id')}
            if len(ids) != 1:
                raise ValueError(
                    f'A demanda {demanda_id} possui {len(ids)} itens com reserva pendente; '
                    'a liberação deve identificar item_id.'
                )
            item_id = next(iter(ids))
        return self.liberar_alocacao_item(item_id, quantidade, motivo, operation_id, user_id)


# Instância singleton para manter a compatibilidade com importações existentes
demanda_alocacao_estoque_service = DemandaAlocacaoEstoqueService()
