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
from contextvars import ContextVar
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

_BOM_EXECUTION_VERSION: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    'bom_execution_version', default=None
)


# ============================================================
# DATA CLASSES
# ============================================================

class IntencaoItem:
    """Representa a intenção de produção reportada pelo usuário."""
    def __init__(self, item: Dict[str, Any]):
        self.item_id = item.get('id')
        self.demanda_id = item.get('demanda_id')
        self.produto_id = item.get('produto_id')
        self.demanda_total = Decimal(str(item.get('quantidade', 0) or 0))
        self.bom_version_id = item.get('bom_version_id')

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
                 saldo_acumulado: Decimal = Decimal('0'),
                 expected_saldo: Optional[Decimal] = None,
                 expected_reservado: Optional[Decimal] = None,
                 expected_reserva_propria: Optional[Decimal] = None,
                 expected_disponivel: Optional[Decimal] = None):
        self.produto_id = produto_id
        self.tipo = tipo
        self.quantidade = quantidade
        self.motivo = motivo
        self.estagio = estagio
        self.deposito_id = deposito_id  # Novo: depósito explícito
        self.saldo_acumulado = saldo_acumulado
        self.expected_saldo = expected_saldo
        self.expected_reservado = expected_reservado
        self.expected_reserva_propria = expected_reserva_propria
        self.expected_disponivel = expected_disponivel


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


def _normalizar_produto_id(produto_id: Any) -> Optional[int]:
    """Converte IDs de produto para int e rejeita valores nulos serializados."""
    if produto_id is None:
        return None

    if isinstance(produto_id, str):
        produto_id = produto_id.strip()
        if not produto_id or produto_id.lower() in {'none', 'null', 'undefined'}:
            return None

    try:
        return int(produto_id)
    except (TypeError, ValueError):
        return None


# ============================================================
# MOTOR DE RECONCILIAÇÃO
# ============================================================

class MotorReconciliacaoEstoque:
    """
    Motor determinístico de reconciliação de estoque.
    Implementa lógica waterfall top-down com produção compensatória.
    """

    def __init__(self):
        # O ledger e escrito pela RPC reconciliar_item_estoque, que insere em
        # demanda_estoque_processado uma linha por movimento (com ON CONFLICT
        # de idempotencia). _ler_ledger_item le dessa mesma tabela.
        self.ledger_table = supabase_db.table('demanda_estoque_processado')
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

    async def reconcile_item(self, item_id: int, demanda_id: int, user_id: str = 'System',
                             acquire_lock: bool = True, correlation_id: Optional[str] = None,
                             operation_id: Optional[str] = None,
                             lease: Optional[Dict[str, Any]] = None) -> ReconciliacaoResultado:
        """
        Orquestra reconciliação completa de um item.
        Chamado APENAS na finalização (E7).

        Args:
            item_id: ID do item de demanda
            demanda_id: ID da demanda de produção
            user_id: ID do usuário que disparou a reconciliação
            acquire_lock: Se True (default), o motor adquire/libera o lock no
                campo itens_demanda.status_processamento. Quando o caller (ex:
                ConsolidadorDeEstoque) ja gerencia o lock, deve passar False
                para evitar double-lock — o motor encontraria PROCESSANDO posto
                pelo proprio caller e desistiria com erro espurio.

        Returns:
            ReconciliacaoResultado com detalhes das movimentações.
        """
        correlation_id = str(correlation_id or uuid.uuid4())

        lease_is_valid = bool(
            operation_id
            and lease
            and lease.get('worker_id')
            and lease.get('lease_token')
            and lease.get('event_ids')
        )
        if not lease_is_valid:
            return ReconciliacaoResultado(
                sucesso=False,
                item_id=item_id,
                demanda_id=demanda_id,
                correlation_id=correlation_id,
                erros=['Reconciliação exige operação estável e lease válido de eventos.'],
            )

        try:
            # 1. Adquirir lock para prevenir concorrência (apenas se o caller
            #    nao gerenciar o lock externamente).
            if acquire_lock:
                lock_adquirido = await self._adquirir_lock_item(item_id)
                if not lock_adquirido:
                    return ReconciliacaoResultado(
                        sucesso=False,
                        item_id=item_id,
                        demanda_id=demanda_id,
                        correlation_id=correlation_id,
                        erros=['Item já está sendo processado por outra transação']
                    )

            bom_context_token = None
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

                if intencao.produto_id:
                    bom_version = self._get_or_pin_bom_version(item_id, intencao)
                    bom_context_token = _BOM_EXECUTION_VERSION.set(bom_version)

                # 3. Calcular quantidades efetivas (waterfall top-down)
                efetivas = await self._calcular_quantidades_efetivas(intencao)

                # 4. Ler realizado (ledger)
                realizado = await self._ler_ledger_item(item_id)

                # 5. Calcular deltas
                deltas = await self._calcular_deltas(efetivas, realizado)

                # 6. Processar deltas em transação única via RPC
                resultado = await self._processar_deltas_transacional(
                    item_id, demanda_id, deltas, efetivas, intencao, realizado, user_id, correlation_id,
                    operation_id=operation_id, lease=lease,
                )

                # O registro no ledger ja foi feito dentro da RPC
                # reconciliar_item_estoque (uma linha por movimento em
                # demanda_estoque_processado). Nao ha passo adicional aqui.
                return resultado

            finally:
                if bom_context_token is not None:
                    _BOM_EXECUTION_VERSION.reset(bom_context_token)
                # Liberar lock apenas se o motor o adquiriu nesta chamada.
                if acquire_lock:
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

    async def _ler_intencao_item(self, item_id: int) -> Optional[IntencaoItem]:
        """Lê o estado visual atual do item (valores reportados)."""
        response = supabase_db.table('itens_demanda')\
            .select('*')\
            .eq('id', item_id)\
            .execute()

        if not response.data:
            return None

        return IntencaoItem(response.data[0])

    def _get_or_pin_bom_version(self, item_id: int, intencao: IntencaoItem) -> Dict[str, Any]:
        """Fixa a primeira BOM efetiva no item e reutiliza a versão em retentativas."""
        if intencao.bom_version_id:
            return bom_service.get_version(intencao.bom_version_id)

        candidate = bom_service.publish_effective_version(int(intencao.produto_id))
        supabase_db.table('itens_demanda').update({
            'bom_version_id': candidate['id'],
        }).eq('id', item_id).is_('bom_version_id', 'null').execute()

        saved = supabase_db.table('itens_demanda').select('bom_version_id').eq(
            'id', item_id
        ).limit(1).execute().data or []
        if not saved or not saved[0].get('bom_version_id'):
            raise RuntimeError(f'BOM_VERSION_PIN_FAILED:item={item_id}')
        intencao.bom_version_id = saved[0]['bom_version_id']
        return bom_service.get_version(intencao.bom_version_id)

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
        """Lê checkpoints confirmados; soma física mistura itens/unidades."""
        response = supabase_db.table('snapshots_reconciliacao')\
            .select('payload')\
            .eq('item_id', item_id)\
            .order('created_at', desc=True)\
            .limit(1)\
            .execute()
        rows = response.data or []
        if not rows:
            return {}
        checkpoints = (rows[0].get('payload') or {}).get('efetivas_confirmadas') or {}
        return {key: Decimal(str(value or 0)) for key, value in checkpoints.items()}

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

            if delta < Decimal('-0.001'):
                raise ValueError(f'RECONCILIACAO_REDUCAO_REQUER_COMPENSACAO:{estagio}:{delta}')
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
        correlation_id: str,
        operation_id: Optional[str] = None,
        lease: Optional[Dict[str, Any]] = None,
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
            produto_pai_id = _normalizar_produto_id(response.data[0].get('produto_id'))
            if produto_pai_id is None:
                return ReconciliacaoResultado(
                    True,
                    item_id,
                    demanda_id,
                    correlation_id,
                    metadata={'ignored': True, 'reason': 'item_sem_produto_mapeado'}
                )

            # IMPORTANTE: quando ha delta em finalizados_qtd, este eh o UNICO
            # estagio que deve gerar movimentos. Os demais estagios (E1-E6)
            # ganham valor visual via cascata feita em finalizar_item/
            # finalizar_item_parcial, mas NAO sao consumos independentes —
            # representam apenas o avanco visual da producao do mesmo item.
            # A producao fisica (PROD_ACAB do produto pai + BOM recursiva
            # com PROD_INT/CONS_INT/CONS_MP de capa pronta, miolo, MPs) ja
            # cobre todos os componentes necessarios. Processar os estagios
            # intermediarios produziria multiplos PROD_INT do mesmo produto
            # (uma vez por estagio + uma vez na recursao da BOM), inflando
            # 1 caderno em ~9 miolos + 8 capas e por ai vai.
            if deltas.get('finalizados_qtd', Decimal('0')) > Decimal('0'):
                deltas = {'finalizados_qtd': deltas['finalizados_qtd']}

            # Processar cada estágio com delta
            for estagio, delta in deltas.items():
                # Identificar produtos associados ao estágio
                produtos_ids = await self._get_produtos_por_estagio(item_id, estagio, produto_pai_id)

                if not produtos_ids:
                    # Estágio sem produto associado (ex: administrativo)
                    continue

                for produto_id in produtos_ids:
                    produto_id = _normalizar_produto_id(produto_id)
                    if produto_id is None:
                        continue

                    # Obter tipo do produto
                    tipo_produto = await self._get_tipo_produto(produto_id)

                    # Regra (B5): tudo que NAO e materia-prima debita em cascata.
                    # Havendo saldo do proprio produto, consome; faltando, produz
                    # JIT e explode a BOM — de modo que o consumo real recai sobre
                    # as materias-primas, as unicas que podem ficar negativas.
                    #
                    # Antes o discriminador era "tem ficha tecnica", nao "e
                    # materia-prima". Nos dados as duas coisas quase coincidem,
                    # mas divergem em 9 intermediarios sem BOM e 1 servico: esses
                    # eram consumidos como se fossem insumo e podiam negativar,
                    # contra a regra. Agora viram erro de cadastro, visivel.
                    componentes_bom = await self._get_componentes_bom(produto_id)
                    tem_bom = len(componentes_bom) > 0
                    eh_materia_prima = (tipo_produto or '').upper() == 'MATERIA_PRIMA'

                    if (tipo_produto or '').upper() == 'SERVICO':
                        # Servico nao movimenta estoque em nenhuma hipotese.
                        continue

                    if not eh_materia_prima and not tem_bom:
                        erros.append(
                            f"Produto {produto_id} e {tipo_produto} sem ficha tecnica: "
                            f"nao ha o que debitar em cascata. Cadastre a BOM ou "
                            f"reclassifique o produto."
                        )
                        continue

                    if tem_bom:
                        # Produto com BOM (Intermediário ou Acabado): NUNCA fica negativo
                        saldo_info = await self._get_saldo_disponivel(produto_id, item_id, deposito_padrao)
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
                            # Explode BOM para consumir intermediários/MPs do acabado.
                            # Passa estagio_pai=estagio para que componentes consumidos
                            # do estoque fiquem no MESMO bloco do PROD_ACAB na view
                            # consolidada (somente JITs abrem sub-blocos jit_<comp_id>).
                            movimentos_bom = await self._explodir_bom_consumo(
                                produto_id, delta, demanda_id, user_id, deposito_padrao,
                                estagio_pai=estagio, item_id=item_id,
                            )
                            movimentos.extend(movimentos_bom)
                        else:
                            # Estágios de CONSUMO de intermediário
                            # A disponibilidade negativa é déficit preexistente,
                            # não quantidade consumível. Só MP pode carregar esse déficit.
                            qtd_usar_estoque = max(Decimal('0'), min(saldo_disponivel, delta))
                            qtd_faltante = delta - qtd_usar_estoque
                            inicio_movimentos_produto = len(movimentos)

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

                            # 2. Faltante: produz JIT, consome espelhado e explode BOM.
                            # Toda a sub-arvore JIT (PROD_INT + CONS_INT espelhado +
                            # filhos da BOM) compartilha o estagio jit_<produto_id>
                            # para que a view consolidada mostre um bloco unico
                            # "Produção JIT de N x <produto>" com seus insumos dentro.
                            if qtd_faltante > 0:
                                estagio_jit = f'jit_{produto_id}'
                                # 2.a Entrada virtual JIT
                                movimentos.append(Movimento(
                                    produto_id=produto_id,
                                    tipo='PROD_INT',
                                    quantidade=+qtd_faltante,
                                    motivo=f'Auto-produção JIT {estagio} demanda {demanda_id}',
                                    estagio=estagio_jit,
                                    deposito_id=deposito_padrao
                                ))
                                # 2.b Saída espelhada (esse JIT só existe pra alocação à demanda)
                                movimentos.append(Movimento(
                                    produto_id=produto_id,
                                    tipo='CONS_INT',
                                    quantidade=-qtd_faltante,
                                    motivo=f'Consumo JIT {estagio} demanda {demanda_id}',
                                    estagio=estagio_jit,
                                    deposito_id=deposito_padrao
                                ))
                                # 2.c Recursão: filhos da BOM do JIT herdam o sub-bloco.
                                movimentos_bom = await self._explodir_bom_consumo(
                                    produto_id, qtd_faltante, demanda_id, user_id, deposito_padrao,
                                    estagio_pai=estagio_jit, item_id=item_id,
                                )
                                movimentos.extend(movimentos_bom)

                            self._anexar_precondicao_saldo(
                                movimentos[inicio_movimentos_produto:], produto_id, saldo_info
                            )

                    else:
                        # Materia-prima sem BOM: consome direto e pode ir negativo.
                        # E o unico caso em que o saldo negativo e esperado.
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
            snapshot['efetivas_confirmadas'] = snapshot['efetivas_calculadas']
            bom_version = _BOM_EXECUTION_VERSION.get()
            if bom_version:
                snapshot['bom_version_id'] = bom_version['id']
                snapshot['bom_version_hash'] = bom_version['content_hash']

            # Persistir TUDO atomicamente via RPC
            resultado_rpc = await self._persistir_via_rpc(
                movimentos, item_id, demanda_id, correlation_id, user_id, snapshot,
                operation_id=operation_id, lease=lease,
            )

            if not resultado_rpc.sucesso:
                return resultado_rpc

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
        max_profundidade: int = 10,
        estagio_pai: Optional[str] = None,
        _path: Optional[List[int]] = None,
        item_id: Optional[int] = None,
    ) -> List[Movimento]:
        """
        Explosão recursiva de BOM para produção compensatória.

        Estrategia de "estagio" para agrupamento na UI:
            - CONS_INT/CONS_MP de componentes consumidos do estoque ficam no
              estagio do BLOCO PAI (estagio_pai). Se nao houver pai (chamada
              de finalizados_qtd), usa f'bom_{produto_id}'.
            - PROD_INT JIT, CONS_INT espelhado e os recursivos abrem um
              SUB-BLOCO proprio: f'jit_{comp_id}'. Assim cada produto JIT
              vira uma linha distinta na view consolidada.

        Exemplo (Caderno = Capa Pronta + Miolo, ambos JIT):
            - estagio finalizados_qtd : PROD_ACAB Caderno + CONS_INT Capa Pronta
                                        + CONS_INT Miolo (do "bloco direto")
            - estagio jit_capa_pronta : PROD_INT Capa Pronta, CONS_INT espelhado
                                        Capa Pronta, e seus filhos (CONS_INT/MP)
            - estagio jit_miolo       : analogo para Miolo
        """
        if profundidade >= max_profundidade:
            raise ValueError(f'BOM_DEPTH_LIMIT: produto={produto_id} profundidade={profundidade}')

        path = list(_path or [])
        if produto_id in path:
            cycle = path[path.index(produto_id):] + [produto_id]
            raise ValueError('BOM_CYCLE: ' + ' -> '.join(map(str, cycle)))
        path.append(produto_id)

        movimentos: List[Movimento] = []

        # Estagio do bloco "atual" (onde caem os CONS_INT/CONS_MP diretos):
        # se foi chamado a partir do alvo da reconciliacao (estagio_pai None),
        # usa "bom_<produto_id>"; senao, usa o estagio_pai.
        estagio_corrente = estagio_pai or f'bom_{produto_id}'

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

            # Regra (B5), agora tambem na recursao: intermediario sem ficha
            # tecnica nao pode ser tratado como insumo. Levanta erro pelo mesmo
            # motivo do bloco acima — e defeito de cadastro, nao de operacao.
            if (tipo_componente or '').upper() not in ('MATERIA_PRIMA', 'SERVICO') and not tem_bom:
                raise ValueError(
                    f"BOM incompleta: componente {comp_id} e {tipo_componente} "
                    f"sem ficha tecnica propria, dentro da BOM de {produto_id}."
                )
            if (tipo_componente or '').upper() == 'SERVICO':
                continue

            if tem_bom:
                # Produto tem BOM: prioriza estoque e produz recursivamente se faltar.
                saldo_info = await self._get_saldo_disponivel(comp_id, item_id, deposito_padrao)
                saldo_disponivel = Decimal(str(saldo_info.get('quantidade_disponivel', 0) or 0))

                qtd_usar_estoque = max(Decimal('0'), min(saldo_disponivel, qtd_necessaria))
                qtd_faltante = qtd_necessaria - qtd_usar_estoque
                inicio_movimentos_componente = len(movimentos)

                # Consumo do estoque cai no BLOCO PAI (estagio_corrente).
                if qtd_usar_estoque > 0:
                    movimentos.append(Movimento(
                        produto_id=comp_id,
                        tipo='CONS_INT',
                        quantidade=-qtd_usar_estoque,
                        motivo=f'Consumo componente para produção {produto_id} demanda {demanda_id}',
                        estagio=estagio_corrente,
                        deposito_id=deposito_padrao
                    ))

                # Falta -> abre SUB-BLOCO proprio do JIT do componente.
                if qtd_faltante > 0:
                    estagio_jit = f'jit_{comp_id}'

                    # 1. PROD_INT JIT
                    movimentos.append(Movimento(
                        produto_id=comp_id,
                        tipo='PROD_INT',
                        quantidade=+qtd_faltante,
                        motivo=f'Auto-produção JIT {comp_id} para {produto_id} demanda {demanda_id}',
                        estagio=estagio_jit,
                        deposito_id=deposito_padrao
                    ))

                    # 2. CONS_INT espelhado (JIT eh consumido imediatamente para virar o pai)
                    movimentos.append(Movimento(
                        produto_id=comp_id,
                        tipo='CONS_INT',
                        quantidade=-qtd_faltante,
                        motivo=f'Consumo JIT de {comp_id} para produção {produto_id} demanda {demanda_id}',
                        estagio=estagio_jit,
                        deposito_id=deposito_padrao
                    ))

                    # 3. Recursao: filhos da BOM do JIT compartilham o mesmo
                    # sub-bloco (estagio_jit), permanecendo agrupados na UI.
                    movimentos_rec = await self._explodir_bom_consumo(
                        comp_id, qtd_faltante, demanda_id, user_id, deposito_padrao,
                        profundidade + 1, max_profundidade,
                        estagio_pai=estagio_jit,
                        _path=path,
                        item_id=item_id,
                    )
                    movimentos.extend(movimentos_rec)

                self._anexar_precondicao_saldo(
                    movimentos[inicio_movimentos_componente:], comp_id, saldo_info
                )

            else:
                # Materia-prima / folha: consome no BLOCO PAI (estagio_corrente).
                movimentos.append(Movimento(
                    produto_id=comp_id,
                    tipo='CONS_MP',
                    quantidade=-qtd_necessaria,
                    motivo=f'Consumo componente folha {comp_id} para produção {produto_id} demanda {demanda_id}',
                    estagio=estagio_corrente,
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
            produto_pai_id = _normalizar_produto_id(response.data[0].get('produto_id'))

        produto_pai_id = _normalizar_produto_id(produto_pai_id)
        if produto_pai_id is None:
            return []

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
            comp_id = _normalizar_produto_id(comp.get('componente_id'))
            if comp_id is None:
                continue
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
        """
        Tipo do produto: MATERIA_PRIMA, INTERMEDIARIO, PRODUTO_ACABADO ou SERVICO.

        O default de produto desconhecido e DESCONHECIDO, nao MATERIA_PRIMA.
        Sob a regra B5, assumir materia-prima faria um produto que nem existe
        ser consumido direto e negativar em silencio.
        """
        produto_id = _normalizar_produto_id(produto_id)
        if produto_id is None:
            return 'DESCONHECIDO'

        response = self.produtos_table\
            .select('tipo_produto')\
            .eq('id', produto_id)\
            .execute()

        if not response.data:
            return 'DESCONHECIDO'

        return response.data[0].get('tipo_produto') or 'DESCONHECIDO'

    async def _get_componentes_bom(self, produto_id: int) -> List[Dict[str, Any]]:
        """Obtém componentes da BOM de um produto."""
        produto_id = _normalizar_produto_id(produto_id)
        if produto_id is None:
            return []

        version = _BOM_EXECUTION_VERSION.get()
        if version:
            node = (version.get('graph') or {}).get('nodes', {}).get(str(produto_id)) or {}
            return list(node.get('componentes') or [])

        componentes = bom_service.get_bom_for_produto(produto_id)
        return [{
            'componente_id': row.componente_id,
            'quantidade_necessaria': row.quantidade,
            'unidade_medida': row.unit,
            'is_inherited': row.is_inherited,
            'grupo': row.group,
            'line_id': row.line_id,
        } for row in componentes]

    async def _get_saldo_disponivel(self, produto_id: int, item_id: Optional[int] = None,
                                    deposito_id: Optional[int] = None) -> Dict[str, Any]:
        """Obtém saldo disponível de um produto."""
        produto_id = _normalizar_produto_id(produto_id)
        if produto_id is None:
            return {'quantidade_disponivel': 0}

        result = estoque_service.get_saldo_atual(produto_id, deposito_id)
        if item_id is not None:
            allocated_query = supabase_db.table('demanda_alocacoes_estoque')\
                .select('quantidade_alocada,quantidade_consumida,quantidade_liberada')\
                .eq('item_id', str(item_id))\
                .eq('produto_id', str(produto_id))\
                .eq('status', 'PENDENTE')
            deposito_resolvido = result.get('deposito_id') or deposito_id
            if deposito_resolvido is not None:
                allocated_query = allocated_query.eq('deposito_id', int(deposito_resolvido))
            allocated = allocated_query.execute()
            own_reserved = sum(
                max(Decimal('0'), Decimal(str(r.get('quantidade_alocada') or 0))
                    - Decimal(str(r.get('quantidade_consumida') or 0))
                    - Decimal(str(r.get('quantidade_liberada') or 0)))
                for r in (allocated.data or [])
            )
            result = dict(result or {})
            result['reserva_propria'] = own_reserved
            result['quantidade_disponivel'] = Decimal(str(result.get('quantidade_disponivel', 0) or 0)) + own_reserved
        return result

    @staticmethod
    def _anexar_precondicao_saldo(movimentos: List[Movimento], produto_id: int,
                                  saldo_info: Dict[str, Any]) -> None:
        """Marca todas as pernas do produto com a fotografia usada na decisão JIT."""
        produto_movimentos = [m for m in movimentos if int(m.produto_id) == int(produto_id)]
        if not produto_movimentos:
            raise RuntimeError(f'JIT_STOCK_GUARD_MISSING_MOVEMENT:produto={produto_id}')
        for movimento in produto_movimentos:
            movimento.expected_saldo = Decimal(str(saldo_info.get('quantidade', 0) or 0))
            movimento.expected_reservado = Decimal(str(saldo_info.get('quantidade_reservada', 0) or 0))
            movimento.expected_reserva_propria = Decimal(str(saldo_info.get('reserva_propria', 0) or 0))
            movimento.expected_disponivel = Decimal(str(saldo_info.get('quantidade_disponivel', 0) or 0))

    async def _persistir_via_rpc(self,
                                  movimentos: List[Movimento],
                                  item_id: int,
                                  demanda_id: int,
                                  correlation_id: str,
                                  user_id: str,
                                  snapshot: Dict[str, Any], operation_id: Optional[str] = None,
                                  lease: Optional[Dict[str, Any]] = None) -> ReconciliacaoResultado:
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
            if m.expected_saldo is not None:
                mov_json[-1].update({
                    'expected_saldo': str(m.expected_saldo),
                    'expected_reservado': str(m.expected_reservado or 0),
                    'expected_reserva_propria': str(m.expected_reserva_propria or 0),
                    'expected_disponivel': str(m.expected_disponivel or 0),
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

            if not operation_id or not lease:
                raise ValueError('Reconciliação sem lease ou operation_id estável foi bloqueada.')
            import hashlib
            import json
            content = json.dumps({
                'item_id': item_id,
                'event_ids': sorted(lease['event_ids']),
                'operation_id': operation_id,
            }, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
            params = {
                'p_operation_id': operation_id,
                'p_content_hash': hashlib.sha256(content.encode('utf-8')).hexdigest(),
                'p_item_id': item_id,
                'p_demanda_id': demanda_id,
                'p_movimentos': mov_json,
                'p_snapshot': snapshot,
                'p_correlation_id': correlation_id,
                'p_user_id': user_id,
                'p_worker_id': lease['worker_id'],
                'p_lease_token': lease['lease_token'],
                'p_event_ids': lease['event_ids'],
            }
            response = supabase_db.rpc('confirmar_reconciliacao_producao', params).execute()

            data = response.data
            if isinstance(data, list):
                data = data[0] if data else None

            if not data or not data.get('sucesso'):
                erro_msg = data.get('erro') if data else "Erro desconhecido na RPC"
                raise Exception(f"Falha na RPC de reconciliação: {erro_msg}")

            # 3. Sucesso!
            return ReconciliacaoResultado(
                sucesso=True,
                item_id=item_id,
                demanda_id=demanda_id,
                correlation_id=correlation_id,
                movimentos=movimentos,
                metadata={
                    'rpc_response': data,
                    'snapshot_id': data.get('snapshot_id')
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

                # Se está PROCESSANDO há mais de 5 minutos, assume lock perdido e libera.
                # IMPORTANTE: o nome `timezone` precisa ser importado diretamente do módulo
                # `datetime` — `datetime.timezone.utc` falha porque `datetime` aqui é a
                # CLASSE datetime.datetime (que não tem o atributo `timezone`).
                if status == 'PROCESSANDO' and updated_at:
                    from datetime import datetime, timedelta, timezone
                    try:
                        # Aceita formato ISO com 'Z' ou com offset numérico
                        iso_str = updated_at.replace('Z', '+00:00') if isinstance(updated_at, str) else str(updated_at)
                        updated_dt = datetime.fromisoformat(iso_str)
                        # Se o timestamp veio sem timezone, assume UTC para comparar
                        if updated_dt.tzinfo is None:
                            updated_dt = updated_dt.replace(tzinfo=timezone.utc)
                        if updated_dt < datetime.now(timezone.utc) - timedelta(minutes=5):
                            print(f"[LOCK] Timeout detectado para item {item_id} (preso desde {updated_at}), liberando lock...")
                            supabase_db.table('itens_demanda')\
                                .update({'status_processamento': 'PENDENTE'})\
                                .eq('id', item_id)\
                                .execute()
                    except Exception as e:
                        print(f"[LOCK] Erro ao verificar timeout do item {item_id}: {e}")

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
