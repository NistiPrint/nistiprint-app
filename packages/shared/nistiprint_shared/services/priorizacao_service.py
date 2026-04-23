"""
Priorizacao Service - Serviço para aplicação de regras de priorização de demandas.

Este serviço aplica regras configuráveis para calcular scores de prioridade
e ordenar demandas de produção de forma inteligente.

Objetivos:
- Aplicar regras de priorização configuráveis
- Calcular scores compostos de prioridade
- Identificar fatores que influenciaram a priorização
- Permitir reordenação dinâmica baseada em critérios de negócio
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, date, time, timedelta
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.utils.date_utils import get_now, get_now_iso
import logging

logger = logging.getLogger("PriorizacaoService")


class PriorizacaoService:
    """Serviço para aplicação de regras de priorização."""

    def __init__(self):
        self.regras_table = supabase_db.table('regras_priorizacao')
        self.demandas_table = supabase_db.table('demandas_producao')

    # ========================================================================
    # MÉTODOS PÚBLICOS - Aplicação de Regras
    # ========================================================================

    def apply_rules(self, demandas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Aplica regras de priorização a uma lista de demandas.

        Args:
            demandas: Lista de demandas (dicionários)

        Returns:
            Lista de demandas com scores e fatores de priorização calculados
        """
        try:
            # 1. Buscar regras ativas ordenadas por prioridade
            regras = self._get_regras_ativas()
            
            if not regras:
                logger.info("Nenhuma regra de priorização encontrada")
                return self._calculate_default_priority(demandas)

            # 2. Para cada demanda, aplicar regras e calcular score
            demandas_priorizadas = []
            for demanda in demandas:
                demanda_com_prioridade = self._apply_rules_to_demanda(demanda, regras)
                demandas_priorizadas.append(demanda_com_prioridade)

            # 3. Ordenar por score (decrescente) e critérios secundários
            demandas_ordenadas = self._sort_demandas(demandas_priorizadas)

            return demandas_ordenadas

        except Exception as e:
            logger.error(f"Erro ao aplicar regras de priorização: {e}", exc_info=True)
            return self._calculate_default_priority(demandas)

    def calculate_score(
        self,
        demanda: Dict[str, Any],
        contexto: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Calcula score de prioridade para uma demanda.

        Args:
            demanda: Dicionário da demanda
            contexto: Contexto de produção opcional (já calculado)

        Returns:
            Score de prioridade (inteiro)
        """
        try:
            # Se contexto já foi fornecido, usar score do contexto
            if contexto and contexto.get('priorizacao'):
                return contexto['priorizacao'].get('score', 0)

            # Calcular score base
            score_base = self._calculate_base_score(demanda)

            # Aplicar regras
            regras = self._get_regras_ativas()
            score_regras = 0
            for regra in regras:
                if self._matches_conditions(demanda, regra.get('condicoes', {})):
                    acao = regra.get('acao', {})
                    if acao.get('tipo') == 'ADD_SCORE':
                        score_regras += acao.get('valor', 0)

            return score_base + score_regras

        except Exception as e:
            logger.error(f"Erro ao calcular score: {e}", exc_info=True)
            return 0

    def get_priority_factors(self, demanda: Dict[str, Any]) -> List[str]:
        """
        Retorna lista de fatores que influenciaram a prioridade.

        Args:
            demanda: Dicionário da demanda

        Returns:
            Lista de fatores (strings)
        """
        fatores = []

        # Fatores de modalidade
        modalidade = demanda.get('modalidade_logistica')
        if modalidade == 'EXPRESS':
            fatores.append('EXPRESS')
        elif modalidade == 'FULFILLMENT':
            fatores.append('FULFILLMENT')

        # Fatores de flags
        if demanda.get('is_flex'):
            fatores.append('FLEX')
        
        if demanda.get('fulfillment'):
            fatores.append('FULFILLMENT_FLAG')

        # Fatores de classificação
        classificacao = demanda.get('classificacao_cliente')
        if classificacao == 'B2B':
            fatores.append('B2B')
        elif classificacao == 'INTERNO':
            fatores.append('INTERNO')

        # Fatores temporais
        categoria = self._categorizar_temporal(demanda.get('data_entrega'))
        if categoria == 'URGENTE':
            fatores.append('URGENTE')
        elif categoria == 'HOJE':
            fatores.append('HOJE')
        elif categoria == 'AMANHA':
            fatores.append('AMANHA')

        # Fatores de horário de corte
        horario_coleta = demanda.get('horario_coleta')
        if horario_coleta and self._is_horario_corte_proximo(horario_coleta):
            fatores.append('HORARIO_CORTE_PROXIMO')

        # Fatores de regras aplicadas
        regras = self._get_regras_ativas()
        for regra in regras:
            if self._matches_conditions(demanda, regra.get('condicoes', {})):
                fatores.extend(regra.get('acao', {}).get('fatores', []))

        # Remover duplicatas mantendo ordem
        return list(dict.fromkeys(fatores))

    def get_regras_aplicaveis(self, demanda: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Retorna regras que se aplicam a uma demanda.

        Args:
            demanda: Dicionário da demanda

        Returns:
            Lista de regras aplicáveis
        """
        regras = self._get_regras_ativas()
        return [r for r in regras if self._matches_conditions(demanda, r.get('condicoes', {}))]

    # ========================================================================
    # MÉTODOS DE GERENCIAMENTO DE REGRAS
    # ========================================================================

    def create_regra(self, regra_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Cria nova regra de priorização.

        Args:
            regra_data: Dados da regra

        Returns:
            Regra criada ou None se erro
        """
        try:
            payload = {
                'nome': regra_data.get('nome'),
                'descricao': regra_data.get('descricao'),
                'condicoes': regra_data.get('condicoes', {}),
                'acao': regra_data.get('acao', {}),
                'ativa': regra_data.get('ativa', True),
                'prioridade_regra': regra_data.get('prioridade_regra', 0),
                'created_at': get_now_iso(),
                'updated_at': get_now_iso()
            }

            response = self.regras_table.insert(payload).execute()
            return response.data[0] if response.data else None

        except Exception as e:
            logger.error(f"Erro ao criar regra: {e}", exc_info=True)
            return None

    def update_regra(self, regra_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Atualiza regra existente.

        Args:
            regra_id: ID da regra
            updates: Campos para atualizar

        Returns:
            Regra atualizada ou None se erro
        """
        try:
            payload = {
                'updated_at': get_now_iso(),
                **updates
            }

            response = self.regras_table.update(payload).eq('id', regra_id).execute()
            return response.data[0] if response.data else None

        except Exception as e:
            logger.error(f"Erro ao atualizar regra: {e}", exc_info=True)
            return None

    def delete_regra(self, regra_id: int) -> bool:
        """
        Exclui regra.

        Args:
            regra_id: ID da regra

        Returns:
            True se excluído, False se erro
        """
        try:
            response = self.regras_table.delete().eq('id', regra_id).execute()
            return len(response.data) > 0

        except Exception as e:
            logger.error(f"Erro ao excluir regra: {e}", exc_info=True)
            return False

    def get_all_regras(self, include_inactive: bool = False) -> List[Dict[str, Any]]:
        """
        Retorna todas as regras.

        Args:
            include_inactive: Incluir regras inativas

        Returns:
            Lista de regras
        """
        try:
            query = self.regras_table.select("*").order('prioridade_regra', desc=True)
            
            if not include_inactive:
                query = query.eq('ativa', True)

            response = query.execute()
            return response.data or []

        except Exception as e:
            logger.error(f"Erro ao buscar regras: {e}", exc_info=True)
            return []

    def toggle_regra(self, regra_id: int) -> Optional[Dict[str, Any]]:
        """
        Alterna status ativo/inativo de uma regra.

        Args:
            regra_id: ID da regra

        Returns:
            Regra atualizada ou None se erro
        """
        try:
            # Buscar regra atual
            response = self.regras_table.select("ativa").eq('id', regra_id).single().execute()
            if not response.data:
                return None

            current_ativa = response.data.get('ativa', True)
            
            # Alternar
            return self.update_regra(regra_id, {'ativa': not current_ativa})

        except Exception as e:
            logger.error(f"Erro ao alternar regra: {e}", exc_info=True)
            return None

    # ========================================================================
    # MÉTODOS PRIVADOS - Helpers
    # ========================================================================

    def _get_regras_ativas(self) -> List[Dict[str, Any]]:
        """Busca regras ativas ordenadas por prioridade."""
        try:
            response = self.regras_table.select("*") \
                .eq('ativa', True) \
                .order('prioridade_regra', desc=True) \
                .execute()
            return response.data or []
        except Exception as e:
            logger.error(f"Erro ao buscar regras ativas: {e}", exc_info=True)
            return []

    def _apply_rules_to_demanda(
        self,
        demanda: Dict[str, Any],
        regras: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Aplica regras a uma demanda específica."""
        # Copiar demanda para não modificar original
        demanda_copy = dict(demanda)

        # Calcular score base
        score_base = self._calculate_base_score(demanda)
        fatores = []

        # Aplicar cada regra
        prioridade_set = None
        mover_topo = False
        
        for regra in regras:
            if self._matches_conditions(demanda, regra.get('condicoes', {})):
                acao = regra.get('acao', {})
                tipo_acao = acao.get('tipo')

                if tipo_acao == 'ADD_SCORE':
                    score_base += acao.get('valor', 0)
                    fatores.extend(acao.get('fatores', []))
                elif tipo_acao == 'SET_PRIORIDADE':
                    prioridade_set = acao.get('valor')
                    fatores.extend(acao.get('fatores', []))
                elif tipo_acao == 'MOVER_TOPO':
                    mover_topo = True
                    fatores.extend(acao.get('fatores', []))

        # Montar resultado
        demanda_copy['priority_score'] = score_base
        demanda_copy['priority_fatores'] = list(dict.fromkeys(fatores))  # Remover duplicatas
        demanda_copy['regras_aplicadas'] = len(fatores) > 0

        if prioridade_set is not None:
            demanda_copy['prioridade_calculada'] = prioridade_set

        if mover_topo:
            demanda_copy['mover_topo'] = True

        return demanda_copy

    def _calculate_base_score(self, demanda: Dict[str, Any]) -> int:
        """Calcula score base sem regras."""
        score = 0

        # Score por modalidade
        modalidade_scores = {
            'EXPRESS': 100,
            'FULFILLMENT': 75,
            'STANDARD': 25,
            'RETIRADA': 10
        }
        modalidade = demanda.get('modalidade_logistica', 'STANDARD')
        score += modalidade_scores.get(modalidade, 0)

        # Bônus FLEX
        if demanda.get('is_flex'):
            score += 50

        # Bônus Fulfillment
        if demanda.get('fulfillment'):
            score += 30

        # Bônus por classificação
        classificacao_scores = {
            'B2B': 20,
            'INTERNO': 5
        }
        classificacao = demanda.get('classificacao_cliente')
        score += classificacao_scores.get(classificacao, 0)

        # Bônus urgência temporal
        categoria = self._categorizar_temporal(demanda.get('data_entrega'))
        categoria_scores = {
            'URGENTE': 80,
            'HOJE': 60,
            'AMANHA': 40,
            'FUTURO': 10
        }
        score += categoria_scores.get(categoria, 0)

        # Bônus horário de corte
        horario_coleta = demanda.get('horario_coleta')
        if horario_coleta:
            try:
                if isinstance(horario_coleta, str):
                    hora = int(horario_coleta.split(':')[0])
                    score += (24 - hora)
            except:
                pass

        # Prioridade manual
        prioridade_manual = demanda.get('prioridade_manual', 0) or demanda.get('prioridade', 0)
        score += (prioridade_manual or 0) * 10

        return score

    def _matches_conditions(
        self,
        demanda: Dict[str, Any],
        condicoes: Dict[str, Any]
    ) -> bool:
        """Verifica se demanda corresponde às condições de uma regra."""
        if not condicoes:
            return True  # Sem condições = sempre aplica

        # Verificar canal_venda_ids
        if 'canal_venda_ids' in condicoes:
            if demanda.get('canal_venda_id') not in condicoes['canal_venda_ids']:
                return False

        # Verificar plataforma_nomes
        if 'plataforma_nomes' in condicoes:
            plataforma_nome = demanda.get('plataforma_nome', '').lower()
            if not any(nome.lower() in plataforma_nome for nome in condicoes['plataforma_nomes']):
                return False

        # Verificar modalidade_logistica
        if 'modalidade_logistica' in condicoes:
            if demanda.get('modalidade_logistica') not in condicoes['modalidade_logistica']:
                return False

        # Verificar tipo_demanda
        if 'tipo_demanda' in condicoes:
            if demanda.get('tipo_demanda') not in condicoes['tipo_demanda']:
                return False

        # Verificar faixa_quantidade
        if 'faixa_quantidade' in condicoes:
            quantidade = demanda.get('quantidade', 0)
            faixa = condicoes['faixa_quantidade']
            if quantidade < faixa.get('min', 0) or quantidade > faixa.get('max', float('inf')):
                return False

        # Verificar horario_corte
        if 'horario_corte' in condicoes:
            horario = demanda.get('horario_coleta')
            if horario:
                try:
                    if isinstance(horario, str):
                        horario_dt = datetime.strptime(horario, '%H:%M').time()
                    else:
                        horario_dt = horario
                    
                    antes = condicoes['horario_corte'].get('antes')
                    depois = condicoes['horario_corte'].get('depois')
                    
                    if antes:
                        antes_dt = datetime.strptime(antes, '%H:%M').time()
                        if horario_dt > antes_dt:
                            return False
                    
                    if depois:
                        depois_dt = datetime.strptime(depois, '%H:%M').time()
                        if horario_dt < depois_dt:
                            return False
                except:
                    pass

        return True

    def _sort_demandas(self, demandas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Ordena demandas por prioridade."""
        def sort_key(d):
            # Critérios de ordenação (em ordem de importância)
            mover_topo = 1 if d.get('mover_topo') else 0
            prioridade_calculada = d.get('prioridade_calculada') or d.get('prioridade_manual', 0) or 0
            priority_score = d.get('priority_score', 0)
            is_flex = 1 if d.get('is_flex') else 0
            
            # Parse horário de coleta para ordenação
            horario_coleta = d.get('horario_coleta', '23:59')
            if isinstance(horario_coleta, str):
                try:
                    horario_val = int(horario_coleta.split(':')[0]) * 60 + int(horario_coleta.split(':')[1])
                except:
                    horario_val = 23 * 60 + 59
            else:
                horario_val = 23 * 60 + 59

            # Parse data de entrega
            data_entrega = d.get('data_entrega', '9999-12-31')
            if not data_entrega:
                data_entrega = '9999-12-31'

            # Ordenar:
            # 1. mover_topo (desc)
            # 2. prioridade_calculada (desc)
            # 3. priority_score (desc)
            # 4. is_flex (desc)
            # 5. horario_coleta (asc)
            # 6. data_entrega (asc)
            return (
                -mover_topo,
                -prioridade_calculada,
                -priority_score,
                -is_flex,
                horario_val,
                data_entrega
            )

        return sorted(demandas, key=sort_key)

    def _calculate_default_priority(self, demandas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Calcula prioridade padrão quando não há regras."""
        result = []
        for demanda in demandas:
            demanda_copy = dict(demanda)
            demanda_copy['priority_score'] = self._calculate_base_score(demanda)
            demanda_copy['priority_fatores'] = self.get_priority_factors(demanda)
            demanda_copy['regras_aplicadas'] = False
            result.append(demanda_copy)

        return self._sort_demandas(result)

    def _categorizar_temporal(self, data_entrega_str: Optional[str]) -> str:
        """Categoriza data temporalmente."""
        if not data_entrega_str:
            return 'FUTURO'

        try:
            data_entrega = datetime.fromisoformat(data_entrega_str.replace('Z', '+00:00')).date()
        except:
            return 'FUTURO'

        hoje = date.today()
        amanha = hoje + timedelta(days=1)

        if data_entrega < hoje:
            return 'URGENTE'  # Atrasado
        elif data_entrega == hoje:
            return 'HOJE'
        elif data_entrega == amanha:
            return 'AMANHA'
        else:
            return 'FUTURO'

    def _is_horario_corte_proximo(self, horario_coleta: str) -> bool:
        """Verifica se horário de corte está nas próximas 2 horas."""
        try:
            if isinstance(horario_coleta, str):
                horario = datetime.strptime(horario_coleta, '%H:%M').time()
            else:
                horario = horario_coleta

            agora = datetime.now().time()
            duas_horas = (datetime.now() + timedelta(hours=2)).time()

            return agora <= horario <= duas_horas
        except:
            return False


# Instância singleton
priorizacao_service = PriorizacaoService()
