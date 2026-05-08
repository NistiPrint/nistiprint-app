"""
Motor de Reconciliação de Estoque - Implementação Determinística

Este motor garante a integridade do consumo de estoque independentemente da ordem
dos apontamentos de produção. Implementa as premissas:

1. Intermediários NUNCA ficam negativos (produção compensatória)
2. Matérias-primas PODEM ficar negativas (apenas log de alerta)
3. Finalização é o gatilho de liquidação (BOM explosion completo)
4. Etapas anteriores são apenas sinais visuais
5. Cálculo por delta (ledger + estado esperado)
6. Processamento assíncrono com fila
7. Idempotência e atomicidade garantidas

Autor: NistiPrint
Data: 2026-03-25
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
from decimal import Decimal
import uuid
import asyncio

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.estoque_service import estoque_service
from nistiprint_shared.services.bom_service import bom_service
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.demanda_alocacao.estoque import demanda_alocacao_estoque_service
from nistiprint_shared.utils.date_utils import get_now_iso


# ============================================================
# DATA CLASSES
# ============================================================

class IntencaoItem:
    """Representa a intenção de produção reportada pelo usuário."""
    def __init__(self, item: Dict[str, Any]):
        self.item_id = item.get('id')
        self.demanda_id = item.get('demanda_id')
        self.demanda_total = Decimal(str(item.get('quantidade', 0) or 0))

        # Valores reportados (visuais)
        self.finalizados = Decimal(str(item.get('finalizados_qtd', 0) or 0))
        self.exp_capa = Decimal(str(item.get('expedicao_capas_retiradas_qtd', 0) or 0))
        self.exp_miolo = Decimal(str(item.get('expedicao_miolos_retirados_qtd', 0) or 0))
        self.capa_pronta = Decimal(str(item.get('capas_prontas_retirada_qtd', 0) or 0))
        self.miolo_pronto = Decimal(str(item.get('miolos_prontos_retirada_qtd', 0) or 0))
        self.capa_prod = Decimal(str(item.get('capas_produzidas_qtd', 0) or 0))
        self.capa_imp = Decimal(str(item.get('capas_impressas_qtd', 0) or 0))


class QuantidadesEfetivas:
    """Quantidades calculadas após aplicação do waterfall top-down."""
    def __init__(self,
                 finalizados: Decimal,
                 exp_capa: Decimal,
                 exp_miolo: Decimal,
                 capa_pronta: Decimal,
                 miolo_pronto: Decimal,
                 capa_prod: Decimal,
                 capa_imp: Decimal):
        self.finalizados = finalizados
        self.exp_capa = exp_capa
        self.exp_miolo = exp_miolo
        self.capa_pronta = capa_pronta
        self.miolo_pronto = miolo_pronto
        self.capa_prod = capa_prod
        self.capa_imp = capa_imp

    def to_dict(self) -> Dict[str, Decimal]:
        return {
            'finalizados_qtd': self.finalizados,
            'expedicao_capas_retiradas_qtd': self.exp_capa,
            'expedicao_miolos_retirados_qtd': self.exp_miolo,
            'capas_prontas_retirada_qtd': self.capa_pronta,
            'miolos_prontos_retirada_qtd': self.miolo_pronto,
            'capas_produzidas_qtd': self.capa_prod,
            'capas_impressas_qtd': self.capa_imp
        }


class Movimento:
    """Representa uma movimentação de estoque a ser registrada."""
    def __init__(self,
                 produto_id: int,
                 tipo: str,  # CONS_MP, PROD_INT, CONS_INT, PROD_ACAB, etc.
                 quantidade: Decimal,
                 motivo: str,
                 estagio: Optional[str] = None,
                 deposito_id: Optional[int] = None,
                 saldo_acumulado: Decimal = Decimal('0')):
        self.produto_id = produto_id
        self.tipo = tipo
        self.quantidade = quantidade
        self.motivo = motivo
        self.estagio = estagio
        self.deposito_id = deposito_id  # Novo: depósito explícito
        self.saldo_acumulado = saldo_acumulado


class ReconciliacaoResultado:
    """Resultado de uma reconciliação."""
    def __init__(self,
                 sucesso: bool,
                 item_id: int,
                 demanda_id: int,
                 correlation_id: str,
                 movimentos: Optional[List[Movimento]] = None,
                 erros: Optional[List[str]] = None,
                 metadata: Optional[Dict[str, Any]] = None):
        self.sucesso = sucesso
        self.item_id = item_id
        self.demanda_id = demanda_id
        self.correlation_id = correlation_id
        self.movimentos = movimentos or []
        self.erros = erros or []
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            'sucesso': self.sucesso,
            'item_id': self.item_id,
            'demanda_id': self.demanda_id,
            'correlation_id': self.correlation_id,
            'movimentos_count': len(self.movimentos),
            'erros': self.erros,
            'metadata': self.metadata
        }


# ============================================================
# MOTOR DE RECONCILIAÇÃO
# ============================================================

class MotorReconciliacaoEstoque:
    """
    Motor determinístico de reconciliação de estoque.
    Implementa lógica waterfall top-down com produção compensatória.
    """

    def __init__(self):
        self.ledger_table = supabase_db.table('demanda_estoque_processado')
        self.eventos_table = supabase_db.table('eventos_producao')
        self.produtos_table = supabase_db.table('produtos')
        self.depositos_table = supabase_db.table('depositos')

        # Mapeamento de estágios para produtos (será carregado dinamicamente)
        self._cache_produtos_estagio: Dict[int, Dict[str, int]] = {}
        self._deposito_padrao_id: Optional[int] = None

    def _get_deposito_padrao(self) -> int:
        """Obtém o depósito padrão (id=1 ou primeiro disponível)."""
        if self._deposito_padrao_id is not None:
            return self._deposito_padrao_id

        response = self.depositos_table.select('id').order('id').limit(1).execute()
        if response.data:
            self._deposito_padrao_id = response.data[0]['id']
        else:
            self._deposito_padrao_id = 1  # Fallback

        return self._deposito_padrao_id

    async def reconcile_item(self, item_id: int, demanda_id: int, user_id: str = 'System') -> ReconciliacaoResultado:
        """
        Orquestra reconciliação completa de um item.
        Chamado APENAS na finalização (E7).

        Args:
            item_id: ID do item de demanda
            demanda_id: ID da demanda de produção
            user_id: ID do usuário que disparou a reconciliação

        Returns:
            ReconciliacaoResultado com detalhes das movimentações.
        """
        correlation_id = str(uuid.uuid4())

        try:
            # 1. Adquirir lock para prevenir concorrência
            lock_adquirido = await self._adquirir_lock_item(item_id)
            if not lock_adquirido:
                return ReconciliacaoResultado(
                    sucesso=False,
                    item_id=item_id,
                    demanda_id=demanda_id,
                    correlation_id=correlation_id,
                    erros=['Item já está sendo processado por outra transação']
                )

            try:
                # 2. Ler intenção (estado visual atual do item)
                intencao = await self._ler_intencao_item(item_id)
                if not intencao:
                    return ReconciliacaoResultado(
                        sucesso=False,
                        item_id=item_id,
                        demanda_id=demanda_id,
                        correlation_id=correlation_id,
                        erros=['Item não encontrado']
                    )

                # 3. Calcular quantidades efetivas (waterfall top-down)
                efetivas = await self._calcular_quantidades_efetivas(intencao)

                # 4. Ler realizado (ledger)
                realizado = await self._ler_ledger_item(item_id)

                # 5. Calcular deltas
                deltas = await self._calcular_deltas(efetivas, realizado)

                # 6. Processar deltas em transação única via RPC
                resultado = await self._processar_deltas_transacional(
                    item_id, demanda_id, deltas, efetivas, intencao, realizado, user_id, correlation_id
                )

                # 7. Registrar evento de produção como processado
                await self._registrar_evento_processado(
                    item_id, demanda_id, 'finalizados_qtd',
                    intencao.finalizados, efetivas.finalizados, correlation_id
                )

                return resultado

            finally:
                # Liberar lock
                await self._liberar_lock_item(item_id)

        except Exception as e:
            print(f"ERRO CRÍTICO na reconciliação do item {item_id}: {e}")
            import traceback
            traceback.print_exc()

            return ReconciliacaoResultado(
                sucesso=False,
                item_id=item_id,
                demanda_id=demanda_id,
                correlation_id=correlation_id,
                erros=[str(e)]
            )

    def processar_fila_unificada(self, limit=50) -> int:
        """
        Método unificado para consumir tarefas da fila 'fila_processamento_estoque'
        usando a lógica determinística do Motor de Reconciliação (MRE).
        """
        from nistiprint_shared.database.supabase_db_service import supabase_db
        from nistiprint_shared.utils.date_utils import get_now_iso
        import uuid
        import socket
        import asyncio

        worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
        fila_table = supabase_db.table('fila_processamento_estoque')

        # Busca tarefas PENDENTES/ERRO usando a RPC force_fetch_all_tasks
        res = supabase_db.rpc('force_fetch_all_tasks', {
            'p_worker_id': worker_id,
            'p_limit': limit
        }).execute()

        if not res.data:
            return 0

        processed = 0
        for tarefa in res.data:
            t_id = tarefa['id']
            try:
                # Delega para a reconciliação (se for tarefa de reconciliação de item)
                if tarefa.get('tipo_operacao') in ['RECONCILIACAO_ITEM', 'ITEM_TOTAL_BOM_PROCESS']:
                    item_id = tarefa.get('item_id')
                    demanda_id = tarefa.get('demanda_id')
                    user_id = tarefa.get('user_id', 'Worker')

                    resultado = asyncio.run(self.reconcile_item(
                        item_id=int(item_id) if item_id else None,
                        demanda_id=int(demanda_id) if demanda_id else None,
                        user_id=str(user_id)
                    ))

                    if resultado.sucesso:
                        fila_table.update({'status': 'CONCLUIDO', 'processed_at': get_now_iso()}).eq('id', t_id).execute()
                        processed += 1
                    else:
                        raise Exception(f"Falha MRE: {resultado.erros}")
                
                elif tarefa.get('tipo_operacao') in ['CONSUMO_BOM', 'ESTORNO_BOM']:
                    # Produção Avulsa ou OP: explode BOM e consome insumos
                    produto_id = tarefa.get('produto_id')
                    quantidade = Decimal(str(tarefa.get('quantidade', 0)))
                    user_id = tarefa.get('user_id', 'Worker')
                    correlation_id = tarefa.get('correlation_id')
                    tipo_op = tarefa.get('tipo_operacao')
                    
                    if not produto_id or quantidade <= 0:
                        fila_table.update({'status': 'SKIPPED', 'mensagem_erro': 'Dados inválidos'}).eq('id', t_id).execute()
                        continue

                    # Se for estorno, a quantidade deve ser negativa para a explosão de consumo
                    multiplicador = Decimal('-1') if tipo_op == 'ESTORNO_BOM' else Decimal('1')
                    
                    # Explodir BOM recursivamente para gerar movimentos de insumos
                    movimentos = asyncio.run(self._explodir_bom_consumo(
                        produto_id=int(produto_id),
                        quantidade=quantidade * multiplicador,
                        demanda_id=None,
                        user_id=user_id,
                        deposito_padrao=self._get_deposito_padrao()
                    ))
                    
                    # Persistir movimentos via RPC
                    snapshot = {
                        'tipo_operacao': tipo_op,
                        'produto_principal_id': produto_id,
                        'quantidade_principal': float(quantidade)
                    }
                    
                    resultado = asyncio.run(self._persistir_via_rpc(
                        movimentos=movimentos,
                        item_id=None,
                        demanda_id=None,
                        correlation_id=correlation_id,
                        user_id=user_id,
                        snapshot=snapshot
                    ))
                    
                    if resultado.sucesso:
                        fila_table.update({'status': 'CONCLUIDO', 'processed_at': get_now_iso()}).eq('id', t_id).execute()
                        processed += 1
                    else:
                        raise Exception(f"Falha MRE (Avulsa): {resultado.erros}")
                
                else:
                    # Caso outros tipos existam, logar ou tratar conforme necessário
                    print(f"DEBUG: Tipo de tarefa {tarefa.get('tipo_operacao')} ainda não migrado para o MRE")
                    fila_table.update({'status': 'SKIPPED', 'mensagem_erro': 'Tipo não suportado pelo novo motor'}).eq('id', t_id).execute()

            except Exception as e:
                print(f"[MRE] Erro na tarefa {t_id}: {e}")
                fila_table.update({'status': 'ERRO', 'mensagem_erro': str(e)}).eq('id', t_id).execute()

        return processed

    async def _ler_intencao_item(self, item_id: int) -> Optional[IntencaoItem]:
        """Lê o estado visual atual do item (valores reportados)."""
        response = supabase_db.table('itens_demanda')\
            .select('*')\
            .eq('id', item_id)\
            .execute()

        if not response.data:
            return None

        return IntencaoItem(response.data[0])

    async def _calcular_quantidades_efetivas(self, intencao: IntencaoItem) -> QuantidadesEfetivas:
        """
        Aplica propagação waterfall top-down.
        Garante que nenhuma etapa tenha menos que a etapa seguinte.

        Lógica:
        - Finalizados puxam todas as etapas anteriores
        - Cada etapa deve cobrir pelo menos o que a etapa seguinte exige
        - Nenhuma etapa pode exceder a demanda total
        """
        demanda_total = intencao.demanda_total

        # Top-down: finalizados puxam todas as etapas anteriores
        eff_finalizados = min(intencao.finalizados, demanda_total)

        # Retiradas (Setor 4 - Expedição)
        eff_exp_capa = min(max(intencao.exp_capa, eff_finalizados), demanda_total)
        eff_exp_miolo = min(max(intencao.exp_miolo, eff_finalizados), demanda_total)

        # Prontas para retirada
        eff_capa_pronta = min(max(intencao.capa_pronta, eff_exp_capa), demanda_total)
        eff_miolo_pronto = min(max(intencao.miolo_pronto, eff_exp_miolo), demanda_total)

        # Produção (Setor 2 e 1)
        eff_capa_prod = min(max(intencao.capa_prod, eff_capa_pronta), demanda_total)
        eff_capa_imp = min(max(intencao.capa_imp, eff_capa_prod), demanda_total)

        return QuantidadesEfetivas(
            finalizados=eff_finalizados,
            exp_capa=eff_exp_capa,
            exp_miolo=eff_exp_miolo,
            capa_pronta=eff_capa_pronta,
            miolo_pronto=eff_miolo_pronto,
            capa_prod=eff_capa_prod,
            capa_imp=eff_capa_imp
        )

    async def _ler_ledger_item(self, item_id: int) -> Dict[str, Decimal]:
        """
        Busca o saldo acumulado de processamento para cada estágio no ledger.
        Soma todas as movimentações do item.
        """
        response = self.ledger_table\
            .select('estagio', 'quantidade')\
            .eq('item_id', item_id)\
            .execute()

        ledger: Dict[str, Decimal] = {}

        if response.data:
            for row in response.data:
                estagio = row['estagio']
                quantidade = Decimal(str(row['quantidade'] or 0))
                ledger[estagio] = ledger.get(estagio, Decimal('0')) + quantidade

        return ledger

    async def _calcular_deltas(self, efetivas: QuantidadesEfetivas,
                                realizado: Dict[str, Decimal]) -> Dict[str, Decimal]:
        """
        Calcula a diferença entre o efetivo e o já processado.
        Apenas deltas > 0 serão processados.
        """
        deltas = {}
        efetivas_dict = efetivas.to_dict()

        for estagio, valor_efetivo in efetivas_dict.items():
            valor_realizado = realizado.get(estagio, Decimal('0'))
            delta = valor_efetivo - valor_realizado

            # Apenas processa se delta > 0 (tolerância para float)
            if delta > Decimal('0.001'):
                deltas[estagio] = delta

        return deltas

    async def _processar_deltas_transacional(
        self,
        item_id: int,
        demanda_id: int,
        deltas: Dict[str, Decimal],
        efetivas: QuantidadesEfetivas,
        intencao: IntencaoItem,
        realizado: Dict[str, Decimal],
        user_id: str,
        correlation_id: str
    ) -> ReconciliacaoResultado:
        """
        Gera movimentos e delega a persistência atômica para a RPC Postgres.
        Implementa produção compensatória recursiva.
        """
        movimentos: List[Movimento] = []
        erros: List[str] = []
        deposito_padrao = self._get_deposito_padrao()

        try:
            # Obter produto pai uma única vez
            response = supabase_db.table('itens_demanda').select('produto_id').eq('id', item_id).execute()
            if not response.data:
                return ReconciliacaoResultado(False, item_id, demanda_id, correlation_id, erros=['Produto pai não encontrado'])
            produto_pai_id = response.data[0]['produto_id']

            # Processar cada estágio com delta
            for estagio, delta in deltas.items():
                # Identificar produtos associados ao estágio
                produtos_ids = await self._get_produtos_por_estagio(item_id, estagio, produto_pai_id)

                if not produtos_ids:
                    # Estágio sem produto associado (ex: administrativo)
                    continue

                for produto_id in produtos_ids:
                    # Obter tipo do produto
                    tipo_produto = await self._get_tipo_produto(produto_id)

                    # Regra: se tem BOM, prioriza estoque e faz produção compensatória (JIT)
                    componentes_bom = await self._get_componentes_bom(produto_id)
                    tem_bom = len(componentes_bom) > 0

                    if tem_bom:
                        # Produto com BOM (Intermediário ou Acabado): NUNCA fica negativo
                        saldo_info = await self._get_saldo_disponivel(produto_id)
                        saldo_disponivel = Decimal(str(saldo_info.get('quantidade_disponivel', 0) or 0))

                        # Estágio finalizados_qtd é PRODUÇÃO de produto acabado:
                        # gera apenas a entrada (PROD_ACAB) e explode BOM para consumir insumos.
                        # Os demais estágios são CONSUMO de intermediários: tentam estoque primeiro,
                        # produzem JIT o restante, e SEMPRE consomem o total (CONS_INT espelhando o JIT).
                        is_producao_acabado = (estagio == 'finalizados_qtd')

                        if is_producao_acabado:
                            # PROD_ACAB sempre +delta (entra no estoque do acabado)
                            movimentos.append(Movimento(
                                produto_id=produto_id,
                                tipo='PROD_ACAB',
                                quantidade=+delta,
                                motivo=f'Produção produto acabado {estagio} demanda {demanda_id}',
                                estagio=estagio,
                                deposito_id=deposito_padrao
                            ))
                            # Explode BOM para consumir intermediários/MPs do acabado
                            movimentos_bom = await self._explodir_bom_consumo(
                                produto_id, delta, demanda_id, user_id, deposito_padrao
                            )
                            movimentos.extend(movimentos_bom)
                        else:
                            # Estágios de CONSUMO de intermediário
                            qtd_usar_estoque = min(saldo_disponivel, delta)
                            qtd_faltante = delta - qtd_usar_estoque

                            # 1. Consome do estoque (parte coberta)
                            if qtd_usar_estoque > 0:
                                movimentos.append(Movimento(
                                    produto_id=produto_id,
                                    tipo='CONS_INT',
                                    quantidade=-qtd_usar_estoque,
                                    motivo=f'Consumo {estagio} demanda {demanda_id}',
                                    estagio=estagio,
                                    deposito_id=deposito_padrao
                                ))

                            # 2. Faltante: produz JIT, consome espelhado e explode BOM
                            if qtd_faltante > 0:
                                # 2.a Entrada virtual JIT
                                movimentos.append(Movimento(
                                    produto_id=produto_id,
                                    tipo='PROD_INT',
                                    quantidade=+qtd_faltante,
                                    motivo=f'Auto-produção JIT {estagio} demanda {demanda_id}',
                                    estagio=estagio,
                                    deposito_id=deposito_padrao
                                ))
                                # 2.b Saída espelhada (esse JIT só existe pra alocação à demanda)
                                movimentos.append(Movimento(
                                    produto_id=produto_id,
                                    tipo='CONS_INT',
                                    quantidade=-qtd_faltante,
                                    motivo=f'Consumo JIT {estagio} demanda {demanda_id}',
                                    estagio=estagio,
                                    deposito_id=deposito_padrao
                                ))
                                # 2.c Recursão: explode BOM do componente faltante
                                movimentos_bom = await self._explodir_bom_consumo(
                                    produto_id, qtd_faltante, demanda_id, user_id, deposito_padrao
                                )
                                movimentos.extend(movimentos_bom)

                    else:
                        # Produto sem BOM (Matéria-prima ou Base): consome direto (pode ir negativo)
                        movimentos.append(Movimento(
                            produto_id=produto_id,
                            tipo='CONS_MP',
                            quantidade=delta * Decimal('-1'),
                            motivo=f'Consumo {estagio} demanda {demanda_id}',
                            estagio=estagio,
                            deposito_id=deposito_padrao
                        ))

            # Preparar Snapshot para Auditoria
            snapshot = {
                'qtd_finalizada': float(intencao.finalizados),
                'bom_necessario': [],
                'ledger_anterior': {k: float(v) for k, v in realizado.items()},
                'deltas_calculados': {k: float(v) for k, v in deltas.items()},
                'efetivas_calculadas': {k: float(v) for k, v in efetivas.to_dict().items()}
            }

            # Persistir TUDO atomicamente via RPC
            resultado_rpc = await self._persistir_via_rpc(movimentos, item_id, demanda_id, correlation_id, user_id, snapshot)

            if not resultado_rpc.sucesso:
                return resultado_rpc

            # Libera reservas correspondentes
            await self._liberar_reservas(demanda_id, deltas, item_id)

            return ReconciliacaoResultado(
                sucesso=True,
                item_id=item_id,
                demanda_id=demanda_id,
                correlation_id=correlation_id,
                movimentos=movimentos,
                erros=erros,
                metadata={
                    'deltas_processados': {k: float(v) for k, v in deltas.items()},
                    'efetivas': {k: float(v) for k, v in efetivas.to_dict().items()}
                }
            )

        except Exception as e:
            print(f"ERRO ao processar deltas transacionais: {e}")
            import traceback
            traceback.print_exc()
            erros.append(str(e))

            return ReconciliacaoResultado(
                sucesso=False,
                item_id=item_id,
                demanda_id=demanda_id,
                correlation_id=correlation_id,
                movimentos=movimentos,
                erros=erros
            )

    async def _explodir_bom_consumo(
        self,
        produto_id: int,
        quantidade: Decimal,
        demanda_id: int,
        user_id: str,
        deposito_padrao: int,
        profundidade: int = 0,
        max_profundidade: int = 10
    ) -> List[Movimento]:
        """
        Explosão recursiva de BOM para produção compensatória.
        """
        if profundidade >= max_profundidade:
            print(f"AVISO: Atingida profundidade máxima {max_profundidade} na explosão de BOM")
            return []

        movimentos: List[Movimento] = []

        # Obter componentes do produto
        componentes = await self._get_componentes_bom(produto_id)

        if not componentes:
            return movimentos

        for comp in componentes:
            comp_id = comp.get('componente_id')
            qtd_necessaria = Decimal(str(comp.get('quantidade_necessaria', 1))) * quantidade

            if not comp_id:
                continue

            tipo_componente = await self._get_tipo_produto(comp_id)
            if tipo_componente == 'PRODUTO_ACABADO':
                raise ValueError(
                    f"BOM invalida: produto acabado {comp_id} nao pode ser componente de {produto_id}"
                )

            # Obter componentes da BOM do próprio componente (para recursão JIT)
            sub_componentes = await self._get_componentes_bom(comp_id)
            tem_bom = len(sub_componentes) > 0

            if tem_bom:
                # Produto tem BOM: prioriza estoque e produz recursivamente se faltar
                saldo_info = await self._get_saldo_disponivel(comp_id)
                saldo_disponivel = Decimal(str(saldo_info.get('quantidade_disponivel', 0) or 0))

                qtd_usar_estoque = min(saldo_disponivel, qtd_necessaria)
                qtd_faltante = qtd_necessaria - qtd_usar_estoque

                # Consome do estoque
                if qtd_usar_estoque > 0:
                    movimentos.append(Movimento(
                        produto_id=comp_id,
                        tipo='CONS_INT',
                        quantidade=-qtd_usar_estoque,
                        motivo=f'Consumo componente para produção {produto_id} demanda {demanda_id}',
                        estagio=f'bom_{produto_id}',
                        deposito_id=deposito_padrao
                    ))

                # Produz compensatório
                if qtd_faltante > 0:
                    # 1. Entrada virtual (PROD_INT JIT) — produz a quantidade faltante
                    movimentos.append(Movimento(
                        produto_id=comp_id,
                        tipo='PROD_INT',
                        quantidade=+qtd_faltante,
                        motivo=f'Auto-produção JIT {comp_id} para {produto_id} demanda {demanda_id}',
                        estagio=f'bom_{produto_id}',
                        deposito_id=deposito_padrao
                    ))

                    # 2. Saída espelhada (CONS_INT) — esse JIT só existe para virar o pai;
                    #    sem essa saída, o saldo do componente ficaria positivo indevidamente.
                    movimentos.append(Movimento(
                        produto_id=comp_id,
                        tipo='CONS_INT',
                        quantidade=-qtd_faltante,
                        motivo=f'Consumo JIT de {comp_id} para produção {produto_id} demanda {demanda_id}',
                        estagio=f'bom_{produto_id}',
                        deposito_id=deposito_padrao
                    ))

                    # 3. Recursão: explode o BOM do componente JIT para consumir suas MPs
                    movimentos_rec = await self._explodir_bom_consumo(
                        comp_id, qtd_faltante, demanda_id, user_id, deposito_padrao,
                        profundidade + 1, max_profundidade
                    )
                    movimentos.extend(movimentos_rec)

            else:
                # Produto sem BOM (Matéria-prima/Folha): consome direto (pode negativo)
                movimentos.append(Movimento(
                    produto_id=comp_id,
                    tipo='CONS_MP',
                    quantidade=-qtd_necessaria,
                    motivo=f'Consumo componente folha {comp_id} para produção {produto_id} demanda {demanda_id}',
                    estagio=f'bom_{produto_id}',
                    deposito_id=deposito_padrao
                ))

        return movimentos

    async def _get_produtos_por_estagio(self, item_id: int, estagio: str, produto_pai_id: Optional[int] = None) -> List[int]:
        """
        Resolve estágio → lista de produtos baseada na Categoria + BOM do item.
        Implementa cache para evitar queries repetitivas.
        """
        from nistiprint_shared.config.production_stages import ESTAGIOS_PRODUCAO
        from nistiprint_shared.services.app_config_service import app_config_service

        # 1. Verificar Cache
        cache_key = f"{item_id}_{estagio}"
        if cache_key in self._cache_produtos_estagio.get(item_id, {}):
            return self._cache_produtos_estagio[item_id][estagio]

        # 2. Obter configuração do estágio
        stage_config = ESTAGIOS_PRODUCAO.get(estagio)

        # 3. Obter produto pai se não fornecido
        if not produto_pai_id:
            response = supabase_db.table('itens_demanda').select('produto_id').eq('id', item_id).execute()
            if not response.data:
                return []
            produto_pai_id = response.data[0]['produto_id']

        # Se o estágio não existe na config ou não tem config_key, assume o produto pai (ex: finalizados)
        if not stage_config or not stage_config.get('config_key'):
            res = [produto_pai_id]
            self._cache_produtos_estagio.setdefault(item_id, {})[estagio] = res
            return res

        config_key = stage_config.get('config_key')

        # 4. Obter categoria alvo da configuração
        target_category_id = app_config_service.get_config(config_key)
        if not target_category_id:
            res = [produto_pai_id]
            self._cache_produtos_estagio.setdefault(item_id, {})[estagio] = res
            return res

        # 5. Resolver produtos na BOM que pertencem a essa categoria
        componentes = await self._get_componentes_bom(produto_pai_id)
        if not componentes:
            res = [produto_pai_id]
            self._cache_produtos_estagio.setdefault(item_id, {})[estagio] = res
            return res

        matching_ids = []
        for comp in componentes:
            comp_id = comp['componente_id']
            prod_info = product_service.get_by_id(str(comp_id))
            if prod_info and str(prod_info.get('categoria_id')) == str(target_category_id):
                matching_ids.append(comp_id)

        # Fallback: se não achou na BOM, verifica o pai
        if not matching_ids:
            prod_pai_info = product_service.get_by_id(str(produto_pai_id))
            if prod_pai_info and str(prod_pai_info.get('categoria_id')) == str(target_category_id):
                matching_ids = [produto_pai_id]
            else:
                matching_ids = [produto_pai_id]

        self._cache_produtos_estagio.setdefault(item_id, {})[estagio] = matching_ids
        return matching_ids

    async def _get_tipo_produto(self, produto_id: int) -> str:
        """Obtém o tipo de produto (MATERIA_PRIMA, INTERMEDIARIO, PRODUTO_ACABADO)."""
        response = self.produtos_table\
            .select('tipo_produto')\
            .eq('id', produto_id)\
            .execute()

        if not response.data:
            return 'MATERIA_PRIMA'

        return response.data[0].get('tipo_produto', 'MATERIA_PRIMA')

    async def _get_componentes_bom(self, produto_id: int) -> List[Dict[str, Any]]:
        """Obtém componentes da BOM de um produto."""
        response = supabase_db.table('ficha_tecnica')\
            .select('componente_id, quantidade_necessaria')\
            .eq('produto_pai_id', produto_id)\
            .execute()

        return response.data or []

    async def _get_saldo_disponivel(self, produto_id: int) -> Dict[str, Any]:
        """Obtém saldo disponível de um produto."""
        return estoque_service.get_saldo_atual(produto_id)

    async def _persistir_via_rpc(self,
                                  movimentos: List[Movimento],
                                  item_id: int,
                                  demanda_id: int,
                                  correlation_id: str,
                                  user_id: str,
                                  snapshot: Dict[str, Any]) -> ReconciliacaoResultado:
        """
        Persiste todos os movimentos e snapshot atomicamente via RPC.
        """
        if not movimentos and not snapshot:
            return ReconciliacaoResultado(True, item_id, demanda_id, correlation_id)

        # 1. Converter movimentos para formato JSON
        mov_json = []
        for m in movimentos:
            mov_json.append({
                'produto_id': m.produto_id,
                'deposito_id': m.deposito_id,
                'tipo': m.tipo,
                'quantidade': float(m.quantidade),
                'motivo': m.motivo,
                'estagio': m.estagio
            })

        try:
            # 2. Chamar RPC Atômica
            params = {
                'p_item_id': item_id,
                'p_demanda_id': demanda_id,
                'p_movimentos': mov_json,
                'p_snapshot': snapshot,
                'p_correlation_id': correlation_id,
                'p_user_id': user_id
            }

            response = supabase_db.rpc('reconciliar_item_estoque', params).execute()

            if not response.data or not response.data.get('sucesso'):
                erro_msg = response.data.get('erro') if response.data else "Erro desconhecido na RPC"
                raise Exception(f"Falha na RPC de reconciliação: {erro_msg}")

            # 3. Sucesso!
            return ReconciliacaoResultado(
                sucesso=True,
                item_id=item_id,
                demanda_id=demanda_id,
                correlation_id=correlation_id,
                movimentos=movimentos,
                metadata={
                    'rpc_response': response.data,
                    'snapshot_id': response.data.get('snapshot_id')
                }
            )

        except Exception as e:
            print(f"ERRO CRÍTICO ao persistir via RPC: {e}")
            return ReconciliacaoResultado(
                sucesso=False,
                item_id=item_id,
                demanda_id=demanda_id,
                correlation_id=correlation_id,
                movimentos=movimentos,
                erros=[str(e)]
            )

    async def _liberar_reservas(self, demanda_id: int, deltas: Dict[str, Decimal], item_id: int):
        """
        Libera as reservas dos componentes consumidos nesta reconciliação.
        Integra com demanda_alocacoes_estoque para liberar reservas proporcionalmente.
        """
        try:
            if not deltas:
                return

            # Para cada estágio processado, libera reserva proporcional
            for estagio, delta in deltas.items():
                if delta <= 0:
                    continue

                # Tenta liberar reserva usando o serviço de alocações
                # Nota: A liberação é feita por demanda, não por item específico
                try:
                    # Libera reserva para o item/processo
                    demanda_alocacao_estoque_service.liberar_alocacao_por_demanda(
                        demanda_id=demanda_id,
                        quantidade=float(delta),
                        motivo=f"Reconciliação Automática - Estágio {estagio}"
                    )
                except Exception as e:
                    # Loga erro mas não falha a reconciliação
                    print(f"AVISO: Erro ao liberar reserva para demanda {demanda_id}: {e}")

        except Exception as e:
            print(f"ERRO ao liberar reservas para demanda {demanda_id}: {e}")

    async def _registrar_evento_processado(self, item_id: int, demanda_id: int,
                                            estagio: str, quantidade_reportada: Decimal,
                                            quantidade_efetiva: Decimal, correlation_id: str):
        """Registra evento de produção como processado."""
        evento = {
            'item_demanda_id': item_id,
            'demanda_id': demanda_id,
            'estagio': estagio,
            'quantidade_reportada': float(quantidade_reportada),
            'quantidade_efetiva': float(quantidade_efetiva),
            'tipo_evento': 'LIQUIDACAO',
            'processado': True,
            'correlation_id': correlation_id,
            'processed_at': get_now_iso()
        }

        self.eventos_table.insert(evento).execute()

    async def _adquirir_lock_item(self, item_id: int) -> bool:
        """
        Adquire lock baseado no status do item no Supabase.
        Previne concorrência atualizando status para 'PROCESSANDO'.
        Inclui timeout para locks presos há mais de 5 minutos.
        """
        try:
            # Primeiro, verifica se está PROCESSANDO há muito tempo (timeout de 5 minutos)
            response = supabase_db.table('itens_demanda')\
                .select('id, status_processamento, updated_at')\
                .eq('id', item_id)\
                .single()\
                .execute()
            
            if response.data:
                status = response.data.get('status_processamento')
                updated_at = response.data.get('updated_at')
                
                # Se está PROCESSANDO há mais de 5 minutos, assume lock perdido e libera
                if status == 'PROCESSANDO' and updated_at:
                    from datetime import datetime, timedelta
                    try:
                        updated_dt = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                        if updated_dt < datetime.now(datetime.timezone.utc) - timedelta(minutes=5):
                            print(f"[LOCK] Timeout detectado para item {item_id}, liberando lock...")
                            supabase_db.table('itens_demanda')\
                                .update({'status_processamento': 'PENDENTE'})\
                                .eq('id', item_id)\
                                .execute()
                    except Exception as e:
                        print(f"[LOCK] Erro ao verificar timeout: {e}")
            
            # Tenta adquirir lock
            response = supabase_db.table('itens_demanda')\
                .update({'status_processamento': 'PROCESSANDO'})\
                .eq('id', item_id)\
                .neq('status_processamento', 'PROCESSANDO')\
                .execute()
            
            return len(response.data) > 0
        except Exception as e:
            print(f"ERRO ao adquirir lock para item {item_id}: {e}")
            return False

    async def _liberar_lock_item(self, item_id: int):
        """Libera o lock atualizando o status de volta para 'PROCESSADO'."""
        try:
            supabase_db.table('itens_demanda') \
                .update({'status_processamento': 'PROCESSADO'}) \
                .eq('id', item_id) \
                .execute()
        except Exception as e:
            print(f"ERRO ao liberar lock para item {item_id}: {e}")


# Singleton
motor_reconciliacao_estoque = MotorReconciliacaoEstoque()
