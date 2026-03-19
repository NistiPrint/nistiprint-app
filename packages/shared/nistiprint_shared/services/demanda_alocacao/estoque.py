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


class DemandaAlocacaoEstoqueService:
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
        Usado para controle de idempotência e cálculo de delta na finalização.

        NOTA: demanda_id, item_id, produto_id podem ser UUIDs ou IDs numéricos (int).
        A tabela foi criada com UUID, mas Postgres faz cast automático de int para UUID
        se o formato for válido. Para IDs numéricos, armazenamos como string mesmo.
        """
        import uuid as uuid_lib

        print(f"DEBUG [_registrar_alocacao_estoque] INICIO: item={item_id}, produto={produto_id}, qtd={quantidade}, tipo={tipo_alocacao}")
        try:
            # Verificar se já existe (idempotência)
            existing = supabase_db.table('demanda_alocacoes_estoque')\
                .select('id', 'status')\
                .eq('correlation_id', correlation_id)\
                .neq('status', 'CANCELADA')\
                .execute()

            if existing.data:
                print(f"DEBUG [_registrar_alocacao_estoque] Alocação {correlation_id} já existe, ignorando registro duplicado")
                return existing.data[0]

            # Manter IDs originais como string (funciona com UUID ou int)
            # O Postgres faz cast quando necessário
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

    def _marcar_alocacao_processada(self, correlation_id: str):
        """Marca alocação como processada após consumo de estoque realizado."""
        try:
            supabase_db.table('demanda_alocacoes_estoque')\
                .update({'status': 'PROCESSADA', 'processed_at': get_now_iso()})\
                .eq('correlation_id', correlation_id)\
                .execute()
        except Exception as e:
            print(f"ERRO ao marcar alocação {correlation_id} como processada: {e}")

    def _marcar_alocacao_cancelada(self, correlation_id: str, motivo: str = None):
        """Cancela alocação (ex: em caso de estorno)."""
        try:
            metadata_update = {'motivo_cancelamento': motivo} if motivo else {}
            # Buscar metadata atual
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

    def _buscar_alocacoes_por_item(self, item_id: str, produto_id: str = None) -> List[Dict[str, Any]]:
        """Busca todas as alocações ativas (não canceladas) para um item."""
        try:
            # Buscar todas alocações não canceladas e filtrar manualmente
            # Isso evita problemas de comparação entre string e UUID
            result = supabase_db.table('demanda_alocacoes_estoque')\
                .select('*')\
                .neq('status', 'CANCELADA')\
                .execute()

            if not result.data:
                return []

            # Filtrar manualmente por item_id e produto_id (comparação flexível)
            alocacoes_filtradas = []
            for aloc in result.data:
                # Comparar como string para funcionar com UUID ou int
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
            # Buscar alocações manualmente (sem RPC)
            alocacoes = self._buscar_alocacoes_por_item(item_id, produto_id)
            total = sum(float(a.get('quantidade_alocada', 0)) for a in alocacoes)
            print(f"DEBUG [_calcular_total_alocado] item={item_id}, prod={produto_id}, total={total} ({len(alocacoes)} alocações)")
            for aloc in alocacoes[:5]:
                print(f"  - {aloc.get('quantidade_alocada')} ({aloc.get('tipo_alocacao')}, status={aloc.get('status')})")
            return total
        except Exception as e:
            print(f"ERRO ao calcular total alocado: {e}")
            return 0.0

    def _calcular_saldo_a_processar(self, item_id: str, produto_id: str, quantidade_necessaria: float) -> float:
        """
        Calcula quanto ainda precisa ser processado (diferença entre necessário e já alocado).
        Retorna 0 se tudo já foi alocado.

        NOTA: item_id e produto_id podem ser UUIDs ou IDs numéricos.
        """
        try:
            # Usar busca direta com IDs originais (string)
            # Evita RPC que espera UUIDs
            print(f"DEBUG [_calcular_saldo_a_processar] item={item_id}, produto={produto_id}, necessario={quantidade_necessaria}")
            total_alocado = self._calcular_total_alocado(item_id, produto_id)
            saldo = float(quantidade_necessaria) - total_alocado
            print(f"DEBUG [_calcular_saldo_a_processar] alocado={total_alocado}, saldo={saldo}")
            return max(saldo, 0.0)
        except Exception as e:
            print(f"ERRO [_calcular_saldo_a_processar]: {e}")
            import traceback
            traceback.print_exc()
            # Em caso de erro, retorna quantidade completa para não bloquear processamento
            return float(quantidade_necessaria)

    def _verificar_alocacao_existente(self, correlation_id: str) -> bool:
        """Verifica se alocação com correlation_id já existe (para idempotência)."""
        try:
            result = supabase_db.rpc('verificar_alocacao_existente', {
                'p_correlation_id': str(correlation_id)  # TEXT é compatível com string
            }).execute()

            if result.data is not None:
                return bool(result.data)

            # Fallback
            existing = supabase_db.table('demanda_alocacoes_estoque')\
                .select('id')\
                .eq('correlation_id', correlation_id)\
                .neq('status', 'CANCELADA')\
                .limit(1)\
                .execute()
            return len(existing.data) > 0
        except Exception as e:
            print(f"ERRO ao verificar alocação {correlation_id}: {e}")
            return False

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

        # Garante que item_id seja inteiro para a consulta .eq()
        try:
            clean_id = int(item_id)
        except (ValueError, TypeError):
            raise ValueError(f"ID de item deve ser numérico: {item_id}")

        response = supabase_db.execute_with_retry(self.itens_table.select("*").eq('id', clean_id))
        if not response.data:
            raise ValueError(f"Item {clean_id} não encontrado")
        return response.data[0]

    def processar_alocacao_de_demanda(self, item_id: str, campo: str, incremento: float, user_id: str, skip_visual_update: bool = False, origem_tipo: Optional[int] = None, retroactive_date: Optional[str] = None, correlation_id: Optional[str] = None):
        """
        Processa a alocação de estoque com base no estágio de produção.
        Implementa o cenário misto: uso de estoque existente + produção JIT.
        Suporta data retroativa e Correlation ID para rastreabilidade.
        """
        from nistiprint_shared.config.production_stages import ESTAGIOS_PRODUCAO
        from nistiprint_shared.services.unit_of_work import UnitOfWork
        from nistiprint_shared.services.bom_service import bom_service
        from nistiprint_shared.services.app_config_service import app_config_service

        # --- GESTÃO DE CORRELAÇÃO E DATA ---
        cid = correlation_id or f"DASH-{uuid.uuid4().hex[:8]}"
        mov_date = retroactive_date or get_now_iso()
        # -----------------------------------

        # Validação básica de entrada para evitar erros de SQL
        if not item_id or item_id == 'None':
            raise ValueError(f"ID do item inválido para processamento de estoque: {item_id}")

        # ETAPA 1: VALIDAÇÃO E IDENTIFICAÇÃO
        if campo not in ESTAGIOS_PRODUCAO:
            # Se o campo (ex: 'expedicao_capas_retiradas_qtd') não é um estágio de produção,
            # ele apenas registra o avanço visualmente, sem movimentar estoque de componentes.
            progresso_result = None
            if not skip_visual_update:
                progresso_result = self._atualizar_progresso_simples(item_id, campo, incremento)

            # Registro de log diário para progresso visual (Expedição, etc)
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

        # Usando a BOM do produto final, encontra o ID do produto intermediário deste estágio
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

        # ETAPA 2: MOVIMENTAÇÃO DE ESTOQUE (HÍBRIDO: ESTOQUE + JIT)
        deposito_id = app_config_service.get_config('default_production_deposit_id')

        # 2.1. Verificar saldo disponível
        saldo_info = estoque_service.get_saldo_atual(produto_intermediario['id'], deposito_id)
        saldo_disponivel = float(saldo_info.get('quantidade_disponivel', 0))

        # 2.2. Decidir origem (se não fornecido)
        if not origem_tipo:
            origem_tipo = 1 if incremento > 0 else 2  # 1: INCREMENTAL, 2: ESTORNO

        # 2.3. Calcular quanto virá do estoque vs. produção
        qtd_do_estoque = 0.0
        qtd_a_produzir = 0.0

        if incremento > 0:
            qtd_do_estoque = min(incremento, max(0.0, saldo_disponivel))
            qtd_a_produzir = incremento - qtd_do_estoque
        else:
            # Estorno: apenas devolve ao estoque
            qtd_do_estoque = incremento  # Negativo

        # 2.4. Executar movimentações
        try:
            # A) Consumo/Estorno de Estoque
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

            # B) Produção JIT (se necessário)
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

            # C) Registrar alocação manual para controle de delta na finalização
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

        # ETAPA 3: ATUALIZAÇÃO VISUAL
        progresso_result = None
        if not skip_visual_update:
            progresso_result = self._atualizar_progresso_simples(item_id, campo, incremento)

        # ETAPA 4: LOG DE PRODUÇÃO DIÁRIA
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

    def associar_saida_a_demanda(self, demanda_id: str, product_id: str, quantity: float, user_id: str = 'System'):
        """
        Associa uma saída de estoque manual a uma demanda específica,
        identificando o item correspondente e atualizando seu progresso.
        """
        try:
            # 1. Identificar o item da demanda que usa este produto (como capa ou miolo)
            demanda = self._core.get_demanda_with_itens(demanda_id)
            if not demanda:
                return False

            target_item = None
            campo_atualizar = 'expedicao_capas_retiradas_qtd'  # Default

            for item in demanda.get('itens', []):
                # Se o produto for o produto principal do item (Capa/Acabado)
                if str(item.get('produto_id')) == str(product_id):
                    target_item = item
                    campo_atualizar = 'expedicao_capas_retiradas_qtd'
                    break
                # Se o produto for o miolo do item
                if str(item.get('id_produto_miolo')) == str(product_id):
                    target_item = item
                    campo_atualizar = 'expedicao_miolos_retirados_qtd'
                    break

            if target_item:
                # 2. Atualizar o progresso do item
                self.processar_alocacao_de_demanda(
                    item_id=target_item['id'],
                    campo=campo_atualizar,
                    incremento=float(quantity),
                    user_id=user_id,
                    skip_visual_update=False
                )
                return True
            return False
        except Exception as e:
            print(f"Erro ao associar saída à demanda {demanda_id}: {e}")
            return False

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

    def _executar_movimentacao_estoque_recursiva(self, item_id, produto_id, quantidade, demanda_id,
                                               saldos_produtos, boms_produtos, deve_sair_no_final=True):
        """
        Motor de movimentação de estoque com suporte a produção JIT recursiva.

        deve_sair_no_final:
            True  -> (ENTRADA + SAÍDA) Usado para Dashboard (progresso) e para sub-componentes
                     que estão sendo produzidos para serem consumidos pelo pai imediatamente.
            False -> (APENAS ENTRADA) Usado para Entrada Manual no Controle de Produção,
                     onde o item final deve permanecer no estoque.
        """
        deposito_id = app_config_service.get_config('default_production_deposit_id')
        produto = product_service.get_by_id(produto_id)
        nome_produto = produto.get('name', f"Produto {produto_id}")

        # 1. PRIORIDADE: CONSUMIR DO ESTOQUE EXISTENTE
        saldo_info = saldos_produtos.get(str(produto_id))
        if saldo_info:
            saldo_disponivel = float(saldo_info.get('quantidade_disponivel', 0))
        else:
            res_saldo = estoque_service.get_saldo_atual(produto_id, deposito_id)
            saldo_disponivel = float(res_saldo.get('quantidade_disponivel', 0))

        qtd_do_estoque = min(saldo_disponivel, quantidade)
        qtd_a_produzir = max(0.0, quantidade - qtd_do_estoque)

        # 1.1. Se temos estoque, realizamos a SAÍDA (Consumo)
        if qtd_do_estoque > 0 and deve_sair_no_final:
            estoque_service.registrar_saida(
                produto_id=produto_id,
                deposito_id=deposito_id,
                quantidade=qtd_do_estoque,
                motivo=f"Consumo de estoque para produção" if not demanda_id else f"Alocação item {item_id} demanda {demanda_id}",
                documento_referencia=demanda_id
            )

        # 2. SEGUNDA OPÇÃO: PRODUZIR O RESTANTE (RECURSIVIDADE)
        if qtd_a_produzir > 0:
            componentes = boms_produtos.get(str(produto_id), [])
            if not componentes:
                componentes = bom_service.get_bom_for_produto(int(produto_id))

            if componentes:
                # 2.1. Processar cada componente da BOM recursivamente
                for comp in componentes:
                    comp_id = str(comp.componente_id)
                    qtd_comp_necessaria = float(comp.quantidade) * qtd_a_produzir

                    role_comp = product_service.identify_product_role(comp_id)

                    if role_comp in ['MIOLO', 'CAPA_IMPRESSAO', 'CAPA_ACABADA']:
                        # CHAMADA RECURSIVA: Componente deve ser consumido pelo pai (deve_sair_no_final=True)
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
                        # Saída simples de insumo/materia-prima básica
                        estoque_service.registrar_saida(
                            produto_id=comp_id,
                            deposito_id=deposito_id,
                            quantidade=qtd_comp_necessaria,
                            motivo=f"Consumo insumo para: {nome_produto}",
                            documento_referencia=demanda_id
                        )

                # 2.2. ENTRADA do item que acabamos de produzir (independente da origem)
                estoque_service.registrar_entrada(
                    produto_id=produto_id,
                    deposito_id=deposito_id,
                    quantidade=qtd_a_produzir,
                    observacao=f"Produção JIT automática: {nome_produto}" if demanda_id else f"Entrada de produção: {nome_produto}"
                )

                # 2.3. SAÍDA imediata se for para Alocação de Demanda ou Consumo pelo Pai
                if deve_sair_no_final:
                    estoque_service.registrar_saida(
                        produto_id=produto_id,
                        deposito_id=deposito_id,
                        quantidade=qtd_a_produzir,
                        motivo=f"Consumo JIT produção" if not demanda_id else f"Alocação JIT demanda {demanda_id}",
                        documento_referencia=demanda_id
                    )

        return True

    def processar_alocacao_avulsa_otimizado(self, product_id: str, campo: str, quantidade: float, user_id: str, sincrono: bool = False):
        """
        Processa uma produção avulsa (fora de demanda específica) com lógica recursiva e fail-safe.
        Usado principalmente pela tela de Controle de Produção (estoque geral).
        """
        from nistiprint_shared.config.production_stages import ESTAGIOS_PRODUCAO

        if campo not in ESTAGIOS_PRODUCAO:
            # Caso simples: apenas log diário
            selected_date = datetime.now().date()
            product = product_service.get_by_id(product_id)
            daily_production_log_service.registrar_producao(
                log_date=selected_date,
                product_id=product_id,
                product_name=product.get('name', 'Produto'),
                quantity=quantidade,
                user_email=user_id
            )
            return {'success': True}

        # SE solicitado síncrono (ex: tela de Controle de Produção), executa agora sem fila
        if sincrono:
            try:
                print(f"DEBUG: Executando PRODUCAO_AVULSA síncrona para {product_id} no campo {campo}")
                correlation_id = str(uuid.uuid4())
                success = self.processar_insumos_por_bom_recursivo(
                    produto_id=int(product_id),
                    quantidade=quantidade,
                    correlation_id=correlation_id,
                    user_id=user_id,
                    tipo_operacao='PRODUCAO_AVULSA'
                )

                daily_production_log_service.create_log(
                    log_date=datetime.now().date(),
                    product_id=str(product_id),
                    product_name=product_service.get_by_id(product_id).get('nome', 'Produto'),
                    quantity=quantidade,
                    production_order_id=None,
                    component_stock_snapshot=[],
                    user_email=user_id,
                    metadata={'tipo': 'AVULSA_SINCRONA', 'campo': campo, 'correlation_id': correlation_id}
                )

                return {
                    'success': success,
                    'message': "Produção avulsa processada em tempo real.",
                    'queued': False
                }
            except Exception as e:
                print(f"Erro no processamento síncrono de produção avulsa: {e}")
                return {'success': False, 'error': str(e)}

        # EXECUÇÃO ASSÍNCRONA (BACKEND QUEUE) - Padrão para Dashboard
        try:
            correlation_id = str(uuid.uuid4())

            self.agendar_processamento_estoque(
                demanda_id=None,
                item_id=None,
                campo='PRODUCAO_AVULSA',
                incremento=quantidade,
                user_id=user_id,
                correlation_id=correlation_id,
                produto_id=product_id
            )

            selected_date = datetime.now().date()
            product = product_service.get_by_id(product_id)
            daily_production_log_service.create_log(
                log_date=selected_date,
                product_id=product_id,
                product_name=product.get('name', 'Produto'),
                quantity=quantidade,
                production_order_id=None,
                component_stock_snapshot=[],
                user_email=user_id,
                metadata={'correlation_id': correlation_id, 'tipo': 'AVULSA'}
            )

            return {'success': True, 'correlation_id': correlation_id}
        except Exception as e:
            print(f"ERRO NA PRODUÇÃO AVULSA ASSÍNCRONA: {e}")
            raise e

    def processar_alocacao_de_demanda_otimizado(self, item_id: str, campo: str, incremento: float, user_id: str,
                                               itens_dict: dict, saldos_produtos: dict, boms_produtos: dict,
                                               origem_tipo: Optional[int] = None, retroactive_date: Optional[str] = None, correlation_id: Optional[str] = None):
        """
        Versão otimizada e evoluída de processar_alocacao_de_demanda que usa dados pré-carregados.
        Implementa recursividade para itens produzíveis na BOM e cascata de estágios.
        """
        print(f"DEBUG: processar_alocacao_otimizado item={item_id} campo={campo} inc={incremento}")
        from nistiprint_shared.config.production_stages import ESTAGIOS_PRODUCAO
        from nistiprint_shared.services.bom_service import bom_service

        # --- GESTÃO DE CORRELAÇÃO E DATA ---
        cid = correlation_id or f"DASH-{uuid.uuid4().hex[:8]}"
        mov_date = retroactive_date or get_now_iso()

        # --- OBTER DEPÓSITO PADRÃO PARA MOVIMENTAÇÕES ---
        deposito_id = app_config_service.get_config('default_production_deposit_id') or 'principal'
        # ------------------------------------------------

        # ETAPA 1: VALIDAÇÃO E IDENTIFICAÇÃO
        item_demanda = itens_dict.get(str(item_id))
        if not item_demanda:
            raise ValueError(f"Item {item_id} não encontrado nos dados pré-carregados")

        if campo not in ESTAGIOS_PRODUCAO:
            self._atualizar_progresso_simples(item_id, campo, incremento)
            try:
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
                'message': f"Atualização visual apenas para campo {campo}",
                'correlation_id': cid
            }

        estagio = ESTAGIOS_PRODUCAO[campo]

        # 1.1. LÓGICA DE CASCATA (Preenchimento Automático de Estágios Anteriores)
        dependencia = estagio.get('depende_de')
        if dependencia and dependencia in item_demanda:
            valor_atual_dep = float(item_demanda.get(dependencia, 0) or 0)
            valor_atual_foco = float(item_demanda.get(campo, 0) or 0)
            novo_foco = valor_atual_foco + incremento

            if novo_foco > valor_atual_dep:
                diff = novo_foco - valor_atual_dep
                self.processar_alocacao_de_demanda_otimizado(
                    item_id, dependencia, diff, user_id, itens_dict, saldos_produtos, boms_produtos,
                    retroactive_date=mov_date, correlation_id=cid
                )
                item_demanda[dependencia] = novo_foco

        if not estagio.get('role_produto_gerado'):
            self._atualizar_progresso_simples(item_id, campo, incremento)
            try:
                daily_production_log_service.create_log(
                    log_date=datetime.fromisoformat(mov_date[:10]).date() if mov_date else datetime.now().date(),
                    product_id=str(item_demanda.get('produto_id')),
                    product_name="Etapa Administrativa",
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
                'status': 'SUCCESS',
                'message': f"Atualização visual de etapa administrativa {campo}",
                'correlation_id': cid
            }

        # ETAPA 2: IDENTIFICAÇÃO DO PRODUTO INTERMEDIÁRIO
        produto_intermediario = None
        if estagio['role_produto_gerado'] == 'MIOLO' and item_demanda.get('id_produto_miolo'):
            produto_intermediario = product_service.get_by_id(str(item_demanda['id_produto_miolo']))

        if not produto_intermediario:
            produto_final_id = item_demanda['produto_id']
            if produto_final_id:
                produto_intermediario = bom_service.get_component_by_role(produto_final_id, estagio['role_produto_gerado'])

        if not produto_intermediario:
            self._atualizar_progresso_simples(item_id, campo, incremento)
            return {
                'campo': campo,
                'incremento': incremento,
                'status': 'WARNING',
                'message': f"Produto com role '{estagio['role_produto_gerado']}' não encontrado na BOM.",
                'correlation_id': cid
            }

        # ETAPA 3: EXECUÇÃO HÍBRIDA (SYNC 1º NÍVEL / ASYNC BOM)
        permite_jit = estagio.get('permite_producao_jit', True)

        try:
            if not origem_tipo:
                origem_tipo = 1 if incremento > 0 else 2

            saldo_info = saldos_produtos.get(str(produto_intermediario['id']), {})
            saldo_disponivel = float(saldo_info.get('quantidade_disponivel', 0))

            if incremento > 0:
                qtd_saida_imediata = min(incremento, max(0.0, saldo_disponivel))

                if qtd_saida_imediata > 0:
                    try:
                        estoque_service.registrar_saida(
                            produto_id=int(produto_intermediario['id']),
                            deposito_id=deposito_id,
                            quantidade=qtd_saida_imediata,
                            motivo=f"Saída Síncrona (Dashboard) - Demanda {item_demanda.get('demanda_id')}",
                            user_context={'user_id': user_id},
                            documento_referencia=item_demanda.get('demanda_id'),
                            correlation_id=cid,
                            data_movimento=mov_date,
                            origem_tipo=0
                        )
                        if str(produto_intermediario['id']) in saldos_produtos:
                            saldos_produtos[str(produto_intermediario['id'])]['quantidade_disponivel'] -= qtd_saida_imediata

                        self._registrar_alocacao_estoque(
                            demanda_id=str(item_demanda.get('demanda_id')),
                            item_id=item_id,
                            produto_id=str(produto_intermediario['id']),
                            correlation_id=cid,
                            quantidade=qtd_saida_imediata,
                            tipo_alocacao='MANUAL_DASHBOARD',
                            processo_origem='DASHBOARD',
                            metadata={'campo': campo, 'qtd_saida_imediata': qtd_saida_imediata, 'qtd_fila_producao': incremento - qtd_saida_imediata}
                        )
                    except Exception as e_sync:
                        print(f"Erro na saída síncrona: {e_sync}")
                        import traceback
                        traceback.print_exc()
                else:
                    print(f"DEBUG: Sem estoque disponível para saída imediata. incremento={incremento}, saldo_disponivel={saldo_disponivel}")

                qtd_fila_producao = incremento - qtd_saida_imediata
                if qtd_fila_producao > 0:
                    self.agendar_processamento_estoque(
                        demanda_id=item_demanda.get('demanda_id'),
                        item_id=item_id,
                        campo=campo,
                        incremento=qtd_fila_producao,
                        user_id=user_id,
                        correlation_id=cid,
                        created_at=mov_date,
                        produto_id=int(produto_intermediario['id'])
                    )
            else:
                try:
                    estoque_service.registrar_entrada(
                        produto_id=int(produto_intermediario['id']),
                        deposito_id=deposito_id,
                        quantidade=abs(incremento),
                        observacao=f"Estorno Síncrono (Dashboard) - Demanda {item_demanda.get('demanda_id')}",
                        user_context={'user_id': user_id},
                        correlation_id=cid,
                        data_movimento=mov_date,
                        origem_tipo=0
                    )
                    if str(produto_intermediario['id']) in saldos_produtos:
                        saldos_produtos[str(produto_intermediario['id'])]['quantidade_disponivel'] += abs(incremento)

                    self._marcar_alocacao_cancelada(cid, f"Estorno de {abs(incremento)} unidades no campo {campo}")
                except Exception as e_estorno:
                    print(f"Erro no estorno síncrono: {e_estorno}")

            try:
                daily_production_log_service.create_log(
                    log_date=datetime.fromisoformat(mov_date[:10]).date() if mov_date else datetime.now().date(),
                    product_id=str(produto_intermediario['id']),
                    product_name=produto_intermediario.get('nome') or produto_intermediario.get('name', 'Produto'),
                    quantity=abs(incremento),
                    production_order_id=None,
                    component_stock_snapshot=[],
                    user_email=user_id,
                    metadata={
                        'demanda_id': item_demanda.get('demanda_id'),
                        'item_id': item_id,
                        'campo': campo,
                        'correlation_id': cid
                    }
                )
            except Exception as log_error:
                print(f"Erro ao registrar log diário de produção: {log_error}")

            self._atualizar_progresso_simples(item_id, campo, incremento)
            item_demanda[campo] = float(item_demanda.get(campo, 0) or 0) + incremento

        except Exception as e:
            print(f"ERRO DE ESTOQUE HÍBRIDO: {str(e)}")
            system_events_log_service.log_event(
                event_type='ERRO_ESTOQUE_HIBRIDO_PRODUCAO',
                details={'item_id': item_id, 'campo': campo, 'erro': str(e), 'produto_id': produto_intermediario['id']},
                user_id=user_id
            )
            try:
                self._atualizar_progresso_simples(item_id, campo, incremento)
            except: pass

        return {
            'campo': campo,
            'incremento': incremento,
            'status': 'SUCCESS',
            'message': "Processamento concluído (Estoque processado em modo best-effort)",
            'correlation_id': cid
        }

    def alocar_producao_automatica(self, produto_id: str, quantidade: float, user_id: str = 'System'):
        """
        Distribui uma quantidade produzida genericamente entre as demandas pendentes.
        Identifica se o produto é um miolo ou capa/final para atualizar o campo correto.
        """
        if quantidade <= 0:
            return 0

        from nistiprint_shared.services.app_config_service import app_config_service
        miolo_cat_id = app_config_service.get_config('producao_miolos_category_id')

        prod_details = product_service.get_by_id(str(produto_id))
        if not prod_details:
            return 0

        categoria_id = str(prod_details.get('categoria_id'))
        is_miolo = (categoria_id == str(miolo_cat_id))

        query = self.itens_table.select("*, demanda:demandas_producao(*)").neq('status_item', 'Concluído')

        if is_miolo:
            query = query.eq('id_produto_miolo', produto_id)
        else:
            query = query.eq('produto_id', produto_id)

        response = supabase_db.execute_with_retry(query)
        if not response.data:
            return 0

        itens_pendentes = []
        for item in response.data:
            demanda = item.get('demanda')
            if not demanda or demanda.get('status') in ['CONCLUIDO', 'CANCELADO']:
                continue
            itens_pendentes.append(item)

        def sort_priority(i):
            d = i['demanda']
            is_express = d.get('modalidade_logistica') == 'EXPRESS' or d.get('is_flex', False)
            prioridade = d.get('prioridade_manual', 0) or 0
            data = d.get('data_entrega', '9999-12-31')
            hora = d.get('horario_coleta', '23:59')
            return (not is_express, -int(prioridade), data, hora)

        itens_pendentes.sort(key=sort_priority)

        saldo_a_alocar = float(quantidade)
        alocacoes_realizadas = 0

        for item in itens_pendentes:
            if saldo_a_alocar <= 0:
                break

            qtd_total_item = item['quantidade']

            campo_progresso = 'miolos_prontos_retirada_qtd' if is_miolo else 'capas_produzidas_qtd'
            progresso_atual = item.get(campo_progresso, 0) or 0

            necessidade = qtd_total_item - progresso_atual
            if necessidade <= 0:
                continue

            alocacao = min(saldo_a_alocar, necessidade)
            novo_valor = progresso_atual + alocacao

            updates = {
                campo_progresso: novo_valor,
                'updated_at': get_now_iso(),
                'status_item': 'Em Andamento'
            }

            if not is_miolo and item.get('capas_impressas_qtd', 0) < novo_valor:
                updates['capas_impressas_qtd'] = novo_valor

            supabase_db.execute_with_retry(self.itens_table.update(updates).eq('id', item['id']))

            saldo_a_alocar -= alocacao
            alocacoes_realizadas += alocacao

            auditoria_service.log_event('ALOCACAO_AUTOMATICA', {
                'demanda_id': item['demanda_id'],
                'item_id': item['id'],
                'produto_id': produto_id,
                'quantidade': alocacao,
                'tipo': 'MIOLO' if is_miolo else 'CAPA/FINAL'
            }, user_id)

        return alocacoes_realizadas

    def get_demandas_ativas_por_item(self, produto_id: str) -> List[Dict[str, Any]]:
        """
        Retorna demandas ativas que contenham o produto_id (como miolo ou capa).
        Ordenado por prioridade de entrega.
        """
        from nistiprint_shared.services.app_config_service import app_config_service
        miolo_cat_id = str(app_config_service.get_config('producao_miolos_category_id') or '6')

        prod_details = product_service.get_by_id(str(produto_id))
        if not prod_details:
            return []

        is_miolo = (str(prod_details.get('categoria_id')) == miolo_cat_id)

        query = self.itens_table.select("*, demanda:demandas_producao(*)").neq('status_item', 'Concluído')
        if is_miolo:
            query = query.eq('id_produto_miolo', produto_id)
        else:
            query = query.eq('produto_id', produto_id)

        response = supabase_db.execute_with_retry(query)
        if not response.data:
            return []

        demandas_map = {}
        for item in response.data:
            dem = item.get('demanda')
            if not dem or dem.get('status') in ['CONCLUIDO', 'CANCELADO']:
                continue

            did = str(dem['id'])
            if did not in demandas_map:
                demandas_map[did] = self._core._process_demanda_dict(dem)
                demandas_map[did]['itens_relacionados'] = []
                demandas_map[did]['quantidade_total_pendente'] = 0
                demandas_map[did]['quantidade_total_produzida'] = 0

            item_data = self._process_item_dict(item)
            demandas_map[did]['itens_relacionados'].append(item_data)

            qty_total = float(item_data.get('quantidade', 0))

            if is_miolo:
                qty_produzida = float(item_data.get('miolos_prontos_retirada_qtd', 0))
            else:
                qty_produzida = float(item_data.get('capas_produzidas_qtd', 0))

            demandas_map[did]['quantidade_total_pendente'] += qty_total
            demandas_map[did]['quantidade_total_produzida'] += qty_produzida

        result = list(demandas_map.values())

        def sort_priority(d):
            is_express = d.get('modalidade_logistica') == 'EXPRESS' or d.get('is_flex', False)
            return (not is_express, d.get('data_entrega', '9999-12-31'), d.get('horario_coleta', '23:59'))

        result.sort(key=sort_priority)
        return result

    def get_pending_items_by_miolo(self, miolo_id: str) -> List[Dict[str, Any]]:
        """Alias para get_demandas_ativas_por_item para compatibilidade."""
        return self.get_demandas_ativas_por_item(miolo_id)

    def _process_demanda_dict(self, demanda: Dict[str, Any], itens: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Adiciona aliases e processa campos para o frontend."""
        if not demanda:
            return None
        d = dict(demanda)
        d['nome'] = d.get('descricao')
        d['manual_priority_score'] = d.get('prioridade_manual', 0)

        if itens is not None:
            d['total_itens'] = sum(i.get('quantidade', 0) for i in itens)
            d['total_quantidade'] = d['total_itens']
            d['itens_finalizados_total'] = sum(float(i.get('finalizados_qtd', 0)) for i in itens)
            d['itens_finalizados'] = d['itens_finalizados_total']
            d['itens_prontos_total'] = sum(min(i.get('capas_prontas_retirada_qtd') or 0, i.get('miolos_prontos_retirada_qtd') or 0) for i in itens)
            d['itens_concluidos'] = d['itens_prontos_total']

        return d

    def _process_item_dict(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Adiciona aliases e processa campos para o frontend."""
        if not item:
            return None
        i = dict(item)
        i['item_descricao'] = i.get('descricao')
        i['quantidade_total'] = i.get('quantidade')
        i['miolo_name'] = i.get('miolo_nome')
        return i

    def agendar_processamento_estoque(self, demanda_id, item_id, campo, incremento, user_id='System', correlation_id=None, created_at=None, produto_id=None, forcar_sincrono=False):
        """Agenda o processamento de estoque na fila e dispara o worker via Celery."""
        if incremento == 0:
            return
        try:
            now = get_now_iso()

            tipo_op = campo
            if campo in ['ITEM_TOTAL_BOM_PROCESS', 'DEMANDA_TOTAL', 'CONSUMO_BOM', 'ESTORNO_BOM', 'PRODUCAO_AVULSA', 'ESTORNO_AVULSO']:
                tipo_op = campo
            else:
                tipo_op = f"ETAPA:{campo}"

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
                'created_at': created_at or now
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

    def processar_insumos_por_bom_recursivo(self, produto_id: int, quantidade: float, correlation_id: str, user_id: str, tipo_operacao: str = 'CONSUMO_BOM', retroactive_date: Optional[str] = None, item_id_referencia: str = None, qtd_a_produzir_forcada: float = None):
        """
        Motor de Produção Waterfall:
        1. Verifica estoque disponível (apenas se CONSUMO_BOM).
        2. Se houver estoque, consome (SAÍDA).
        3. Se faltar e houver BOM, produz o restante recursivamente (ENTRADA + SAÍDA).
        4. Se for PRODUCAO_AVULSA, produz sem consumir o item final (fica no estoque).
        5. VERIFICA alocações manuais existentes para evitar duplicação (apenas se item_id_referencia fornecido).
        """
        print(f"DEBUG [WATERFALL] Processando Produto {produto_id}, Qtd: {quantidade}, Operacao: {tipo_operacao}, Correlation: {correlation_id}, ItemRef: {item_id_referencia}, QtdProduzirForcada: {qtd_a_produzir_forcada}")
        from nistiprint_shared.services.bom_service import bom_service
        from nistiprint_shared.services.app_config_service import app_config_service

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
            else:
                print(f"DEBUG [WATERFALL] Sem alocações manuais para {produto_id}. Processando {quantidade} unidades normalemente.")

        qtd_estoque = 0.0

        if tipo_operacao == 'CONSUMO_BOM':
            if qtd_a_produzir_forcada is not None:
                qtd_a_produzir = qtd_a_produzir_forcada
                print(f"DEBUG [WATERFALL] Usando qtd_a_produzir_forcada={qtd_a_produzir_forcada}")
            else:
                saldo_info = estoque_service.get_saldo_atual(produto_id, default_deposito_id)
                disponivel = float(saldo_info.get('quantidade_disponivel', 0) or 0)

                qtd_estoque = min(max(0.0, disponivel), quantidade)
                qtd_a_produzir = quantidade - qtd_estoque

                print(f"DEBUG [WATERFALL] Produto {produto_id}: Disponivel={disponivel}, UsarEstoque={qtd_estoque}, Produzir={qtd_a_produzir}")

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
            print(f"DEBUG [WATERFALL] Produção Avulsa para {produto_id}: Produzindo {quantidade}...")

        if qtd_a_produzir <= 0:
            print(f"DEBUG [WATERFALL] Produto {produto_id}: qtd_a_produzir={qtd_a_produzir}. Pulando explosão BOM.")
            return

        componentes = bom_service.get_bom_for_produto(produto_id)

        if componentes and tipo_operacao in ['CONSUMO_BOM', 'PRODUCAO_AVULSA']:
            print(f"DEBUG [WATERFALL] Produto {produto_id} tem BOM. Explodindo para {qtd_a_produzir} unidades...")
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


demanda_alocacao_estoque_service = DemandaAlocacaoEstoqueService()
