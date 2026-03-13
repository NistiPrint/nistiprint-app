import os
import sys
from typing import Dict, List, Any

# Adiciona o caminho do pacote compartilhado
sys.path.append(os.path.join(os.getcwd(), 'packages', 'shared'))

from nistiprint_shared.database.supabase_db_service import supabase_db

def audit_demand_consumption(demanda_id: str):
    print(f"\n=== AUDITORIA DE CONSUMO: DEMANDA {demanda_id} ===\n")
    
    # 1. Obter Previsão de Consumo
    previsao_res = supabase_db.table('previsao_consumo_demanda')\
        .select('produto_id, quantidade_prevista, unidade, produtos(nome, sku)')\
        .eq('demanda_id', demanda_id)\
        .execute()
    
    if not previsao_res.data:
        print("[!] Nenhuma previsão encontrada para esta demanda.")
        return

    previsao_map = {}
    for p in previsao_res.data:
        pid = p['produto_id']
        previsao_map[pid] = {
            'nome': p['produtos']['nome'],
            'sku': p['produtos']['sku'],
            'previsto': float(p['quantidade_prevista']),
            'unidade': p['unidade'],
            'realizado': 0.0
        }

    # 2. Obter Movimentações Reais
    # Vamos buscar por documento_referencia = demanda_id OU motivo contendo o ID da demanda
    # Nota: Em produções reais, o documento_referencia deve ser o ID da demanda (UUID ou PK)
    
    # Tenta buscar movimentos pelo documento_referencia
    mov_res = supabase_db.table('movimentacoes_estoque')\
        .select('produto_id, quantidade, tipo_movimentacao, motivo')\
        .eq('documento_referencia', demanda_id)\
        .execute()
    
    # Também busca na fila de processamento se houve correlation_id propagado
    # (Para auditoria mais profunda, precisaríamos seguir os correlation_ids)
    
    all_movements = mov_res.data or []
    
    # Se não achou nada por doc_ref, tenta por motivo (fallback legado/parcial)
    if not all_movements:
        mov_res_motivo = supabase_db.table('movimentacoes_estoque')\
            .select('produto_id, quantidade, tipo_movimentacao, motivo')\
            .ilike('motivo', f'%{demanda_id}%')\
            .execute()
        all_movements = mov_res_motivo.data or []

    for m in all_movements:
        pid = m['produto_id']
        qty = abs(float(m['quantidade']))
        
        if pid in previsao_map:
            if m['tipo_movimentacao'] == 'SAIDA':
                previsao_map[pid]['realizado'] += qty
            elif m['tipo_movimentacao'] == 'ENTRADA': # Estorno
                previsao_map[pid]['realizado'] -= qty
        else:
            # Produto consumido mas não previsto!
            print(f"[AVISO] Produto ID {pid} consumido ({qty}) mas não estava na previsão!")

    # 3. Relatório Final
    print(f"{'PRODUTO (SKU)':<40} | {'PREVISTO':<10} | {'REALIZADO':<10} | {'DIFERENÇA':<10}")
    print("-" * 80)
    
    total_discrepancy = 0
    for pid, data in previsao_map.items():
        prev = data['previsto']
        real = data['realizado']
        diff = prev - real
        status = "OK" if abs(diff) < 0.001 else "ERRO"
        
        label = f"{data['nome'][:25]} ({data['sku']})"
        print(f"{label:<40} | {prev:<10.2f} | {real:<10.2f} | {diff:<10.2f} [{status}]")
        
        if status == "ERRO":
            total_discrepancy += 1

    if total_discrepancy == 0:
        print("\n[SUCESSO] Consumo real condiz com a previsão.")
    else:
        print(f"\n[ALERTA] Encontradas {total_discrepancy} discrepâncias no consumo.")

def run_global_audit(limit=10):
    print(f"=== AUDITORIA GLOBAL DE CONSUMO (Últimas {limit} demandas) ===\n")
    
    demandas = supabase_db.table('demandas_producao')\
        .select('id, descricao')\
        .order('created_at', desc=True)\
        .limit(limit)\
        .execute()
    
    for d in demandas.data:
        audit_demand_consumption(d['id'])

if __name__ == "__main__":
    if len(sys.argv) > 1:
        audit_demand_consumption(sys.argv[1])
    else:
        run_global_audit()
