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


class DemandaAlocacaoWaterfallService:
    def __init__(self):
        self.demandas_table = supabase_db.table('demandas_producao')
        self.itens_table = supabase_db.table('itens_demanda')

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

    def processar_insumos_por_bom_recursivo(self, produto_id: int, quantidade: float, correlation_id: str, user_id: str, tipo_operacao: str = 'CONSUMO_BOM', retroactive_date: Optional[str] = None, item_id_referencia: str = None, qtd_a_produzir_forcada: float = None):
        """
        Motor de Produção Waterfall:
        1. Verifica estoque disponível (apenas se CONSUMO_BOM).
        2. Se houver estoque, consome (SAÍDA).
        3. Se faltar e houver BOM, produz o restante recursivamente (ENTRADA + SAÍDA).
        4. Se for PRODUCAO_AVULSA, produz sem consumir o item final (fica no estoque).
        5. VERIFICA alocações manuais existentes para evitar duplicação (apenas se item_id_referencia fornecido).

        Parâmetro qtd_a_produzir_forcada:
        - Usado quando o caller já calculou o delta e quer forçar a quantidade a produzir
        - Ignora cálculo de estoque para este produto, vai direto para explosão BOM
        """
        print(f"DEBUG [WATERFALL] Processando Produto {produto_id}, Qtd: {quantidade}, Operacao: {tipo_operacao}, Correlation: {correlation_id}, ItemRef: {item_id_referencia}, QtdProduzirForcada: {qtd_a_produzir_forcada}")
        from nistiprint_shared.services.bom_service import bom_service
        from nistiprint_shared.services.app_config_service import app_config_service

        default_deposito_id = app_config_service.get_config('default_production_deposit_id')

        # --- VERIFICAÇÃO DE ALOCAÇÕES MANUAIS (DELTA) ---
        # Se temos um item_id_referencia, verificamos o que já foi alocado manualmente
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

                # Se tudo já foi alocado, não precisa processar nada
                if quantidade <= 0:
                    print(f"DEBUG [WATERFALL] Produto {produto_id} já foi totalmente alocado manualmente. Pulando processamento.")
                    return
            else:
                print(f"DEBUG [WATERFALL] Sem alocações manuais para {produto_id}. Processando {quantidade} unidades normalemente.")

        # --- LÓGICA DE DECISÃO DE ESTOQUE ---
        qtd_estoque = 0.0

        if tipo_operacao == 'CONSUMO_BOM':
            # Se qtd_a_produzir_forcada foi fornecido, usamos esse valor diretamente
            # Isso indica que o caller já calculou o delta e quer produzir apenas essa quantidade
            if qtd_a_produzir_forcada is not None:
                qtd_a_produzir = qtd_a_produzir_forcada
                print(f"DEBUG [WATERFALL] Usando qtd_a_produzir_forcada={qtd_a_produzir_forcada}")
            else:
                # 1. Verificar estoque disponível atual do produto para ver se podemos pular a produção JIT
                saldo_info = estoque_service.get_saldo_atual(produto_id, default_deposito_id)
                disponivel = float(saldo_info.get('quantidade_disponivel', 0) or 0)

                # O que vamos tirar do estoque pronto?
                qtd_estoque = min(max(0.0, disponivel), quantidade)
                # O que precisamos "produzir" via BOM?
                qtd_a_produzir = quantidade - qtd_estoque

                print(f"DEBUG [WATERFALL] Produto {produto_id}: Disponivel={disponivel}, UsarEstoque={qtd_estoque}, Produzir={qtd_a_produzir}")

            # 2. Consumir o que já existe em estoque (SAÍDA SIMPLES)
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

                # Registrar alocação se temos item_id_referencia
                if item_id_referencia:
                    self._registrar_alocacao_estoque(
                        demanda_id='UNKNOWN',  # Será atualizado se necessário
                        item_id=item_id_referencia,
                        produto_id=str(produto_id),
                        correlation_id=correlation_id,
                        quantidade=qtd_estoque,
                        tipo_alocacao='FINALIZACAO',
                        processo_origem='WORKER_FINALIZACAO',
                        metadata={'qtd_estoque': qtd_estoque, 'qtd_a_produzir': qtd_a_produzir, 'quantidade_original': quantidade_original}
                    )
        elif tipo_operacao == 'PRODUCAO_AVULSA':
            # Produção avulsa sempre gera novas unidades explodindo BOM
            qtd_estoque = 0.0
            qtd_a_produzir = quantidade
            print(f"DEBUG [WATERFALL] Produção Avulsa para {produto_id}: Produzindo {quantidade}...")

        # 3. Processar o restante que precisa ser "produzido" ou consumido sem estoque
        if qtd_a_produzir <= 0:
            print(f"DEBUG [WATERFALL] Produto {produto_id}: qtd_a_produzir={qtd_a_produzir}. Pulando explosão BOM.")
            return

        # Verificar se tem BOM para produzir
        componentes = bom_service.get_bom_for_produto(produto_id)

        if componentes and tipo_operacao in ['CONSUMO_BOM', 'PRODUCAO_AVULSA']:
            print(f"DEBUG [WATERFALL] Produto {produto_id} tem BOM. Explodindo para {qtd_a_produzir} unidades...")
            # --- PRODUZIR ---
            # 3.1. Explodir BOM recursivamente para os filhos (Sempre CONSUMO_BOM para os filhos)
            # IMPORTANTE: Não passar item_id_referencia para os filhos, pois eles são componentes da BOM
            # e devem ser consumidos integralmente para produzir qtd_a_produzir
            for comp in componentes:
                qtd_comp_necessaria = float(comp.quantidade) * qtd_a_produzir
                print(f"DEBUG [WATERFALL] Componente {comp.componente_id}: {comp.quantidade} x {qtd_a_produzir} = {qtd_comp_necessaria}")
                self.processar_insumos_por_bom_recursivo(
                    produto_id=int(comp.componente_id),
                    quantidade=qtd_comp_necessaria,
                    correlation_id=correlation_id,
                    user_id=user_id,
                    tipo_operacao='CONSUMO_BOM', # Filhos sempre são consumidos
                    retroactive_date=retroactive_date,
                    item_id_referencia=None  # NÃO passar item_id_referencia para componentes
                )

            # 3.2. Registrar ENTRADA do produto atual (foi produzido agora consumindo os filhos)
            estoque_service.registrar_entrada(
                produto_id=produto_id,
                deposito_id=default_deposito_id,
                quantidade=qtd_a_produzir,
                observacao=f"[WATERFALL_PROD] Entrada de item produzido para Correlation: {correlation_id}",
                usuario_id=None,
                correlation_id=correlation_id,
                origem_tipo=8, # 8: ENTRADA_POR_PRODUCAO_BOM
                data_movimento=retroactive_date
            )

            # 3.3. Registrar SAÍDA do produto atual APENAS se for CONSUMO_BOM
            # Se for PRODUCAO_AVULSA, o item FICA no estoque pronto.
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
            # --- NÃO TEM BOM OU É ESTORNO ---
            if tipo_operacao in ['CONSUMO_BOM', 'ESTORNO_AVULSO_CONSUMO']: # Estorno de consumo seria saída? Não, entrada.
                # Consome direto (fica negativo se não houver estoque)
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
                # Lógica de Estorno (apenas devolve ao estoque)
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


demanda_alocacao_waterfall_service = DemandaAlocacaoWaterfallService()
