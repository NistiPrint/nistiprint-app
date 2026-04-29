"""
Script de Verificação Rápida: Duplicação de Movimentações
==========================================================

Este script verifica se há duplicação de movimentações de estoque
após as correções implementadas.

Uso:
    python scripts/verificar_duplicacao.py
"""

import sys
import os
from datetime import datetime, timedelta

# Adicionar path do projeto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from nistiprint_shared.database.supabase_db_service import supabase_db

def print_header(text):
    print("\n" + "=" * 80)
    print(f" {text}")
    print("=" * 80 + "\n")

def verificar_duplicacao_geral():
    """Verifica duplicação de movimentações nas últimas 24 horas"""
    print_header("VERIFICAÇÃO DE DUPLICAÇÃO DE MOVIMENTAÇÕES")
    
    # Buscar últimas movimentações
    result = supabase_db.table('movimentacoes_estoque')\
        .select('*')\
        .order('created_at', desc=True)\
        .limit(200)\
        .execute()
    
    if not result.data:
        print("❌ Nenhuma movimentação encontrada no banco de dados.")
        return
    
    movimentacoes = result.data
    print(f"Total de movimentações analisadas: {len(movimentacoes)}")
    print(f"Período: {movimentacoes[-1]['created_at'][:19]} até {movimentacoes[0]['created_at'][:19]}")
    
    # Agrupar por correlation_id
    por_correlation = {}
    for mov in movimentacoes:
        corr = mov.get('correlation_id', 'SEM_CORRELATION')
        if corr not in por_correlation:
            por_correlation[corr] = []
        por_correlation[corr].append(mov)
    
    # Identificar correlation_ids com múltiplas movimentações
    print_section("1. MOVIMENTAÇÕES POR CORRELATION_ID")
    
    correls_multiplas = {k: v for k, v in por_correlation.items() if len(v) > 1}
    
    if correls_multiplas:
        print(f"\n{len(correls_multiplas)} correlation_ids com múltiplas movimentações:")
        
        # Verificar se são duplicações reais ou operações relacionadas
        duplicacoes_reais = []
        
        for corr, movs in correls_multiplas.items():
            # Agrupar por produto + tipo + quantidade
            grupos = {}
            for mov in movs:
                chave = f"{mov['produto_id']}_{mov['tipo_movimentacao']}_{mov['quantidade']}"
                if chave not in grupos:
                    grupos[chave] = []
                grupos[chave].append(mov)
            
            # Verificar duplicações exatas
            for chave, grupo in grupos.items():
                if len(grupo) > 1:
                    duplicacoes_reais.append({
                        'correlation_id': corr,
                        'chave': chave,
                        'count': len(grupo),
                        'movimentacoes': grupo
                    })
        
        if duplicacoes_reais:
            print(f"\n⚠️  {len(duplicacoes_reais)} DUPLICAÇÕES REAIS DETECTADAS:\n")
            
            for dup in duplicacoes_reais[:10]:  # Mostrar apenas 10 primeiras
                print(f"  Correlation: {dup['correlation_id'][:8]}...")
                print(f"  Produto/Tipo/Qtd: {dup['chave']}")
                print(f"  Ocorrências: {dup['count']}")
                
                for mov in dup['movimentacoes'][:2]:
                    print(f"    - {mov['created_at'][11:19]} | {mov['tipo_movimentacao']} {mov['quantidade']:+.1f}")
                
                if dup['count'] > 2:
                    print(f"    ... e mais {dup['count'] - 2}")
                print()
        else:
            print("\n✅ Múltiplas movimentações por correlation_id, mas SEM duplicação exata")
            print("   (provavelmente operações relacionadas: entrada + saída)")
    else:
        print("\n✅ Cada correlation_id tem apenas UMA movimentação")
    
    # Análise por produto
    print_section("2. MOVIMENTAÇÕES POR PRODUTO")
    
    por_produto = {}
    for mov in movimentacoes:
        pid = mov['produto_id']
        if pid not in por_produto:
            por_produto[pid] = {'ENTRADA': 0, 'SAIDA': 0}
        if mov['tipo_movimentacao'] == 'ENTRADA':
            por_produto[pid]['ENTRADA'] += 1
        elif mov['tipo_movimentacao'] == 'SAIDA':
            por_produto[pid]['SAIDA'] += 1
    
    # Produtos com muitas movimentações
    produtos_suspeitos = {k: v for k, v in por_produto.items() if v['ENTRADA'] > 3 or v['SAIDA'] > 3}
    
    if produtos_suspeitos:
        print(f"\n{len(produtos_suspeitos)} produtos com muitas movimentações:")
        for pid, counts in list(produtos_suspeitos.items())[:5]:
            print(f"  Produto {pid}: {counts['ENTRADA']} entradas, {counts['SAIDA']} saídas")
    else:
        print("\n✅ Distribuição normal de movimentações por produto")
    
    # Resumo final
    print_section("3. RESUMO")
    
    if duplicacoes_reais:
        print(f"\n❌ FORAM DETECTADAS {len(duplicacoes_reais)} DUPLICAÇÕES REAIS")
        print("\nIsso indica que as correções podem não ter sido aplicadas corretamente.")
        print("Verifique:")
        print("  1. Se o código foi atualizado em produção")
        print("  2. Se há reinício dos workers após atualização")
        print("  3. Se o Celery está rodando corretamente")
    else:
        print("\n✅ SEM DUPLICAÇÕES REAIS DETECTADAS")
        print("\nAs correções estão funcionando corretamente!")
    
    print("\n" + "=" * 80)
    
    return len(duplicacoes_reais) == 0

def verificar_fila_processamento():
    """Verifica status da fila de processamento"""
    print_section("FILA DE PROCESSAMENTO")
    
    try:
        result = supabase_db.table('fila_processamento_estoque')\
            .select('status, tipo_operacao, created_at')\
            .order('created_at', desc=True)\
            .limit(50)\
            .execute()
        
        if not result.data:
            print("Nenhuma tarefa na fila.")
            return
        
        # Contar por status
        por_status = {}
        for tarefa in result.data:
            status = tarefa.get('status', 'DESCONHECIDO')
            if status not in por_status:
                por_status[status] = 0
            por_status[status] += 1
        
        print("\nTarefas por status:")
        for status, count in por_status.items():
            print(f"  {status}: {count}")
        
        # Verificar tarefas com erro
        erros = [t for t in result.data if t.get('status') == 'ERRO']
        if erros:
            print(f"\n⚠️  {len(erros)} tarefas com ERRO:")
            for erro in erros[:3]:
                print(f"  - {erro.get('tipo_operacao')}: {erro.get('mensagem_erro', 'Sem mensagem')[:50]}")
        
    except Exception as e:
        print(f"Erro ao verificar fila: {e}")

def print_section(text):
    print("\n" + "-" * 60)
    print(f" {text}")
    print("-" * 60)

if __name__ == '__main__':
    print("\n" + "=" * 80)
    print(" VERIFICAÇÃO DE DUPLICAÇÃO DE ESTOQUE")
    print(" Pós-correção")
    print("=" * 80)
    
    # Verificar duplicação
    sucesso = verificar_duplicacao_geral()
    
    # Verificar fila
    verificar_fila_processamento()
    
    sys.exit(0 if sucesso else 1)
