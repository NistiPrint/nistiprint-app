"""
Contexto Producao Service - Serviço para construir e gerenciar contextos unificados de produção.

Este serviço sintetiza todas as relações entre plataformas, canais, integrações,
logística, pedidos e demandas para fornecer uma visão contextual completa.

Objetivos:
- Construir contexto unificado para uma demanda ou pedido
- Calcular scores de priorização
- Fornecer dados para ordenação inteligente de produção
- Servir como base para sinalizações e autopreenchimento
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, date, time
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.utils.date_utils import get_now, get_now_iso
import logging

logger = logging.getLogger("ContextoProducaoService")


class ContextoProducaoService:
    """Serviço para construção e gerenciamento de contextos de produção."""

    def __init__(self):
        self.contextos_table = supabase_db.table('contextos_producao')
        self.demandas_table = supabase_db.table('demandas_producao')
        self.pedidos_table = supabase_db.table('pedidos')
        self.canais_venda_table = supabase_db.table('canais_venda')
        self.regras_logisticas_table = supabase_db.table('regras_logisticas_canal')
        self.integracao_canais_table = supabase_db.table('integracao_canais_config')
        self.pontos_coleta_table = supabase_db.table('pontos_coleta')
        self.plataformas_table = supabase_db.table('plataformas')

    # ========================================================================
    # MÉTODOS PÚBLICOS - Construção de Contexto
    # ========================================================================

    def build_context_for_demanda(self, demanda_id: str) -> Optional[Dict[str, Any]]:
        """
        Constrói contexto unificado para uma demanda de produção.

        Args:
            demanda_id: ID da demanda (string)

        Returns:
            Dicionário com contexto completo ou None se não encontrado
        """
        try:
            # 1. Buscar demanda com relacionamentos
            demanda = self._get_demanda_with_relations(demanda_id)
            if not demanda:
                logger.warning(f"Demanda {demanda_id} não encontrada")
                return None

            # 2. Buscar canal de venda
            canal = self._get_canal_venda(demanda.get('canal_venda_id'))
            if not canal:
                logger.warning(f"Canal {demanda.get('canal_venda_id')} não encontrado")
                return None

            # 3. Buscar regras logísticas do canal
            regras_logisticas = self._get_regras_logisticas_canal(demanda.get('canal_venda_id'))

            # 4. Buscar integração do canal
            integracao = self._get_integracao_canal(demanda.get('canal_venda_id'))

            # 5. Determinar modalidade logística (da demanda ou padrão do canal)
            modalidade = demanda.get('modalidade_logistica') or 'STANDARD'
            regra_modalidade = self._get_regra_por_modalidade(regras_logisticas, modalidade)

            # 6. Construir snapshots
            snapshot_plataforma = self._build_snapshot_plataforma(canal, demanda)
            snapshot_integracao = self._build_snapshot_integracao(integracao)
            snapshot_logistica = self._build_snapshot_logistica(demanda, regra_modalidade, canal)
            snapshot_temporal = self._build_snapshot_temporal(demanda, regra_modalidade)
            snapshot_priorizacao = self._build_snapshot_priorizacao(demanda, snapshot_logistica, snapshot_temporal)

            # 7. Construir contexto final
            contexto = {
                'id': self._generate_context_id(demanda_id),
                'tipo': 'DEMANDA_CONSOLIDADA' if demanda.get('tipo_demanda') == 'PLATAFORMA' else 'PEDIDO_UNICO',
                
                # Vínculos
                'pedido_id': demanda.get('pedido_id'),
                'demanda_id': int(demanda_id) if demanda_id.isdigit() else None,
                'canal_venda_id': canal.get('id'),
                'canal_venda_nome': canal.get('nome'),
                
                # Contextos
                'plataforma': snapshot_plataforma,
                'integracao': snapshot_integracao,
                'logistica': snapshot_logistica,
                'temporal': snapshot_temporal,
                'priorizacao': snapshot_priorizacao,
                'status': self._build_status(demanda)
            }

            return contexto

        except Exception as e:
            logger.error(f"Erro ao construir contexto para demanda {demanda_id}: {e}", exc_info=True)
            return None

    def build_context_for_pedido(self, pedido_id: int) -> Optional[Dict[str, Any]]:
        """
        Constrói contexto unificado para um pedido.

        Args:
            pedido_id: ID do pedido

        Returns:
            Dicionário com contexto completo ou None se não encontrado
        """
        try:
            # 1. Buscar pedido com relacionamentos
            pedido = self._get_pedido_with_relations(pedido_id)
            if not pedido:
                logger.warning(f"Pedido {pedido_id} não encontrado")
                return None

            # 2. Buscar canal de venda
            canal = self._get_canal_venda(pedido.get('canal_venda_id'))
            if not canal:
                logger.warning(f"Canal {pedido.get('canal_venda_id')} não encontrado")
                return None

            # 3. Buscar regras logísticas do canal
            regras_logisticas = self._get_regras_logisticas_canal(pedido.get('canal_venda_id'))

            # 4. Buscar integração do canal
            integracao = self._get_integracao_canal(pedido.get('canal_venda_id'))

            # 5. Determinar modalidade logística
            is_flex = pedido.get('is_flex', False)
            modalidade = 'EXPRESS' if is_flex else 'STANDARD'
            regra_modalidade = self._get_regra_por_modalidade(regras_logisticas, modalidade)

            # 6. Construir snapshots
            snapshot_plataforma = self._build_snapshot_plataforma(canal, pedido)
            snapshot_integracao = self._build_snapshot_integracao(integracao)
            snapshot_logistica = self._build_snapshot_logistica(pedido, regra_modalidade, canal)
            snapshot_temporal = self._build_snapshot_temporal(pedido, regra_modalidade)
            snapshot_priorizacao = self._build_snapshot_priorizacao(pedido, snapshot_logistica, snapshot_temporal)

            # 7. Construir contexto final
            contexto = {
                'id': self._generate_context_id(f"pedido_{pedido_id}"),
                'tipo': 'PEDIDO_UNICO',
                
                # Vínculos
                'pedido_id': pedido_id,
                'demanda_id': None,
                'canal_venda_id': canal.get('id'),
                'canal_venda_nome': canal.get('nome'),
                
                # Contextos
                'plataforma': snapshot_plataforma,
                'integracao': snapshot_integracao,
                'logistica': snapshot_logistica,
                'temporal': snapshot_temporal,
                'priorizacao': snapshot_priorizacao,
                'status': self._build_status_pedido(pedido)
            }

            return contexto

        except Exception as e:
            logger.error(f"Erro ao construir contexto para pedido {pedido_id}: {e}", exc_info=True)
            return None

    def get_production_order(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Retorna lista de demandas ordenadas para produção.

        Args:
            filters: Filtros opcionais (canal_venda_id, status, modalidade, etc.)
            limit: Limite de resultados

        Returns:
            Lista de contextos de produção ordenados por prioridade
        """
        try:
            # 1. Construir query base
            query = self.demandas_table.select("*")

            # 2. Aplicar filtros
            if filters:
                if filters.get('canal_venda_id'):
                    query = query.eq('canal_venda_id', filters['canal_venda_id'])
                
                if filters.get('status'):
                    query = query.in_('status', filters['status'])
                
                if filters.get('modalidade_logistica'):
                    query = query.eq('modalidade_logistica', filters['modalidade_logistica'])
                
                if filters.get('is_flex') is not None:
                    query = query.eq('is_flex', filters['is_flex'])

            # 3. Ordenar por prioridade (critérios múltiplos)
            query = query.order('prioridade_manual', desc=True) \
                        .order('prioridade', desc=True) \
                        .order('data_entrega', desc=False) \
                        .order('horario_coleta', desc=False) \
                        .limit(limit)

            response = query.execute()
            demandas = response.data

            # 4. Construir contexto para cada demanda
            contextos = []
            for demanda in demandas:
                contexto = self.build_context_for_demanda(str(demanda.get('id')))
                if contexto:
                    contextos.append(contexto)

            return contextos

        except Exception as e:
            logger.error(f"Erro ao obter ordem de produção: {e}", exc_info=True)
            return []

    def calculate_priority_score(self, contexto: Dict[str, Any]) -> int:
        """
        Calcula score de prioridade para um contexto.

        Args:
            contexto: Dicionário de contexto de produção

        Returns:
            Score de prioridade (inteiro)
        """
        score = 0
        logistica = contexto.get('logistica', {})
        temporal = contexto.get('temporal', {})
        priorizacao = contexto.get('priorizacao', {})

        # Score base por modalidade
        modalidade_scores = {
            'EXPRESS': 100,
            'FULFILLMENT': 75,
            'STANDARD': 25,
            'RETIRADA': 10
        }
        score += modalidade_scores.get(logistica.get('modalidade'), 0)

        # Bônus FLEX
        if logistica.get('is_flex'):
            score += 50

        # Bônus Fulfillment
        if logistica.get('is_fulfillment'):
            score += 30

        # Bônus urgência temporal
        categoria_scores = {
            'URGENTE': 80,
            'HOJE': 60,
            'AMANHA': 40,
            'FUTURO': 10
        }
        score += categoria_scores.get(temporal.get('categoria_temporal'), 0)

        # Bônus horário de corte (quanto mais cedo, maior prioridade)
        horario_corte = logistica.get('horario_corte')
        if horario_corte:
            try:
                hora = int(horario_corte.split(':')[0])
                score += (24 - hora)
            except:
                pass

        # Adicionar score manual da priorização
        score += priorizacao.get('score', 0)

        return score

    def save_context(self, contexto: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Salva contexto no banco de dados.

        Args:
            contexto: Dicionário de contexto de produção

        Returns:
            Contexto salvo ou None se erro
        """
        try:
            payload = {
                'tipo': contexto.get('tipo'),
                'pedido_id': contexto.get('pedido_id'),
                'demanda_id': contexto.get('demanda_id'),
                'canal_venda_id': contexto.get('canal_venda_id'),
                'snapshot_plataforma': contexto.get('plataforma', {}),
                'snapshot_integracao': contexto.get('integracao', {}),
                'snapshot_logistica': contexto.get('logistica', {}),
                'snapshot_temporal': contexto.get('temporal', {}),
                'snapshot_priorizacao': contexto.get('priorizacao', {}),
                'is_active': True,
                'created_at': get_now_iso(),
                'updated_at': get_now_iso()
            }

            response = self.contextos_table.insert(payload).execute()
            return response.data[0] if response.data else None

        except Exception as e:
            logger.error(f"Erro ao salvar contexto: {e}", exc_info=True)
            return None

    def update_context(self, contexto_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Atualiza contexto existente.

        Args:
            contexto_id: ID do contexto
            updates: Campos para atualizar

        Returns:
            Contexto atualizado ou None se erro
        """
        try:
            payload = {
                'updated_at': get_now_iso(),
                **updates
            }

            response = self.contextos_table.update(payload).eq('id', contexto_id).execute()
            return response.data[0] if response.data else None

        except Exception as e:
            logger.error(f"Erro ao atualizar contexto: {e}", exc_info=True)
            return None

    def get_context_by_demanda_id(self, demanda_id: str) -> Optional[Dict[str, Any]]:
        """
        Busca contexto por ID da demanda.

        Args:
            demanda_id: ID da demanda

        Returns:
            Contexto ou None se não encontrado
        """
        try:
            response = self.contextos_table.select("*") \
                .eq('demanda_id', demanda_id) \
                .eq('is_active', True) \
                .single() \
                .execute()

            return response.data if response.data else None

        except Exception as e:
            logger.error(f"Erro ao buscar contexto por demanda_id: {e}", exc_info=True)
            return None

    def get_context_by_pedido_id(self, pedido_id: int) -> Optional[Dict[str, Any]]:
        """
        Busca contexto por ID do pedido.

        Args:
            pedido_id: ID do pedido

        Returns:
            Contexto ou None se não encontrado
        """
        try:
            response = self.contextos_table.select("*") \
                .eq('pedido_id', pedido_id) \
                .eq('is_active', True) \
                .single() \
                .execute()

            return response.data if response.data else None

        except Exception as e:
            logger.error(f"Erro ao buscar contexto por pedido_id: {e}", exc_info=True)
            return None

    # ========================================================================
    # MÉTODOS PRIVADOS - Helpers de Construção
    # ========================================================================

    def _get_demanda_with_relations(self, demanda_id: str) -> Optional[Dict[str, Any]]:
        """Busca demanda com relacionamentos."""
        try:
            response = self.demandas_table.select("*") \
                .eq('id', demanda_id) \
                .single() \
                .execute()
            return response.data
        except:
            return None

    def _get_pedido_with_relations(self, pedido_id: int) -> Optional[Dict[str, Any]]:
        """Busca pedido com relacionamentos."""
        try:
            response = self.pedidos_table.select("*") \
                .eq('id', pedido_id) \
                .single() \
                .execute()
            return response.data
        except:
            return None

    def _get_canal_venda(self, canal_venda_id: Optional[int]) -> Optional[Dict[str, Any]]:
        """Busca canal de venda."""
        if not canal_venda_id:
            return None
        
        try:
            response = self.canais_venda_table.select("*") \
                .eq('id', canal_venda_id) \
                .single() \
                .execute()
            return response.data
        except:
            return None

    def _get_regras_logisticas_canal(self, canal_venda_id: Optional[int]) -> List[Dict[str, Any]]:
        """Busca regras logísticas de um canal."""
        if not canal_venda_id:
            return []
        
        try:
            response = self.regras_logisticas_table.select("*, pontos_coleta(nome)") \
                .eq('canal_venda_id', canal_venda_id) \
                .order('prioridade_uso', desc=True) \
                .execute()
            return response.data or []
        except:
            return []

    def _get_integracao_canal(self, canal_venda_id: Optional[int]) -> Optional[Dict[str, Any]]:
        """Busca integração de um canal."""
        if not canal_venda_id:
            return None
        
        try:
            response = self.integracao_canais_table.select("*") \
                .eq('canal_venda_id', canal_venda_id) \
                .eq('is_active', True) \
                .eq('is_primary', True) \
                .single() \
                .execute()
            return response.data
        except:
            return None

    def _get_regra_por_modalidade(
        self,
        regras: List[Dict[str, Any]],
        modalidade: str
    ) -> Optional[Dict[str, Any]]:
        """Busca regra logística por modalidade."""
        for regra in regras:
            if regra.get('modalidade') == modalidade:
                return regra
        return None

    def _build_snapshot_plataforma(
        self,
        canal: Dict[str, Any],
        origem: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Constrói snapshot da plataforma."""
        plataforma_nome = canal.get('plataforma_nome') or 'Desconhecida'
        
        return {
            'nome': plataforma_nome,
            'tipo': self._infer_plataforma_tipo(plataforma_nome),
            'pedido_externo_id': origem.get('pedido_numero') or origem.get('pedido_externo_id', '')
        }

    def _build_snapshot_integracao(
        self,
        integracao: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Constrói snapshot da integração."""
        if not integracao:
            return {
                'marketplace_integration_id': None,
                'bling_integration_id': None,
                'bling_loja_id': None
            }

        return {
            'marketplace_integration_id': integracao.get('marketplace_integration_id'),
            'bling_integration_id': integracao.get('bling_integration_id'),
            'bling_loja_id': integracao.get('bling_loja_id')
        }

    def _build_snapshot_logistica(
        self,
        origem: Dict[str, Any],
        regra_modalidade: Optional[Dict[str, Any]],
        canal: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Constrói snapshot da logística.
        
        REGRA DE PRECEDÊNCIA PARA horario_coleta:
        1. regras_logisticas_canal.horario_limite WHERE (canal_venda_id, modalidade) — FONTE CANÔNICA
        2. FALLBACK: canais_venda.horario_coleta — Legado, será depreciado
        3. FALLBACK: '23:59' — Default se nada configurado
        
        Esta função implementa explicitamente a regra de que a fonte primária de
        horario_coleta é sempre a combinação (canal, modalidade), nunca o campo
        genérico canais_venda.horario_coleta.
        """
        modalidade = origem.get('modalidade_logistica') or 'STANDARD'

        # VALORES DEFAULT
        horario_corte = '23:59'
        ponto_coleta_id = None
        ponto_coleta_nome = None
        tipo_envio = 'COLETA_LOCAL'

        # PRIORIDADE 1: Usar dados da regra logística por modalidade (FONTE CANÔNICA)
        if regra_modalidade:
            horario_corte = regra_modalidade.get('horario_limite', '23:59')
            ponto_coleta_id = regra_modalidade.get('ponto_coleta_id')
            ponto_coleta_nome = regra_modalidade.get('ponto_coleta_nome')
            tipo_envio = regra_modalidade.get('tipo_envio', 'COLETA_LOCAL')
            
            logger.debug(
                "Horário de corte derivado de regras_logisticas_canal: %s (canal=%s, modalidade=%s)",
                horario_corte,
                canal.get('id') if canal else None,
                modalidade
            )
        
        # PRIORIDADE 2: Fallback para canais_venda.horario_coleta (LEGADO)
        elif canal:
            if canal.get('horario_coleta'):
                horario_corte = canal.get('horario_coleta')
                logger.warning(
                    "Horário de corte derivado de canais_venda.horario_coleta (LEGADO). "
                    "Considere configurar regras_logisticas_canal para (canal=%s, modalidade=%s).",
                    canal.get('id'),
                    modalidade
                )

        return {
            'modalidade': modalidade,
            'tipo_envio': tipo_envio,
            'ponto_coleta_id': ponto_coleta_id,
            'ponto_coleta_nome': ponto_coleta_nome,
            'horario_corte': horario_corte if isinstance(horario_corte, str) else str(horario_corte),
            'is_flex': origem.get('is_flex', False) or modalidade == 'EXPRESS',
            'is_fulfillment': origem.get('fulfillment', False) or modalidade == 'FULFILLMENT',
            # Metadados para debug/auditoria
            '_fonte_horario_corte': 'regras_logisticas_canal' if regra_modalidade else ('canais_venda' if canal and canal.get('horario_coleta') else 'default')
        }

    def _build_snapshot_temporal(
        self,
        origem: Dict[str, Any],
        regra_modalidade: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Constrói snapshot temporal."""
        data_entrega_str = origem.get('data_entrega')
        data_pedido_str = origem.get('created_at') or get_now_iso()
        
        # Parse das datas
        try:
            data_entrega = datetime.fromisoformat(data_entrega_str.replace('Z', '+00:00')).date() if data_entrega_str else date.today()
            data_pedido = datetime.fromisoformat(data_pedido_str.replace('Z', '+00:00')).date() if data_pedido_str else date.today()
        except:
            data_entrega = date.today()
            data_pedido = date.today()

        # Calcular categoria temporal
        categoria = self._categorizar_temporal(data_entrega)

        # Calcular deadline final
        deadline_final = '23:59'
        if regra_modalidade and regra_modalidade.get('horario_limite'):
            deadline_final = regra_modalidade.get('horario_limite', '23:59')
            if not isinstance(deadline_final, str):
                deadline_final = str(deadline_final)

        return {
            'data_pedido': data_pedido.isoformat(),
            'data_limite_envio': data_entrega.isoformat(),
            'data_promessa_cliente': data_entrega.isoformat(),
            'categoria_temporal': categoria,
            'deadline_final': deadline_final
        }

    def _build_snapshot_priorizacao(
        self,
        origem: Dict[str, Any],
        logistica: Dict[str, Any],
        temporal: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Constrói snapshot de priorização."""
        score = 0
        fatores = []

        # Fatores de modalidade
        modalidade = logistica.get('modalidade', 'STANDARD')
        if modalidade == 'EXPRESS':
            score += 100
            fatores.append('EXPRESS')
        elif modalidade == 'FULFILLMENT':
            score += 75
            fatores.append('FULFILLMENT')

        # Fator FLEX
        if logistica.get('is_flex'):
            score += 50
            fatores.append('FLEX')

        # Fator urgência temporal
        categoria = temporal.get('categoria_temporal')
        if categoria == 'URGENTE':
            score += 80
            fatores.append('URGENTE')
        elif categoria == 'HOJE':
            score += 60
            fatores.append('HOJE')
        elif categoria == 'AMANHA':
            score += 40
            fatores.append('AMANHA')

        # Prioridade manual
        prioridade_manual = origem.get('prioridade_manual', 0) or origem.get('prioridade', 0)
        score += prioridade_manual * 10 if prioridade_manual else 0

        return {
            'score': score,
            'fatores': fatores,
            'prioridade_manual': prioridade_manual
        }

    def _build_status(self, demanda: Dict[str, Any]) -> Dict[str, Any]:
        """Constrói snapshot de status para demanda."""
        status_producao = demanda.get('status', 'AGUARDANDO')
        
        # Mapear para status padronizado
        status_map = {
            'AGUARDANDO': 'AGUARDANDO',
            'EM_PRODUCAO': 'EM_PRODUCAO',
            'COLETA_PARCIAL': 'COLETA_PARCIAL',
            'CONCLUIDO': 'CONCLUIDO',
            'CANCELADO': 'CONCLUIDO'  # Tratado como finalizado
        }

        return {
            'producao': status_map.get(status_producao, 'AGUARDANDO'),
            'sincronizacao': 'SINCRONIZADO'  # Assumir sincronizado se já está no sistema
        }

    def _build_status_pedido(self, pedido: Dict[str, Any]) -> Dict[str, Any]:
        """Constrói snapshot de status para pedido."""
        return {
            'producao': 'AGUARDANDO',  # Pedido ainda não virou demanda
            'sincronizacao': 'SINCRONIZADO' if pedido.get('origem') in ['SHOPEE', 'BLING'] else 'PENDENTE'
        }

    def _categorizar_temporal(self, data_entrega: date) -> str:
        """Categoriza data temporalmente."""
        hoje = date.today()
        amanha = hoje + timedelta(days=1)

        if data_entrega == hoje:
            return 'HOJE'
        elif data_entrega == amanha:
            return 'AMANHA'
        elif data_entrega < hoje:
            return 'URGENTE'  # Atrasado
        else:
            return 'FUTURO'

    def _infer_plataforma_tipo(self, plataforma_nome: str) -> str:
        """Inferir tipo de plataforma pelo nome."""
        marketplace_names = ['shopee', 'amazon', 'mercadolivre', 'shein', 'tiktok']
        erp_names = ['bling', 'totvs', 'sap']

        nome_lower = plataforma_nome.lower()
        
        if any(name in nome_lower for name in marketplace_names):
            return 'MARKETPLACE'
        elif any(name in nome_lower for name in erp_names):
            return 'ERP'
        else:
            return 'ECOMMERCE'

    def _generate_context_id(self, identifier: str) -> str:
        """Gera ID único para contexto."""
        import uuid
        return str(uuid.uuid4())


# Instância singleton
contexto_producao_service = ContextoProducaoService()
