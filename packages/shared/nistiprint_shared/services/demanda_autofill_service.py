"""
Demanda AutoFill Service - Serviço para autopreenchimento inteligente de formulários.

Este serviço minimiza a carga cognitiva do usuário ao aproveitar dados cadastrados
para preencher automaticamente formulários de criação/edição de demandas.

Objetivos:
- Autopreencher campos baseados em seleções do usuário (canal, modalidade, etc.)
- Calcular valores sugeridos (data limite, setores envolvidos)
- Validar conflitos antes da submissão
- Lembrar preferências do usuário
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, date, time, timedelta
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.utils.date_utils import get_now, get_now_iso
import logging

logger = logging.getLogger("DemandaAutoFillService")


class DemandaAutoFillService:
    """Serviço para autopreenchimento inteligente de formulários de demanda."""

    def __init__(self):
        self.canais_venda_table = supabase_db.table('canais_venda')
        self.regras_logisticas_table = supabase_db.table('regras_logisticas_canal')
        self.pontos_coleta_table = supabase_db.table('pontos_coleta')
        self.templates_obs_table = supabase_db.table('templates_obs_canal')
        self.produtos_table = supabase_db.table('produtos')
        self.bom_table = supabase_db.table('produto_lista_materiais')
        self.setores_table = supabase_db.table('setores')
        self.preferencias_table = supabase_db.table('preferencias_ux_usuario')

    # ========================================================================
    # MÉTODOS PÚBLICOS - Autopreenchimento
    # ========================================================================

    def get_defaults_for_canal(self, canal_venda_id: int) -> Dict[str, Any]:
        """
        Busca padrões para um canal de venda.

        Args:
            canal_venda_id: ID do canal de venda

        Returns:
            Dicionário com valores padrão:
            - horario_coleta
            - modalidade_logistica
            - ponto_coleta_id, ponto_coleta_nome
            - tipo_demanda
            - observacoes_template
        """
        try:
            # 1. Buscar canal
            canal = self._get_canal_venda(canal_venda_id)
            if not canal:
                return {}

            # 2. Buscar regras logísticas do canal
            regras = self._get_regras_logisticas_canal(canal_venda_id)

            # 3. Extrair padrão da primeira regra (mais prioritária)
            defaults = {
                'canal_venda_id': canal_venda_id,
                'canal_venda_nome': canal.get('nome'),
                'plataforma_nome': canal.get('plataforma_nome'),
            }

            if regras:
                regra_principal = regras[0]  # Já vem ordenada por prioridade
                defaults.update({
                    'horario_coleta': self._format_horario(regra_principal.get('horario_limite')),
                    'modalidade_logistica': regra_principal.get('modalidade', 'STANDARD'),
                    'tipo_envio': regra_principal.get('tipo_envio', 'COLETA_LOCAL'),
                    'ponto_coleta_id': regra_principal.get('ponto_coleta_id'),
                    'ponto_coleta_nome': regra_principal.get('ponto_coleta_nome'),
                })

                # Buscar detalhes do ponto de coleta se existir
                if regra_principal.get('ponto_coleta_id'):
                    ponto = self._get_ponto_coleta(regra_principal.get('ponto_coleta_id'))
                    if ponto:
                        defaults['horario_corte_ponto'] = self._format_horario(ponto.get('horario_corte_padrao'))

            # 4. Inferir tipo de demanda baseado na plataforma
            defaults['tipo_demanda'] = self._infer_tipo_demanda(canal.get('plataforma_nome'))

            # 5. Buscar template de observações
            template = self._get_template_obs_padrao(canal_venda_id)
            if template:
                defaults['observacoes_template'] = template.get('template')

            return defaults

        except Exception as e:
            logger.error(f"Erro ao buscar padrões para canal {canal_venda_id}: {e}", exc_info=True)
            return {}

    def get_defaults_for_modalidade(
        self,
        canal_venda_id: int,
        modalidade: str
    ) -> Dict[str, Any]:
        """
        Busca padrões para uma modalidade específica de um canal.

        Args:
            canal_venda_id: ID do canal de venda
            modalidade: Modalidade logística (STANDARD, EXPRESS, FULFILLMENT, RETIRADA)

        Returns:
            Dicionário com valores padrão para a modalidade
        """
        try:
            # Buscar regra específica da modalidade
            regra = self._get_regra_por_modalidade(canal_venda_id, modalidade)

            if not regra:
                return {}

            defaults = {
                'modalidade_logistica': modalidade,
                'horario_coleta': self._format_horario(regra.get('horario_limite')),
                'tipo_envio': regra.get('tipo_envio', 'COLETA_LOCAL'),
            }

            # Buscar ponto de coleta se aplicável
            if regra.get('ponto_coleta_id'):
                ponto = self._get_ponto_coleta(regra.get('ponto_coleta_id'))
                if ponto:
                    defaults['ponto_coleta_id'] = ponto.get('id')
                    defaults['ponto_coleta_nome'] = ponto.get('nome')
                    defaults['horario_corte_ponto'] = self._format_horario(ponto.get('horario_corte_padrao'))

            # Inferir flags
            defaults['is_flex'] = modalidade == 'EXPRESS'
            defaults['fulfillment'] = modalidade == 'FULFILLMENT'

            return defaults

        except Exception as e:
            logger.error(f"Erro ao buscar padrões para modalidade {modalidade}: {e}", exc_info=True)
            return {}

    def get_suggested_deadline(
        self,
        produtos: List[Dict[str, Any]],
        data_entrega_str: str,
        horario_coleta_str: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calcula data limite de execução baseada no tempo de produção.

        Args:
            produtos: Lista de produtos da demanda
            data_entrega_str: Data de entrega (YYYY-MM-DD)
            horario_coleta_str: Horário de coleta (HH:MM)

        Returns:
            Dicionário com:
            - data_limite_execucao: Data sugerida para início da execução
            - tempo_producao_dias: Tempo estimado de produção
            - margem_seguranca: Margem de segurança aplicada
        """
        try:
            # 1. Calcular tempo de produção baseado nos produtos
            tempo_producao = self._calcular_tempo_producao(produtos)

            # 2. Parse da data de entrega
            data_entrega = self._parse_date(data_entrega_str)
            if not data_entrega:
                data_entrega = date.today() + timedelta(days=7)

            # 3. Calcular data limite (data entrega - tempo produção)
            data_limite = data_entrega - timedelta(days=tempo_producao)

            # 4. Ajustar se horário de coleta for manhã
            if horario_coleta_str:
                try:
                    hora = int(horario_coleta_str.split(':')[0])
                    if hora < 12:  # Coleta pela manhã
                        data_limite = data_limite - timedelta(days=1)
                except:
                    pass

            # 5. Garantir que data limite não é no passado
            hoje = date.today()
            if data_limite < hoje:
                data_limite = hoje

            return {
                'data_limite_execucao': data_limite.isoformat(),
                'tempo_producao_dias': tempo_producao,
                'margem_seguranca': 1,  # Dia de margem
                'data_entrega': data_entrega_str,
                'horario_coleta': horario_coleta_str
            }

        except Exception as e:
            logger.error(f"Erro ao calcular data limite: {e}", exc_info=True)
            return {
                'data_limite_execucao': data_entrega_str,
                'tempo_producao_dias': 1,
                'margem_seguranca': 0
            }

    def get_setores_envolvidos(self, produtos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Inferir setores envolvidos a partir da BOM dos produtos.

        Args:
            produtos: Lista de produtos da demanda

        Returns:
            Lista de setores com informações:
            - setor_id
            - setor_nome
            - tempo_estimado
        """
        try:
            setores_map = {}

            for produto in produtos:
                produto_id = produto.get('id') or produto.get('produto_id')
                if not produto_id:
                    continue

                # Buscar BOM do produto
                bom_itens = self._get_bom_itens(produto_id)

                for bom_item in bom_itens:
                    setor = bom_item.get('setor')
                    if not setor:
                        continue

                    setor_id = setor.get('id') or setor.get('setor_id')
                    if not setor_id:
                        continue

                    # Agrupar por setor
                    if setor_id not in setores_map:
                        setores_map[setor_id] = {
                            'setor_id': setor_id,
                            'setor_nome': setor.get('nome', 'Desconhecido'),
                            'tempo_estimado': 0,
                            'produtos': []
                        }

                    # Somar tempo estimado
                    tempo = bom_item.get('tempo_estimado') or bom_item.get('tempo_preparacao') or 0
                    setores_map[setor_id]['tempo_estimado'] += tempo
                    setores_map[setor_id]['produtos'].append(produto.get('nome', produto.get('descricao')))

            return list(setores_map.values())

        except Exception as e:
            logger.error(f"Erro ao inferir setores: {e}", exc_info=True)
            return []

    def validate_horario_coleta(
        self,
        horario_coleta_str: str,
        ponto_coleta_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Valida se horário de coleta é compatível com ponto de coleta.

        Args:
            horario_coleta_str: Horário de coleta (HH:MM)
            ponto_coleta_id: ID do ponto de coleta

        Returns:
            Dicionário de validação:
            - valido: bool
            - erros: lista de strings
            - avisos: lista de strings
        """
        resultado = {
            'valido': True,
            'erros': [],
            'avisos': []
        }

        try:
            # Parse do horário
            if not horario_coleta_str:
                resultado['erros'].append('Horário de coleta não informado')
                resultado['valido'] = False
                return resultado

            horario = self._parse_time(horario_coleta_str)
            if not horario:
                resultado['erros'].append('Formato de horário inválido. Use HH:MM')
                resultado['valido'] = False
                return resultado

            # Se tem ponto de coleta, validar contra horário de corte
            if ponto_coleta_id:
                ponto = self._get_ponto_coleta(ponto_coleta_id)
                if ponto:
                    horario_corte = self._parse_time(ponto.get('horario_corte_padrao'))
                    
                    if horario_corte and horario > horario_corte:
                        resultado['erros'].append(
                            f'Horário de coleta ({horario_coleta_str}) é posterior ao '
                            f'horário de corte do ponto ({ponto.get("horario_corte_padrao")})'
                        )
                        resultado['valido'] = False

            # Validar se horário não é muito cedo (antes das 8h)
            if horario.hour < 8:
                resultado['avisos'].append('Horário de coleta muito cedo (antes das 8:00)')

            # Validar se horário não é muito tarde (depois das 18h)
            if horario.hour >= 18:
                resultado['avisos'].append('Horário de coleta tarde (após 18:00)')

        except Exception as e:
            logger.error(f"Erro ao validar horário: {e}", exc_info=True)
            resultado['erros'].append(f'Erro na validação: {str(e)}')
            resultado['valido'] = False

        return resultado

    def validate_data_entrega(
        self,
        data_entrega_str: str,
        produtos: List[Dict[str, Any]],
        horario_coleta_str: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Valida se data de entrega é viável com tempo de produção.

        Args:
            data_entrega_str: Data de entrega (YYYY-MM-DD)
            produtos: Lista de produtos
            horario_coleta_str: Horário de coleta

        Returns:
            Dicionário de validação
        """
        resultado = {
            'valido': True,
            'erros': [],
            'avisos': []
        }

        try:
            data_entrega = self._parse_date(data_entrega_str)
            if not data_entrega:
                resultado['erros'].append('Data de entrega inválida')
                resultado['valido'] = False
                return resultado

            hoje = date.today()

            # Verificar se data não é no passado
            if data_entrega < hoje:
                resultado['erros'].append('Data de entrega não pode ser no passado')
                resultado['valido'] = False
                return resultado

            # Calcular tempo de produção necessário
            tempo_producao = self._calcular_tempo_producao(produtos)
            data_minima = hoje + timedelta(days=tempo_producao)

            # Ajustar para horário de coleta
            if horario_coleta_str:
                try:
                    hora = int(horario_coleta_str.split(':')[0])
                    if hora < 12:
                        data_minima = data_minima + timedelta(days=1)
                except:
                    pass

            # Verificar se data é viável
            if data_entrega < data_minima:
                resultado['erros'].append(
                    f'Data de entrega muito próxima. Mínimo necessário: {data_minima.isoformat()} '
                    f'({tempo_producao} dias de produção)'
                )
                resultado['valido'] = False
                return resultado

            # Aviso se data está muito próxima
            dias_restantes = (data_entrega - hoje).days
            if dias_restantes <= tempo_producao + 1:
                resultado['avisos'].append(
                    f'Data de entrega próxima ({dias_restantes} dias). Producao requer {tempo_producao} dias.'
                )

        except Exception as e:
            logger.error(f"Erro ao validar data: {e}", exc_info=True)
            resultado['erros'].append(f'Erro na validação: {str(e)}')
            resultado['valido'] = False

        return resultado

    def get_last_used_config(self, user_id: str) -> Dict[str, Any]:
        """
        Retorna última configuração usada pelo usuário.

        Args:
            user_id: ID do usuário

        Returns:
            Última configuração usada
        """
        try:
            response = self.preferencias_table.select("ultima_config_demanda") \
                .eq('user_id', user_id) \
                .single() \
                .execute()

            if response.data:
                return response.data.get('ultima_config_demanda', {})
            return {}

        except:
            return {}

    def save_last_used_config(self, user_id: str, config: Dict[str, Any]) -> bool:
        """
        Salva última configuração usada pelo usuário.

        Args:
            user_id: ID do usuário
            config: Configuração usada

        Returns:
            True se salvo, False se erro
        """
        try:
            # Verificar se já existe
            existing = self.preferencias_table.select("id") \
                .eq('user_id', user_id) \
                .execute()

            if existing.data:
                # Atualizar
                self.preferencias_table.update({
                    'ultima_config_demanda': config,
                    'updated_at': get_now_iso()
                }).eq('user_id', user_id).execute()
            else:
                # Criar
                self.preferencias_table.insert({
                    'user_id': user_id,
                    'ultima_config_demanda': config,
                    'created_at': get_now_iso(),
                    'updated_at': get_now_iso()
                }).execute()

            return True

        except Exception as e:
            logger.error(f"Erro ao salvar configuração: {e}", exc_info=True)
            return False

    def get_template_obs(self, canal_venda_id: int, variaveis: Dict[str, str] = None) -> Optional[str]:
        """
        Busca template de observações para um canal e aplica variáveis.

        Args:
            canal_venda_id: ID do canal
            variaveis: Dicionário de variáveis para substituição

        Returns:
            Template processado ou None
        """
        try:
            template = self._get_template_obs_padrao(canal_venda_id)
            if not template:
                return None

            template_str = template.get('template', '')

            # Substituir variáveis
            if variaveis:
                for chave, valor in variaveis.items():
                    template_str = template_str.replace(f'{{{{{chave}}}}}', str(valor))

            return template_str

        except Exception as e:
            logger.error(f"Erro ao buscar template: {e}", exc_info=True)
            return None

    def get_all_templates_for_canal(self, canal_venda_id: int) -> List[Dict[str, Any]]:
        """
        Busca todos os templates de um canal.

        Args:
            canal_venda_id: ID do canal

        Returns:
            Lista de templates
        """
        try:
            response = self.templates_obs_table.select("*") \
                .eq('canal_venda_id', canal_venda_id) \
                .order('is_default', desc=True) \
                .order('nome') \
                .execute()

            return response.data or []

        except Exception as e:
            logger.error(f"Erro ao buscar templates: {e}", exc_info=True)
            return []

    # ========================================================================
    # MÉTODOS PRIVADOS - Helpers
    # ========================================================================

    def _get_canal_venda(self, canal_venda_id: int) -> Optional[Dict[str, Any]]:
        """Busca canal de venda."""
        try:
            response = self.canais_venda_table.select("*") \
                .eq('id', canal_venda_id) \
                .single() \
                .execute()
            return response.data
        except:
            return None

    def _get_regras_logisticas_canal(self, canal_venda_id: int) -> List[Dict[str, Any]]:
        """Busca regras logísticas do canal."""
        try:
            response = self.regras_logisticas_table.select("*, pontos_coleta(nome)") \
                .eq('canal_venda_id', canal_venda_id) \
                .order('prioridade_uso', desc=True) \
                .execute()
            return response.data or []
        except:
            return []

    def _get_regra_por_modalidade(
        self,
        canal_venda_id: int,
        modalidade: str
    ) -> Optional[Dict[str, Any]]:
        """Busca regra por modalidade."""
        regras = self._get_regras_logisticas_canal(canal_venda_id)
        for regra in regras:
            if regra.get('modalidade') == modalidade:
                return regra
        return None

    def _get_ponto_coleta(self, ponto_coleta_id: int) -> Optional[Dict[str, Any]]:
        """Busca ponto de coleta."""
        try:
            response = self.pontos_coleta_table.select("*") \
                .eq('id', ponto_coleta_id) \
                .single() \
                .execute()
            return response.data
        except:
            return None

    def _get_template_obs_padrao(self, canal_venda_id: int) -> Optional[Dict[str, Any]]:
        """Busca template padrão de observações."""
        try:
            response = self.templates_obs_table.select("*") \
                .eq('canal_venda_id', canal_venda_id) \
                .eq('is_default', True) \
                .single() \
                .execute()
            return response.data
        except:
            return None

    def _get_bom_itens(self, produto_id: int) -> List[Dict[str, Any]]:
        """Busca itens da BOM de um produto."""
        try:
            response = self.bom_table.select("*, setor(nome, id)") \
                .eq('produto_id', produto_id) \
                .execute()
            return response.data or []
        except:
            return []

    def _calcular_tempo_producao(self, produtos: List[Dict[str, Any]]) -> int:
        """Calcula tempo de produção em dias baseado nos produtos."""
        if not produtos:
            return 1  # Default 1 dia

        tempo_max = 0
        for produto in produtos:
            # Tentar obter tempo do produto
            tempo = produto.get('tempo_producao') or produto.get('lead_time') or 1
            tempo_max = max(tempo_max, tempo)

        return tempo_max

    def _infer_tipo_demanda(self, plataforma_nome: Optional[str]) -> str:
        """Inferir tipo de demanda baseado na plataforma."""
        if not plataforma_nome:
            return 'PLATAFORMA'

        nome_lower = plataforma_nome.lower()
        
        # Marketplaces são PLATAFORMA
        if any(m in nome_lower for m in ['shopee', 'amazon', 'mercadolivre', 'shein', 'tiktok']):
            return 'PLATAFORMA'
        
        # Bling pode ser B2B ou PLATAFORMA
        if 'bling' in nome_lower:
            return 'PLATAFORMA'

        return 'PLATAFORMA'

    def _parse_date(self, date_str: str) -> Optional[date]:
        """Parse de string para date."""
        try:
            return datetime.fromisoformat(date_str).date()
        except:
            return None

    def _parse_time(self, time_str: str) -> Optional[time]:
        """Parse de string para time."""
        try:
            return datetime.strptime(time_str, '%H:%M').time()
        except:
            return None

    def _format_horario(self, horario: Any) -> Optional[str]:
        """Formata horário para string HH:MM."""
        if not horario:
            return None
        
        if isinstance(horario, str):
            return horario
        
        if isinstance(horario, time):
            return horario.strftime('%H:%M')
        
        return str(horario)


# Instância singleton
demanda_autofill_service = DemandaAutoFillService()
