"""
Sinalizacao Service - Serviço para geração e gerenciamento de sinalizações de demanda.

Este serviço cria sinalizações visuais (badges, alertas, indicadores) para demandas
de produção, baseando-se em contexto logístico, status de integração, estoque, etc.

Objetivos:
- Gerar sinalizações automáticas baseadas em regras
- Alertar sobre condições críticas (atrasos, estoque insuficiente, erros)
- Destacar informações relevantes (FLEX, FULFILLMENT, horário de corte próximo)
- Reduzir carga cognitiva ao guiar visualmente o usuário
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, date, time, timedelta
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.utils.date_utils import get_now, get_now_iso
import logging

logger = logging.getLogger("SinalizacaoService")


class SinalizacaoService:
    """Serviço para geração e gerenciamento de sinalizações de demanda."""

    def __init__(self):
        self.sinalizacoes_table = supabase_db.table('sinalizacoes_demanda')
        self.demandas_table = supabase_db.table('demandas_producao')
        self.itens_demanda_table = supabase_db.table('itens_demanda')
        self.integracao_canais_table = supabase_db.table('integracao_canais_config')

    # ========================================================================
    # MÉTODOS PÚBLICOS - Geração de Sinalizações
    # ========================================================================

    def generate_signals(self, demanda_id: str) -> List[Dict[str, Any]]:
        """
        Gera todas as sinalizações aplicáveis a uma demanda.

        Args:
            demanda_id: ID da demanda

        Returns:
            Lista de sinalizações geradas
        """
        try:
            # 1. Buscar demanda
            demanda = self._get_demanda(demanda_id)
            if not demanda:
                logger.warning(f"Demanda {demanda_id} não encontrada")
                return []

            sinalizacoes = []

            # 2. Verificar cada tipo de sinalização
            sinalizacoes.extend(self._check_flex(demanda))
            sinalizacoes.extend(self._check_fulfillment(demanda))
            sinalizacoes.extend(self._check_horario_corte_proximo(demanda))
            sinalizacoes.extend(self._check_pedido_vinculado(demanda))
            sinalizacoes.extend(self._check_integracao_erro(demanda))
            sinalizacoes.extend(self._check_estoque_insuficiente(demanda))
            sinalizacoes.extend(self._check_producao_atrasada(demanda))

            # 3. Salvar sinalizações no banco
            sinalizacoes_salvas = []
            for sinalizacao in sinalizacoes:
                salva = self._save_sinalizacao(demanda_id, sinalizacao)
                if salva:
                    sinalizacoes_salvas.append(salva)

            return sinalizacoes_salvas

        except Exception as e:
            logger.error(f"Erro ao gerar sinalizações para demanda {demanda_id}: {e}", exc_info=True)
            return []

    def check_flex_deadline(self, demanda_id: str) -> Optional[Dict[str, Any]]:
        """
        Verifica e gera sinalização FLEX se aplicável.

        Args:
            demanda_id: ID da demanda

        Returns:
            Sinalização FLEX ou None
        """
        demanda = self._get_demanda(demanda_id)
        if not demanda:
            return None

        sinalizacoes = self._check_flex(demanda)
        if sinalizacoes:
            return self._save_sinalizacao(demanda_id, sinalizacoes[0])
        return None

    def check_stock_alert(self, demanda_id: str) -> Optional[Dict[str, Any]]:
        """
        Verifica e gera sinalização de estoque insuficiente.

        Args:
            demanda_id: ID da demanda

        Returns:
            Sinalização de estoque ou None
        """
        demanda = self._get_demanda(demanda_id)
        if not demanda:
            return None

        sinalizacoes = self._check_estoque_insuficiente(demanda)
        if sinalizacoes:
            return self._save_sinalizacao(demanda_id, sinalizacoes[0])
        return None

    def check_integration_status(self, demanda_id: str) -> Optional[Dict[str, Any]]:
        """
        Verifica e gera sinalização de erro de integração.

        Args:
            demanda_id: ID da demanda

        Returns:
            Sinalização de integração ou None
        """
        demanda = self._get_demanda(demanda_id)
        if not demanda:
            return None

        sinalizacoes = self._check_integracao_erro(demanda)
        if sinalizacoes:
            return self._save_sinalizacao(demanda_id, sinalizacoes[0])
        return None

    def get_sinalizacoes_by_demanda(
        self,
        demanda_id: str,
        include_lidas: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Busca sinalizações de uma demanda.

        Args:
            demanda_id: ID da demanda
            include_lidas: Incluir sinalizações já lidas

        Returns:
            Lista de sinalizações
        """
        try:
            query = self.sinalizacoes_table.select("*") \
                .eq('demanda_id', demanda_id) \
                .eq('visivel', True)

            if not include_lidas:
                query = query.eq('lido', False)

            response = query.order('created_at', desc=True).execute()
            return response.data or []

        except Exception as e:
            logger.error(f"Erro ao buscar sinalizações: {e}", exc_info=True)
            return []

    def mark_as_read(self, sinalizacao_id: int) -> Optional[Dict[str, Any]]:
        """
        Marca sinalização como lida.

        Args:
            sinalizacao_id: ID da sinalização

        Returns:
            Sinalização atualizada ou None
        """
        try:
            response = self.sinalizacoes_table.update({'lido': True}) \
                .eq('id', sinalizacao_id) \
                .execute()
            return response.data[0] if response.data else None

        except Exception as e:
            logger.error(f"Erro ao marcar sinalização como lida: {e}", exc_info=True)
            return None

    def mark_all_as_read(self, demanda_id: str) -> int:
        """
        Marca todas as sinalizações de uma demanda como lidas.

        Args:
            demanda_id: ID da demanda

        Returns:
            Número de sinalizações atualizadas
        """
        try:
            response = self.sinalizacoes_table.update({'lido': True}) \
                .eq('demanda_id', demanda_id) \
                .execute()
            return len(response.data or [])

        except Exception as e:
            logger.error(f"Erro ao marcar todas como lidas: {e}", exc_info=True)
            return 0

    def hide_sinalizacao(self, sinalizacao_id: int) -> Optional[Dict[str, Any]]:
        """
        Esconde sinalização (não deleta).

        Args:
            sinalizacao_id: ID da sinalização

        Returns:
            Sinalização atualizada ou None
        """
        try:
            response = self.sinalizacoes_table.update({'visivel': False}) \
                .eq('id', sinalizacao_id) \
                .execute()
            return response.data[0] if response.data else None

        except Exception as e:
            logger.error(f"Erro ao esconder sinalização: {e}", exc_info=True)
            return None

    def clear_sinalizacoes(self, demanda_id: str) -> bool:
        """
        Limpa todas as sinalizações de uma demanda.

        Args:
            demanda_id: ID da demanda

        Returns:
            True se limpo, False se erro
        """
        try:
            response = self.sinalizacoes_table.delete() \
                .eq('demanda_id', demanda_id) \
                .execute()
            return True

        except Exception as e:
            logger.error(f"Erro ao limpar sinalizações: {e}", exc_info=True)
            return False

    def get_sinalizacoes_resumo(self, demanda_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Retorna resumo de sinalizações para múltiplas demandas.

        Args:
            demanda_ids: Lista de IDs de demandas

        Returns:
            Dicionário {demanda_id: [sinalizacoes]}
        """
        try:
            response = self.sinalizacoes_table.select("*") \
                .in_('demanda_id', demanda_ids) \
                .eq('visivel', True) \
                .order('severidade', desc=True) \
                .execute()

            resumo = {}
            for sinalizacao in (response.data or []):
                demanda_id = str(sinalizacao.get('demanda_id'))
                if demanda_id not in resumo:
                    resumo[demanda_id] = []
                resumo[demanda_id].append(sinalizacao)

            return resumo

        except Exception as e:
            logger.error(f"Erro ao obter resumo de sinalizações: {e}", exc_info=True)
            return {}

    # ========================================================================
    # MÉTODOS PRIVADOS - Verificações Específicas
    # ========================================================================

    def _check_flex(self, demanda: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Verifica condição FLEX."""
        sinalizacoes = []

        # Verificar se é FLEX
        is_flex = demanda.get('is_flex') or demanda.get('modalidade_logistica') == 'EXPRESS'
        
        if is_flex:
            # Verificar urgência
            data_entrega = demanda.get('data_entrega')
            horario_coleta = demanda.get('horario_coleta')
            
            severidade = 'INFO'
            dados = {'tipo': 'FLEX_PADRAO'}

            # Se entrega é hoje e horário está próximo, aumentar severidade
            if data_entrega and self._is_today(data_entrega):
                if horario_coleta and self._is_horario_proximo(horario_coleta, horas=2):
                    severidade = 'ATENCAO'
                    dados = {
                        'tipo': 'FLEX_URGENTE',
                        'mensagem': 'Entrega FLEX prevista para hoje',
                        'horario_corte': horario_coleta
                    }

            sinalizacoes.append({
                'tipo': 'FLEX',
                'severidade': severidade,
                'dados': dados
            })

        return sinalizacoes

    def _check_fulfillment(self, demanda: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Verifica condição FULFILLMENT."""
        sinalizacoes = []

        is_fulfillment = demanda.get('fulfillment') or demanda.get('modalidade_logistica') == 'FULFILLMENT'
        
        if is_fulfillment:
            sinalizacoes.append({
                'tipo': 'FULFILLMENT',
                'severidade': 'INFO',
                'dados': {
                    'tipo': 'FULFILLMENT_REPOSICAO',
                    'mensagem': 'Reposição de fulfillment externo'
                }
            })

        return sinalizacoes

    def _check_horario_corte_proximo(self, demanda: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Verifica horário de corte próximo."""
        sinalizacoes = []

        horario_coleta = demanda.get('horario_coleta')
        
        if horario_coleta and self._is_horario_proximo(horario_coleta, horas=2):
            # Verificar se ainda não está coletado
            status = demanda.get('status')
            if status not in ['CONCLUIDO', 'COLETA_PARCIAL']:
                sinalizacoes.append({
                    'tipo': 'HORARIO_CORTE_PROXIMO',
                    'severidade': 'ATENCAO',
                    'dados': {
                        'mensagem': 'Horário de corte nas próximas 2 horas',
                        'horario_corte': horario_coleta,
                        'status_atual': status
                    }
                })

        return sinalizacoes

    def _check_pedido_vinculado(self, demanda: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Verifica se há pedidos vinculados."""
        sinalizacoes = []

        # Verificar se demanda tem pedido número ou vínculo
        pedido_numero = demanda.get('pedido_numero')
        pedido_id = demanda.get('pedido_id')

        if pedido_numero or pedido_id:
            sinalizacoes.append({
                'tipo': 'PEDIDO_VINCULADO',
                'severidade': 'INFO',
                'dados': {
                    'mensagem': 'Demanda vinculada a pedido externo',
                    'pedido_numero': pedido_numero,
                    'pedido_id': pedido_id
                }
            })

        return sinalizacoes

    def _check_integracao_erro(self, demanda: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Verifica erros de integração."""
        sinalizacoes = []

        canal_venda_id = demanda.get('canal_venda_id')
        
        if canal_venda_id:
            # Verificar status da integração
            integracao = self._get_integracao_canal(canal_venda_id)
            
            if integracao:
                sync_status = integracao.get('sync_status')
                last_sync = integracao.get('last_sync')

                # Verificar se há erro de sincronização
                if sync_status == 'ERRO' or sync_status == 'ERROR':
                    sinalizacoes.append({
                        'tipo': 'INTEGRACAO_ERRO',
                        'severidade': 'CRITICO',
                        'dados': {
                            'mensagem': 'Erro de sincronização com plataforma',
                            'sync_status': sync_status,
                            'last_sync': last_sync
                        }
                    })
                elif last_sync and self._is_sync_antigo(last_sync, horas=24):
                    sinalizacoes.append({
                        'tipo': 'INTEGRACAO_ERRO',
                        'severidade': 'ATENCAO',
                        'dados': {
                            'mensagem': 'Sincronização desatualizada (>24h)',
                            'last_sync': last_sync,
                            'sync_status': sync_status
                        }
                    })

        return sinalizacoes

    def _check_estoque_insuficiente(self, demanda: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Verifica estoque insuficiente."""
        sinalizacoes = []

        demanda_id = demanda.get('id')
        
        if demanda_id:
            # Buscar itens da demanda
            itens = self._get_itens_demanda(demanda_id)
            
            itens_sem_estoque = []
            for item in itens:
                # Verificar se há campos de estoque/produção
                capas_produzidas = item.get('capas_produzidas_qtd') or 0
                miolos_prontos = item.get('miolos_prontos_retirada_qtd') or 0
                quantidade = item.get('quantidade') or 0

                # Se quantidade produzida < quantidade demandada
                if quantidade > 0:
                    if capas_produzidas < quantidade or mielos_prontos < quantidade:
                        itens_sem_estoque.append({
                            'item_id': item.get('id'),
                            'produto_nome': item.get('produto_nome'),
                            'quantidade_demandada': quantidade,
                            'capas_produzidas': capas_produzidas,
                            'mielos_prontos': mielos_prontos
                        })

            if itens_sem_estoque:
                sinalizacoes.append({
                    'tipo': 'ESTOQUE_INSUFICIENTE',
                    'severidade': 'CRITICO',
                    'dados': {
                        'mensagem': 'Itens com produção incompleta',
                        'itens': itens_sem_estoque,
                        'total_itens_afetados': len(itens_sem_estoque)
                    }
                })

        return sinalizacoes

    def _check_producao_atrasada(self, demanda: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Verifica produção atrasada."""
        sinalizacoes = []

        data_entrega = demanda.get('data_entrega')
        status = demanda.get('status')
        data_conclusao = demanda.get('data_conclusao')

        if data_entrega and status not in ['CONCLUIDO']:
            # Verificar se data de entrega já passou
            if self._is_data_atrasada(data_entrega):
                sinalizacoes.append({
                    'tipo': 'PRODUCAO_ATRASADA',
                    'severidade': 'CRITICO',
                    'dados': {
                        'mensagem': 'Produção atrasada em relação à data de entrega',
                        'data_entrega_prevista': data_entrega,
                        'status_atual': status,
                        'data_conclusao': data_conclusao
                    }
                })
            elif self._is_data_proxima(data_entrega, dias=1) and status == 'AGUARDANDO':
                sinalizacoes.append({
                    'tipo': 'PRODUCAO_ATRASADA',
                    'severidade': 'ATENCAO',
                    'dados': {
                        'mensagem': 'Produção ainda não iniciada e entrega próxima',
                        'data_entrega_prevista': data_entrega,
                        'status_atual': status
                    }
                })

        return sinalizacoes

    # ========================================================================
    # MÉTODOS PRIVADOS - Helpers
    # ========================================================================

    def _get_demanda(self, demanda_id: str) -> Optional[Dict[str, Any]]:
        """Busca demanda por ID."""
        try:
            response = self.demandas_table.select("*") \
                .eq('id', demanda_id) \
                .single() \
                .execute()
            return response.data
        except:
            return None

    def _get_itens_demanda(self, demanda_id: int) -> List[Dict[str, Any]]:
        """Busca itens de uma demanda."""
        try:
            response = self.itens_demanda_table.select("*") \
                .eq('demanda_id', demanda_id) \
                .execute()
            return response.data or []
        except:
            return []

    def _get_integracao_canal(self, canal_venda_id: int) -> Optional[Dict[str, Any]]:
        """Busca integração de um canal."""
        try:
            response = self.integracao_canais_table.select("*") \
                .eq('canal_venda_id', canal_venda_id) \
                .eq('is_active', True) \
                .single() \
                .execute()
            return response.data
        except:
            return None

    def _save_sinalizacao(
        self,
        demanda_id: str,
        sinalizacao_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Salva sinalização no banco."""
        try:
            # Verificar se já existe sinalização similar ativa
            existing = self.sinalizacoes_table.select("id") \
                .eq('demanda_id', demanda_id) \
                .eq('tipo', sinalizacao_data['tipo']) \
                .eq('visivel', True) \
                .execute()

            if existing.data:
                # Atualizar existente
                payload = {
                    'severidade': sinalizacao_data['severidade'],
                    'dados': sinalizacao_data['dados'],
                    'updated_at': get_now_iso()
                }
                response = self.sinalizacoes_table.update(payload) \
                    .eq('id', existing.data[0]['id']) \
                    .execute()
                return response.data[0] if response.data else None
            else:
                # Criar nova
                payload = {
                    'demanda_id': demanda_id,
                    'tipo': sinalizacao_data['tipo'],
                    'severidade': sinalizacao_data['severidade'],
                    'dados': sinalizacao_data['dados'],
                    'visivel': True,
                    'lido': False,
                    'created_at': get_now_iso()
                }
                response = self.sinalizacoes_table.insert(payload).execute()
                return response.data[0] if response.data else None

        except Exception as e:
            logger.error(f"Erro ao salvar sinalização: {e}", exc_info=True)
            return None

    def _is_today(self, data_str: str) -> bool:
        """Verifica se data é hoje."""
        try:
            data = datetime.fromisoformat(data_str.replace('Z', '+00:00')).date()
            return data == date.today()
        except:
            return False

    def _is_horario_proximo(self, horario_str: str, horas: int = 2) -> bool:
        """Verifica se horário está nas próximas X horas."""
        try:
            if isinstance(horario_str, str):
                horario = datetime.strptime(horario_str, '%H:%M').time()
            else:
                horario = horario_str

            agora = datetime.now().time()
            limite = (datetime.now() + timedelta(hours=horas)).time()

            return agora <= horario <= limite
        except:
            return False

    def _is_sync_antigo(self, last_sync_str: str, horas: int = 24) -> bool:
        """Verifica se última sincronização é antiga."""
        try:
            last_sync = datetime.fromisoformat(last_sync_str.replace('Z', '+00:00'))
            return datetime.now() - last_sync > timedelta(hours=horas)
        except:
            return False

    def _is_data_atrasada(self, data_str: str) -> bool:
        """Verifica se data já passou."""
        try:
            data = datetime.fromisoformat(data_str.replace('Z', '+00:00')).date()
            return data < date.today()
        except:
            return False

    def _is_data_proxima(self, data_str: str, dias: int = 1) -> bool:
        """Verifica se data está próxima (dentro de X dias)."""
        try:
            data = datetime.fromisoformat(data_str.replace('Z', '+00:00')).date()
            hoje = date.today()
            return 0 <= (data - hoje).days <= dias
        except:
            return False


# Instância singleton
sinalizacao_service = SinalizacaoService()
