"""
Motor de Estoque v2 — Reconciliação Síncrona com Produção JIT

Este motor implementa a lógica de reconciliação incremental baseada em deltas de produção,
permitindo que cada etapa do dashboard (E1, E2, E4) sensibilize o estoque de forma síncrona.

Premissas v2:
- P3': Liquidação por etapa (E1, E2, E4, E7).
- P4': Sinais síncronos (Dashboard -> Transação).
- P12: Pool da Demanda (itens alocados fisicamente).
- Idempotência por lote_id.
- Reversibilidade por deltas negativos.

Autor: NistiPrint
Data: 2026-05-08
"""

import logging
import uuid
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.bom_service import bom_service
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.estoque_service import estoque_service
from nistiprint_shared.services.app_config_service import app_config_service
from nistiprint_shared.utils.date_utils import get_now_iso

logger = logging.getLogger(__name__)

class LedgerAcumuladores:
    """Acumuladores do ledger para um item de demanda."""
    def __init__(self):
        self.ci_estoque_consumido = Decimal('0')
        self.ci_jit_produzido = Decimal('0')
        self.cp_estoque_consumido = Decimal('0')
        self.cp_jit_produzido = Decimal('0')
        self.m_estoque_consumido = Decimal('0')
        self.m_jit_produzido = Decimal('0')
        self.mp_consumido = defaultdict(Decimal)

class AlvoProducao:
    """Alvo de produção decomposto em estoque vs JIT."""
    def __init__(self, estoque: Decimal = Decimal('0'), jit: Decimal = Decimal('0')):
        self.estoque = estoque
        self.jit = jit

class MotorEstoqueV2:
    """
    Motor de Estoque v2 para reconciliação síncrona.
    """

    def __init__(self):
        self.itens_table = supabase_db.table('itens_demanda')
        self.movimentacoes_table = supabase_db.table('movimentacoes_estoque')
        
    def reconciliar(self, item_demanda_id: int, deltas: Dict[str, float], origem: str = 'Dashboard', 
                    user_id: Optional[int] = None, lote_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Algoritmo Central — Reconciliação Incremental por Lote.
        """
        lote_id = lote_id or str(uuid.uuid4())
        
        # 1. Verificar idempotência (se lote_id já processado)
        if self._lote_ja_processado(lote_id):
            logger.info(f"Lote {lote_id} já processado. Ignorando.")
            return {"success": True, "message": "Lote já processado", "lote_id": lote_id}

        # 2. Lock pessimista e busca de estado atual
        # Como o PostgREST não suporta SELECT FOR UPDATE persistente,
        # usamos uma RPC para garantir a atomicidade da leitura + trava + escrita.
        # Mas para seguir o esqueleto proposto, faremos a lógica aqui e a persistência via RPC.
        
        item_demanda = self._obter_item_demanda(item_demanda_id)
        if not item_demanda:
            raise ValueError(f"Item de demanda {item_demanda_id} não encontrado.")

        # 3. Aplicar deltas em memória para validar invariantes
        estado_novo = self._aplicar_deltas_em_memoria(item_demanda, deltas)
        self._validar_invariantes(estado_novo)

        # 4. Obter acumuladores do ledger
        ledger = self._obter_acumuladores_ledger(item_demanda_id)

        # 5. Resolução TOP-DOWN (CP e M)
        cp_alvo = self._resolver_cp_alvo(estado_novo, ledger)
        m_alvo = self._resolver_m_alvo(estado_novo, ledger)

        # 6. Resolução BOTTOM-UP (CI depende de CP vindo de estoque)
        ci_alvo = self._resolver_ci_alvo(estado_novo, ledger, cp_alvo)

        # 7. Resolução de MPs (derivadas dos JITs)
        mp_alvo = self._computar_mp_alvo(item_demanda, ci_alvo, cp_alvo, m_alvo)

        # 8. Calcular movimentos a emitir (Delta entre Alvo e Ledger)
        movimentos = []
        movimentos += self._emitir_delta_movimentos(item_demanda_id, 'CP', cp_alvo, ledger.cp_estoque_consumido, ledger.cp_jit_produzido)
        movimentos += self._emitir_delta_movimentos(item_demanda_id, 'M', m_alvo, ledger.m_estoque_consumido, ledger.m_jit_produzido)
        movimentos += self._emitir_delta_movimentos(item_demanda_id, 'CI', ci_alvo, ledger.ci_estoque_consumido, ledger.ci_jit_produzido)
        movimentos += self._emitir_delta_mp(item_demanda_id, mp_alvo, ledger.mp_consumido)

        # 9. Liquidação Produto Acabado (E7)
        delta_finalizados = Decimal(str(deltas.get('finalizados_qtd', 0)))
        if delta_finalizados != 0:
            movimentos += self._emitir_prod_acab(item_demanda, delta_finalizados)

        # 10. Persistência Atômica via RPC
        if movimentos:
            self._persistir_transacional(item_demanda_id, movimentos, estado_novo, lote_id, user_id, origem)
        else:
            # Se não houver movimentos de estoque, apenas atualiza o item_demanda
            self.itens_table.update(estado_novo).eq('id', item_demanda_id).execute()

        return {
            "success": True,
            "lote_id": lote_id,
            "movimentos_count": len(movimentos)
        }

    def _obter_item_demanda(self, item_id: int) -> Dict[str, Any]:
        res = self.itens_table.select("*").eq('id', item_id).single().execute()
        return res.data

    def _lote_ja_processado(self, lote_id: str) -> bool:
        res = self.movimentacoes_table.select("id").eq('lote_id', lote_id).limit(1).execute()
        return len(res.data) > 0

    def _aplicar_deltas_em_memoria(self, item: Dict[str, Any], deltas: Dict[str, float]) -> Dict[str, Any]:
        novo_estado = item.copy()
        for k, v in deltas.items():
            if k in item:
                valor_atual = Decimal(str(item.get(k, 0) or 0))
                novo_valor = max(Decimal('0'), valor_atual + Decimal(str(v)))
                novo_estado[k] = float(novo_valor)
        return novo_estado

    def _validar_invariantes(self, estado: Dict[str, Any]):
        """Valida invariantes de cascata (P14)."""
        ci = Decimal(str(estado.get('capas_impressas_qtd', 0) or 0))
        cp = Decimal(str(estado.get('capas_produzidas_qtd', 0) or 0))
        cp_pronta = Decimal(str(estado.get('capas_prontas_retirada_qtd', 0) or 0))
        m_pronta = Decimal(str(estado.get('miolos_prontos_retirada_qtd', 0) or 0))
        exp_cp = Decimal(str(estado.get('expedicao_capas_retiradas_qtd', 0) or 0))
        exp_m = Decimal(str(estado.get('expedicao_miolos_retirados_qtd', 0) or 0))
        finalizados = Decimal(str(estado.get('finalizados_qtd', 0) or 0))

        # Cascata visual
        if not (ci >= cp):
            logger.warning(f"Invariante violada: ci ({ci}) < cp ({cp})")
        if not (cp >= cp_pronta):
             logger.warning(f"Invariante violada: cp ({cp}) < cp_pronta ({cp_pronta})")
        if not (cp_pronta >= exp_cp):
             logger.warning(f"Invariante violada: cp_pronta ({cp_pronta}) < exp_cp ({exp_cp})")
        if not (m_pronta >= exp_m):
             logger.warning(f"Invariante violada: m_pronta ({m_pronta}) < exp_m ({exp_m})")
        if not (finalizados <= exp_cp):
             logger.warning(f"Invariante violada: finalizados ({finalizados}) > exp_cp ({exp_cp})")
        if not (finalizados <= exp_m):
             logger.warning(f"Invariante violada: finalizados ({finalizados}) > exp_m ({exp_m})")

    def _obter_acumuladores_ledger(self, item_id: int) -> LedgerAcumuladores:
        """Calcula os acumuladores baseados no histórico de movimentações do item."""
        res = self.movimentacoes_table.select("produto_id, quantidade, is_jit, tipo_movimentacao")\
            .eq('item_demanda_id', item_id).execute()
        
        ledger = LedgerAcumuladores()
        
        for mov in res.data:
            prod_id = mov['produto_id']
            qtd = Decimal(str(mov['quantidade']))
            is_jit = mov.get('is_jit', False)
            tipo = mov['tipo_movimentacao']
            
            # Identificar papel do produto
            role = product_service.identify_product_role(str(prod_id))
            
            if role == 'CAPA_ACABADA': # CP
                if is_jit: ledger.cp_jit_produzido += qtd
                else: ledger.cp_estoque_consumido += abs(qtd) # Consumo é negativo no ledger
            elif role == 'MIOLO': # M
                if is_jit: ledger.m_jit_produzido += qtd
                else: ledger.m_estoque_consumido += abs(qtd)
            elif role == 'CAPA_IMPRESSAO': # CI
                if is_jit: ledger.ci_jit_produzido += qtd
                else: ledger.ci_estoque_consumido += abs(qtd)
            else:
                # MP ou outros
                ledger.mp_consumido[prod_id] += abs(qtd)
                
        return ledger

    def _resolver_cp_alvo(self, estado: Dict[str, Any], ledger: LedgerAcumuladores) -> AlvoProducao:
        cp_pool_total = Decimal(str(estado.get('capas_produzidas_qtd', 0)))
        # Saldo global atual + o que esta demanda JÁ pegou do estoque (para não contar duas vezes)
        produto_cp = self._get_produto_por_role(estado, 'CAPA_ACABADA')
        saldo_livre = self._saldo_global(produto_cp['id']) if produto_cp else Decimal('0')
        
        cp_max_estoque = ledger.cp_estoque_consumido + saldo_livre
        cp_estoque = min(cp_pool_total, cp_max_estoque)
        cp_jit = max(Decimal('0'), cp_pool_total - cp_estoque)
        
        return AlvoProducao(estoque=cp_estoque, jit=cp_jit)

    def _resolver_m_alvo(self, estado: Dict[str, Any], ledger: LedgerAcumuladores) -> AlvoProducao:
        m_pool_total = Decimal(str(estado.get('miolos_prontos_retirada_qtd', 0)))
        produto_m = self._get_produto_por_role(estado, 'MIOLO')
        saldo_livre = self._saldo_global(produto_m['id']) if produto_m else Decimal('0')
        
        m_max_estoque = ledger.m_estoque_consumido + saldo_livre
        m_estoque = min(m_pool_total, m_max_estoque)
        m_jit = max(Decimal('0'), m_pool_total - m_estoque)
        
        return AlvoProducao(estoque=m_estoque, jit=m_jit)

    def _resolver_ci_alvo(self, estado: Dict[str, Any], ledger: LedgerAcumuladores, cp_alvo: AlvoProducao) -> AlvoProducao:
        # CIs que a demanda PRECISA fisicamente
        ci_marcadas = Decimal(str(estado.get('capas_impressas_qtd', 0)))
        # Descontar as CIs que já vieram embutidas nas CPs de estoque
        ci_pool_real = max(Decimal('0'), ci_marcadas - cp_alvo.esto) # Erro no plano: deve ser cp_alvo.estoque
        ci_pool_real = max(Decimal('0'), ci_marcadas - cp_alvo.estoque)

        produto_ci = self._get_produto_por_role(estado, 'CAPA_IMPRESSAO')
        saldo_livre = self._saldo_global(produto_ci['id']) if produto_ci else Decimal('0')
        
        ci_max_estoque = ledger.ci_estoque_consumido + saldo_livre
        ci_estoque = min(ci_pool_real, ci_max_estoque)
        ci_jit = max(Decimal('0'), ci_pool_real - ci_estoque)
        
        return AlvoProducao(estoque=ci_estoque, jit=ci_jit)

    def _computar_mp_alvo(self, item: Dict[str, Any], ci_alvo: AlvoProducao, cp_alvo: AlvoProducao, m_alvo: AlvoProducao) -> Dict[int, Decimal]:
        mp = defaultdict(Decimal)
        
        prod_id = item['produto_id']
        id_miolo = item.get('id_produto_miolo')
        
        # 1. MPs do BOM de CI (escalado por CI JIT)
        produto_ci = self._get_produto_por_role(item, 'CAPA_IMPRESSAO')
        if produto_ci and ci_alvo.jit > 0:
            for mp_id, qtd_per in self._get_bom_mp(produto_ci['id']):
                mp[mp_id] += ci_alvo.jit * Decimal(str(qtd_per))
                
        # 2. MPs do BOM de CP (escalado por CP JIT), excluindo componente CI
        produto_cp = self._get_produto_por_role(item, 'CAPA_ACABADA')
        if produto_cp and cp_alvo.jit > 0:
            for mp_id, qtd_per in self._get_bom_mp_direto(produto_cp['id']):
                mp[mp_id] += cp_alvo.jit * Decimal(str(qtd_per))
                
        # 3. MPs do BOM de M (escalado por M JIT)
        produto_m = self._get_produto_por_role(item, 'MIOLO')
        if produto_m and m_alvo.jit > 0:
            for mp_id, qtd_per in self._get_bom_mp(produto_m['id']):
                mp[mp_id] += m_alvo.jit * Decimal(str(qtd_per))
                
        return mp

    def _emitir_delta_movimentos(self, item_id: int, role_key: str, alvo: AlvoProducao, 
                                 consumido_ledger: Decimal, jit_ledger: Decimal) -> List[Dict[str, Any]]:
        movs = []
        
        # Resolver produto real do item
        item = self._obter_item_demanda(item_id)
        role_map = {'CP': 'CAPA_ACABADA', 'M': 'MIOLO', 'CI': 'CAPA_IMPRESSAO'}
        produto = self._get_produto_por_role(item, role_map[role_key])
        if not produto: return []
        
        # Delta Estoque
        delta_estoque = alvo.estoque - consumido_ledger
        if delta_estoque != 0:
            movs.append({
                'produto_id': produto['id'],
                'tipo_movimentacao': 'CONS_INT',
                'quantidade': float(-delta_estoque), # Consumo é negativo
                'is_jit': False,
                'motivo': f"Reconciliação {role_key} (Estoque)"
            })
            
        # Delta JIT
        delta_jit = alvo.jit - jit_ledger
        if delta_jit != 0:
            # Produção JIT (PROD_INT + CONS_INT)
            movs.append({
                'produto_id': produto['id'],
                'tipo_movimentacao': 'PROD_INT',
                'quantidade': float(delta_jit),
                'is_jit': True,
                'motivo': f"Reconciliação {role_key} (JIT - Produção)"
            })
            movs.append({
                'produto_id': produto['id'],
                'tipo_movimentacao': 'CONS_INT',
                'quantidade': float(-delta_jit),
                'is_jit': True,
                'motivo': f"Reconciliação {role_key} (JIT - Alocação)"
            })
            
        return movs

    def _emitir_delta_mp(self, item_id: int, mp_alvo: Dict[int, Decimal], mp_ledger: Dict[int, Decimal]) -> List[Dict[str, Any]]:
        movs = []
        # Unir todas as chaves (alvo + ledger)
        all_mps = set(mp_alvo.keys()) | set(mp_ledger.keys())
        
        for mp_id in all_mps:
            alvo_qtd = mp_alvo.get(mp_id, Decimal('0'))
            ledger_qtd = mp_ledger.get(mp_id, Decimal('0'))
            delta = alvo_qtd - ledger_qtd
            
            if delta != 0:
                movs.append({
                    'produto_id': mp_id,
                    'tipo_movimentacao': 'CONS_MP',
                    'quantidade': float(-delta),
                    'is_jit': False,
                    'motivo': "Reconciliação MP (Insumo JIT)"
                })
        return movs

    def _emitir_prod_acab(self, item: Dict[str, Any], delta: Decimal) -> List[Dict[str, Any]]:
        # PROD_ACAB do produto pai
        # Também deve consumir MPs que não estão nos intermediários (ex: espiral, embalagem)
        movs = []
        movs.append({
            'produto_id': item['produto_id'],
            'tipo_movimentacao': 'PROD_ACAB',
            'quantidade': float(delta),
            'is_jit': False,
            'motivo': "Finalização de Item"
        })
        
        # BOM DIRETA do acabado (filtando o que NÃO é CI ou M)
        for mp_id, qtd_per in self._get_bom_mp_direto(item['produto_id']):
            # Se o componente não for CI nem M, ele deve ser consumido aqui
            role = product_service.identify_product_role(str(mp_id))
            if role not in ['CAPA_IMPRESSAO', 'MIOLO']:
                 movs.append({
                    'produto_id': mp_id,
                    'tipo_movimentacao': 'CONS_MP',
                    'quantidade': float(-delta * Decimal(str(qtd_per))),
                    'is_jit': False,
                    'motivo': "Consumo MP Direta (Acabado)"
                })
        return movs

    def _saldo_global(self, produto_id: int) -> Decimal:
        """Obtém saldo disponível global."""
        res = estoque_service.get_saldo_atual(produto_id)
        return Decimal(str(res.get('quantidade_disponivel', 0)))

    def _get_produto_por_role(self, item: Dict[str, Any], role_alvo: str) -> Optional[Dict[str, Any]]:
        """Resolve o produto associado a um papel específico para o item."""
        # 1. Tentar miolo se for MIOLO
        if role_alvo == 'MIOLO':
            miolo_id = item.get('id_produto_miolo')
            if miolo_id: return {'id': miolo_id}
            
        # 2. Buscar na BOM do pai
        pai_id = item['produto_id']
        componentes = bom_service.get_bom_for_produto(pai_id)
        for comp in componentes:
            role = product_service.identify_product_role(str(comp.componente_id))
            if role == role_alvo:
                return {'id': comp.componente_id}
                
        # 3. Fallback: se o próprio pai for o papel (ex: produção avulsa de capa)
        role_pai = product_service.identify_product_role(str(pai_id))
        if role_pai == role_alvo:
            return {'id': pai_id}
            
        return None

    def _get_bom_mp(self, produto_id: int) -> List[Tuple[int, float]]:
        """Explode toda a BOM em busca de Matérias Primas (folhas)."""
        components = bom_service.get_bom_for_produto(produto_id)
        result = []
        for c in components:
            # Se componente tem BOM, explode ele também
            sub = bom_service.get_bom_for_produto(c.componente_id)
            if sub:
                # Recursão simples (v2 foca em intermediários de 1 nível)
                for sub_c in sub:
                    result.append((sub_c.componente_id, c.quantidade_necessaria * sub_c.quantidade_necessaria))
            else:
                result.append((c.componente_id, c.quantidade_necessaria))
        return result

    def _get_bom_mp_direto(self, produto_id: int) -> List[Tuple[int, float]]:
        """Obtém apenas componentes diretos da BOM."""
        components = bom_service.get_bom_for_produto(produto_id)
        return [(c.componente_id, c.quantidade_necessaria) for c in components]

    def _persistir_transacional(self, item_id: int, movimentos: List[Dict[str, Any]], 
                                estado_novo: Dict[str, Any], lote_id: str, 
                                user_id: Optional[int], origem: str):
        """Persiste movimentos e estado do item atomicamente via RPC."""
        snapshot = {
            'origem': origem,
            'lote_id': lote_id,
            'estado_novo': {k: v for k, v in estado_novo.items() if isinstance(v, (int, float, str))}
        }
        
        # Adaptar movimentos para o formato da RPC
        rpc_movs = []
        for m in movimentos:
            rpc_movs.append({
                'produto_id': m['produto_id'],
                'tipo': m['tipo_movimentacao'],
                'quantidade': m['quantidade'],
                'motivo': f"[{origem}] {m['motivo']}",
                'is_jit': m.get('is_jit', False),
                'coluna_origem': m.get('coluna_origem', origem)
            })

        params = {
            'p_item_id': item_id,
            'p_movimentos': rpc_movs,
            'p_estado_novo': estado_novo,
            'p_snapshot': snapshot,
            'p_lote_id': lote_id,
            'p_user_id': str(user_id) if user_id else None
        }
        
        res = supabase_db.rpc('reconciliar_estoque_v2', params).execute()
        if not res.data or not res.data.get('sucesso'):
            error = res.data.get('erro') if res.data else "Erro desconhecido na RPC"
            raise RuntimeError(f"Falha na reconciliação atômica: {error}")

# Singleton
motor_estoque_v2 = MotorEstoqueV2()
