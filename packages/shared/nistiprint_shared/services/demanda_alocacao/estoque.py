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
        """
        Agenda o processamento de estoque na fila legada.
        Mantido para compatibilidade com OPs e fluxos que ainda não usam eventos_v2.
        """
        if not correlation_id:
            correlation_id = str(uuid.uuid4())
            
        tarefa = {
            'demanda_id': demanda_id,
            'item_id': item_id,
            'produto_id': produto_id,
            'quantidade': float(incremento),
            'tipo_operacao': 'CONSUMO_BOM' if incremento > 0 else 'ESTORNO_BOM',
            'correlation_id': correlation_id,
            'user_id': str(user_id),
            'status': 'PENDENTE',
            'created_at': created_at or get_now_iso()
        }
        
        return supabase_db.table('fila_processamento_estoque').insert(tarefa).execute()

    def processar_fila_estoque(self, limit=10):
        """
        Processa a fila legada usando o novo motor unificado.
        """
        from nistiprint_shared.services.motor_reconciliacao_estoque import motor_reconciliacao_estoque
        return motor_reconciliacao_estoque.processar_fila_unificada(limit=limit)

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

    def liberar_alocacao_por_demanda(self, demanda_id: int, quantidade: float, motivo: str = "Liberação Automática"):
        """
        Libera alocações de reserva de estoque para uma demanda específica.
        
        Args:
            demanda_id: ID da demanda de produção
            quantidade: Quantidade a liberar (proporcional ao consumido)
            motivo: Motivo da liberação
        """
        try:
            from nistiprint_shared.database.supabase_db_service import supabase_db
            
            # Busca alocações pendentes para esta demanda
            response = supabase_db.table('demanda_alocacoes_estoque')\
                .select('*')\
                .eq('demanda_id', demanda_id)\
                .eq('status', 'PENDENTE')\
                .execute()
            
            if not response.data:
                # Sem alocações pendentes - isso é OK, nem toda demanda tem reservas
                return
            
            # Libera alocações proporcionalmente
            for alocacao in response.data:
                qtd_alocada = float(alocacao.get('quantidade_alocada', 0))
                if qtd_alocada <= 0:
                    continue
                
                # Calcula proporção a liberar
                qtd_liberar = min(qtd_alocada, quantidade)
                
                # Atualiza status para cancelada (liberada)
                supabase_db.table('demanda_alocacoes_estoque')\
                    .update({
                        'status': 'CANCELADA',
                        'cancelled_at': get_now_iso(),
                        'metadata': {
                            **alocacao.get('metadata', {}),
                            'liberacao_motivo': motivo,
                            'quantidade_liberada': qtd_liberar
                        }
                    })\
                    .eq('id', alocacao['id'])\
                    .execute()
                
                # Libera o estoque fisicamente (reservado → disponível)
                produto_id = alocacao.get('produto_id')
                if produto_id:
                    try:
                        estoque_service.liberar_reserva(
                            produto_id=produto_id,
                            quantidade=qtd_liberar,
                            deposito_id=None,  # Usa depósito padrão
                            ordem_id=None
                        )
                    except Exception as e:
                        print(f"AVISO: Erro ao liberar reserva do produto {produto_id}: {e}")
                        
        except Exception as e:
            print(f"ERRO ao liberar alocação para demanda {demanda_id}: {e}")
            # Não lança exceção - liberação de reserva é secundária

# Instância singleton para manter a compatibilidade com importações existentes
demanda_alocacao_estoque_service = DemandaAlocacaoEstoqueService()

