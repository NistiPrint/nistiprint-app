# ===========================================
# CLASSIFICAÇÃO E CONSOLIDAÇÃO AUTOMÁTICA DE PEDIDOS
# ===========================================
# Quando um novo pedido é importado via webhook Bling:
#   1. Classifica o pedido em um grupo de consolidação existente
#   2. Consolida os itens do pedido na demanda
#   3. Vincula pedido → demanda via pivot
# Se nenhum grupo existe → cria nova demanda RASCUNHO
# ===========================================

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional
import sys
import os

from celery_config import celery_app
from nistiprint_shared.services.correlation_service import with_correlation

# Adicionar diretório do worker ao path para importar task_logger
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from task_logger import log_task_execution

# ============================================================
# PREFIXO DE LOG — identificável nos logs do container
# ============================================================
_LOG_PREFIX = "[WORKER:CONSOLID]"

def _log(level: str, msg: str, **kw):
    """Log padronizado com prefixo identificável."""
    tag = f"{_LOG_PREFIX}[{level}]"
    ts = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3))).strftime("%H:%M:%S")
    parts = [f"{ts} {tag}", msg]
    if kw:
        parts.append(str(kw))
    line = " ".join(parts)
    print(line)


@celery_app.task(
    name="tasks.auto_consolidation_tasks.classificar_e_consolidar_pedido",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
@log_task_execution(task_type='PEDIDO')
def classificar_e_consolidar_pedido(
    self,
    pedido_id: int,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Classifica um pedido em um grupo de consolidação existente e o consolida.

    Fluxo:
      1. Buscar dados do pedido (canal, modalidade, coleta)
      2. Procurar demanda AGUARDANDO/RASCUNHO com mesmas regras de agrupamento
      3. Se existe → consolidar itens + vincular pedido
      4. Se não existe → criar nova demanda RASCUNHO + consolidar
      5. Retornar resultado
    """
    # Configurar correlation_id
    correlation_id = with_correlation(correlation_id)
    
    # Mapear pedido -> correlation_id
    try:
        supabase_db.table('entity_correlation_mapping').insert({
            'entity_type': 'pedido',
            'entity_id': pedido_id,
            'correlation_id': correlation_id
        }).execute()
    except Exception as e:
        _log("WARN", f"Erro ao mapear pedido {pedido_id} -> correlation_id: {e}")
    
    try:
        _log("INFO", f"Classificando pedido_id={pedido_id}")

        # ================================================================
        # 1. BUSCAR DADOS DO PEDIDO
        # ================================================================
        pedido_res = supabase_db.table('pedidos').select('''
            id,
            numero_pedido,
            codigo_pedido_externo,
            canal_venda_id,
            is_flex,
            origem,
            data_limite_envio,
            canal_venda:canais_venda(nome)
        ''').eq('id', pedido_id).single().execute()

        if not pedido_res.data:
            _log("ERROR", f"Pedido {pedido_id} não encontrado")
            return {"success": False, "error": "Pedido não encontrado"}

        pedido = pedido_res.data
        canal_id = pedido.get('canal_venda_id')
        is_flex = pedido.get('is_flex', False)
        data_limite = pedido.get('data_limite_envio')

        _log("INFO", f"Pedido #{pedido.get('numero_pedido')} — canal={canal_id}, flex={is_flex}, limite={data_limite}")

        # ================================================================
        # 2. BUSCAR ITENS DO PEDIDO (para consolidação)
        # ================================================================
        itens_res = supabase_db.table('itens_pedido').select(
            'id, sku_externo, descricao, quantidade, preco_unitario'
        ).eq('pedido_id', pedido_id).execute()

        itens_pedido = itens_res.data or []
        if not itens_pedido:
            _log("WARN", f"Pedido {pedido_id} sem itens — pulando consolidação")
            return {"success": True, "skipped": True, "reason": "Sem itens"}

        _log("INFO", f"Pedido {pedido_id}: {len(itens_pedido)} itens para consolidar")

        # ================================================================
        # 3. BUSCAR DEMANDA ABERTA COMPATÍVEL (grupo de consolidação)
        # ================================================================
        # Critérios de agrupamento:
        #   - Mesmo canal_venda_id
        #   - Mesmo is_flex (modalidade logística: STANDARD vs EXPRESS)
        #   - Status: RASCUNHO ou AGUARDANDO
        #   - Dentro da janela de coleta (próximas 24h)

        demandas_res = supabase_db.table('demandas_producao').select(
            'id, demanda_id, descricao, status, canal_venda_id, is_flex, data_entrega'
        ).eq('canal_venda_id', canal_id).eq('is_flex', is_flex).in_('status', ['RASCUNHO', 'AGUARDANDO']).execute()

        demandas_candidatas = demandas_res.data or []

        demanda_alvo = None

        # Se há múltiplas candidatas, escolher a mais recente
        if demandas_candidatas:
            demandas_candidatas.sort(key=lambda d: d.get('created_at', ''), reverse=True)
            demanda_alvo = demandas_candidatas[0]
            _log("INFO", f"Grupo encontrado: demanda_id={demanda_alvo['id']} ({demanda_alvo.get('demanda_id')})")
        else:
            _log("INFO", "Nenhum grupo encontrado — criando nova demanda RASCUNHO")

        # ================================================================
        # 4. CRIAR NOVA DEMANDA (se necessário)
        # ================================================================
        if not demanda_alvo:
            from uuid import uuid4

            now = datetime.datetime.now(datetime.timezone.utc)
            demanda_data = {
                'demanda_id': f"RASCUNHO-{canal_id}-{now.strftime('%Y%m%d%H%M')}",
                'descricao': f"Demanda auto — Canal {pedido.get('canal_venda', {}).get('nome', '?')}",
                'status': 'RASCUNHO',
                'tipo_demanda': 'PLATAFORMA',
                'modalidade_logistica': 'EXPRESS' if is_flex else 'STANDARD',
                'classificacao_cliente': 'B2C',
                'canal_venda_id': canal_id,
                'is_flex': is_flex,
                'data_criacao': now.isoformat(),
                'rascunho_expira_em': (now + datetime.timedelta(hours=24)).isoformat(),
            }

            dem_res = supabase_db.table('demandas_producao').insert(demanda_data).execute()
            if not dem_res.data:
                _log("ERROR", "Falha ao criar demanda")
                raise self.retry(exc=Exception("Falha ao criar demanda"))

            demanda_alvo = dem_res.data[0]
            _log("INFO", f"Nova demanda criada: id={demanda_alvo['id']}, demanda_id={demanda_alvo.get('demanda_id')}")

        demanda_id = demanda_alvo['id']

        # ================================================================
        # 5. CONSOLIDAR ITENS DO PEDIDO NA DEMANDA
        # ================================================================
        # Para cada item do pedido, verificar se já existe item equivalente na demanda
        # Se existe → somar quantidade
        # Se não existe → criar novo item de demanda

        itens_demanda_res = supabase_db.table('itens_demanda').select('*').eq('demanda_id', demanda_id).execute()
        itens_demanda_existentes = itens_demanda_res.data or []

        # Mapa SKU → item existente (para merge rápido)
        itens_por_sku = {}
        for item in itens_demanda_existentes:
            sku = item.get('sku_externo')
            if sku:
                itens_por_sku[sku] = item

        itens_para_criar = []
        itens_para_atualizar = []

        for item_pedido in itens_pedido:
            sku = item_pedido.get('sku_externo')
            qtd = int(item_pedido.get('quantidade', 1))

            if sku and sku in itens_por_sku:
                # Item já existe → somar quantidade
                item_existente = itens_por_sku[sku]
                nova_qtd = int(item_existente.get('quantidade_planejada', 0)) + qtd
                itens_para_atualizar.append({
                    'id': item_existente['id'],
                    'quantidade_planejada': nova_qtd,
                    'quantidade': nova_qtd,
                })
                _log("DEBUG", f"  Item SKU={sku}: {item_existente.get('quantidade_planejada', 0)} + {qtd} = {nova_qtd}")
            else:
                # Item novo → criar
                itens_para_criar.append({
                    'demanda_id': demanda_id,
                    'sku_externo': sku,
                    'descricao': item_pedido.get('descricao'),
                    'quantidade': qtd,
                    'quantidade_planejada': qtd,
                    'quantidade_atendida': 0,
                })
                _log("DEBUG", f"  Item SKU={sku}: NOVO (qtd={qtd})")

        # Aplicar atualizações
        if itens_para_atualizar:
            for item_upd in itens_para_atualizar:
                supabase_db.table('itens_demanda').update({
                    'quantidade_planejada': item_upd['quantidade_planejada'],
                    'quantidade': item_upd['quantidade'],
                }).eq('id', item_upd['id']).execute()
            _log("INFO", f"  {len(itens_para_atualizar)} itens atualizados (soma de quantidade)")

        # Aplicar criações
        if itens_para_criar:
            supabase_db.table('itens_demanda').insert(itens_para_criar).execute()
            _log("INFO", f"  {len(itens_para_criar)} itens novos criados na demanda")

        # ================================================================
        # 6. VINCULAR PEDIDO → DEMANDA (pivot)
        # ================================================================
        # Verificar se já não está vinculado
        vinculo_existente = supabase_db.table('demandas_pedidos').select('id').eq('pedido_id', pedido_id).eq('demanda_id', demanda_id).execute()

        if not vinculo_existente.data:
            supabase_db.table('demandas_pedidos').insert({
                'demanda_id': demanda_id,
                'pedido_id': pedido_id,
            }).execute()
            _log("INFO", f"Pedido {pedido_id} vinculado à demanda {demanda_id}")
        else:
            _log("INFO", f"Pedido {pedido_id} já estava vinculado à demanda {demanda_id}")

        # ================================================================
        # 7. ATUALIZAR STATUS SE NECESSÁRIO
        # ================================================================
        # Se a demanda estava em RASCUNHO e agora tem itens + pedidos,
        # promover para AGUARDANDO
        if demanda_alvo.get('status') == 'RASCUNHO':
            # Verificar se há pelo menos 1 pedido e 1 item
            total_pedidos = supabase_db.table('demandas_pedidos').select('id', count='exact').eq('demanda_id', demanda_id).execute()
            total_itens = supabase_db.table('itens_demanda').select('id', count='exact').eq('demanda_id', demanda_id).execute()

            if (total_pedidos.count or 0) >= 1 and (total_itens.count or 0) >= 1:
                supabase_db.table('demandas_producao').update({
                    'status': 'AGUARDANDO',
                }).eq('id', demanda_id).execute()
                _log("INFO", f"Demanda {demanda_id}: RASCUNHO → AGUARDANDO")

        # ================================================================
        # 8. RETORNAR
        # ================================================================
        _log("INFO", f"✅ Concluído: pedido {pedido_id} → demanda {demanda_id} "
                      f"({len(itens_para_criar)} novos, {len(itens_para_atualizar)} atualizados)")

        return {
            "success": True,
            "pedido_id": pedido_id,
            "demanda_id": demanda_id,
            "demanda_numero": demanda_alvo.get('demanda_id'),
            "itens_novos": len(itens_para_criar),
            "itens_atualizados": len(itens_para_atualizar),
        }

    except Exception as e:
        _log("ERROR", f"Erro ao classificar/consolidar pedido {pedido_id}: {e}")
        raise self.retry(exc=e, countdown=30 * (2 ** self.request.retries))
