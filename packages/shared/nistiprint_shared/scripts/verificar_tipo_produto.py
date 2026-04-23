"""
Script de Verificação de Tipo de Produto

Script simplificado para verificar a classificação de produtos.
O campo tipo_material já existe e foi convertido para tipo_produto.

Uso:
    python -m nistiprint_shared.scripts.verificar_tipo_produto

Autor: NistiPrint
Data: 2026-03-24
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from nistiprint_shared.database.supabase_db_service import supabase_db
from typing import List, Dict, Any


CORES = {
    'OK': '\033[92m',        # Verde
    'ERRO': '\033[91m',      # Vermelho
    'AVISO': '\033[93m',     # Amarelo
    'RESET': '\033[0m',
    'BOLD': '\033[1m'
}


def get_auditoria() -> List[Dict[str, Any]]:
    """Busca auditoria de tipo_produto."""
    response = supabase_db.table('view_auditoria_tipo_produto')\
        .select('*')\
        .execute()
    
    return response.data if response.data else []


def get_divergentes() -> List[Dict[str, Any]]:
    """Busca apenas produtos com divergência."""
    response = supabase_db.table('view_auditoria_tipo_produto')\
        .select('*')\
        .neq('status_conferencia', 'OK')\
        .execute()
    
    return response.data if response.data else []


def get_resumo() -> Dict[str, int]:
    """Retorna resumo da classificação."""
    response = supabase_db.table('produtos')\
        .select('tipo_produto')\
        .execute()
    
    resumo = {
        'MATERIA_PRIMA': 0,
        'INTERMEDIARIO': 0,
        'PRODUTO_ACABADO': 0,
        'SERVICO': 0,
        'NAO_CLASSIFICADO': 0
    }
    
    if response.data:
        for produto in response.data:
            tipo = produto.get('tipo_produto')
            if tipo is None:
                resumo['NAO_CLASSIFICADO'] += 1
            elif tipo in resumo:
                resumo[tipo] += 1
    
    return resumo


def atualizar_tipo(produto_id: int, tipo_produto: str) -> bool:
    """Atualiza tipo_produto manualmente."""
    try:
        supabase_db.table('produtos')\
            .update({'tipo_produto': tipo_produto})\
            .eq('id', produto_id)\
            .execute()
        return True
    except Exception as e:
        print(f"{CORES['ERRO']}Erro: {e}{CORES['RESET']}")
        return False


def mostrar_resumo():
    """Mostra resumo da classificação."""
    resumo = get_resumo()
    total = sum(resumo.values())
    
    print(f"\n{CORES['BOLD']}{'=' * 50}{CORES['RESET']}")
    print(f"{CORES['BOLD']}RESUMO DA CLASSIFICAÇÃO{CORES['RESET']}")
    print(f"{CORES['BOLD']}{'=' * 50}{CORES['RESET']}")
    
    for tipo, quantidade in resumo.items():
        porcentagem = (quantidade / total * 100) if total > 0 else 0
        print(f"  {tipo:20}: {quantidade:5} ({porcentagem:5.2f}%)")
    
    print(f"{CORES['BOLD']}{'=' * 50}{CORES['RESET']}")
    print(f"  {'TOTAL':20}: {total:5} (100.00%)")
    print(f"{CORES['BOLD']}{'=' * 50}{CORES['RESET']}")


def mostrar_divergentes():
    """Mostra produtos com divergência."""
    divergentes = get_divergentes()
    
    if not divergentes:
        print(f"\n{CORES['OK']}✓ Todos os produtos estão classificados corretamente!{CORES['RESET']}")
        return
    
    print(f"\n{CORES['AVISO']}⚠ Produtos com divergência ({len(divergentes)}):{CORES['RESET']}\n")
    
    for i, prod in enumerate(divergentes[:20], 1):
        status = prod.get('status_conferencia', 'DESCONHECIDO')
        cor = CORES['ERRO'] if status == 'ERRO_CONVERSAO' else CORES['AVISO']
        
        print(f"  {i:3}. ID: {prod.get('id'):6} | SKU: {prod.get('sku', 'N/A'):15} | "
              f"{cor}{status:20}{CORES['RESET']} | "
              f"tipo_material: {prod.get('tipo_material', 'NULL'):15} | "
              f"tipo_produto: {prod.get('tipo_produto', 'NULL'):15}")
    
    if len(divergentes) > 20:
        print(f"\n  ... e mais {len(divergentes) - 20} produtos")
    
    print(f"\n{CORES['BOLD']}Use a view view_auditoria_tipo_produto para ver todos.{CORES['RESET']}")


def menu_principal():
    """Mostra menu principal."""
    print(f"\n{CORES['BOLD']}MENU:{CORES['RESET']}")
    print(f"  1. Ver Resumo")
    print(f"  2. Ver Divergências")
    print(f"  3. Atualizar Tipo Manualmente")
    print(f"  0. Sair")


def main():
    """Função principal."""
    print(f"{CORES['BOLD']}VERIFICAÇÃO DE TIPO DE PRODUTO{CORES['RESET']}")
    print(f"Campo origem: tipo_material → destino: tipo_produto")
    
    while True:
        menu_principal()
        opcao = input(f"\n{CORES['BOLD']}Escolha: {CORES['RESET']}").strip()
        
        if opcao == '1':
            mostrar_resumo()
        elif opcao == '2':
            mostrar_divergentes()
        elif opcao == '3':
            produto_id = input("ID do produto: ").strip()
            print("Tipos: MATERIA_PRIMA, INTERMEDIARIO, PRODUTO_ACABADO, SERVICO")
            tipo = input("Tipo: ").strip().upper()
            
            if produto_id.isdigit() and tipo in ['MATERIA_PRIMA', 'INTERMEDIARIO', 'PRODUTO_ACABADO', 'SERVICO']:
                if atualizar_tipo(int(produto_id), tipo):
                    print(f"{CORES['OK']}✓ Atualizado!{CORES['RESET']}")
            else:
                print(f"{CORES['ERRO']}Dados inválidos{CORES['RESET']}")
        elif opcao == '0':
            break
        else:
            print(f"{CORES['ERRO']}Opção inválida{CORES['RESET']}")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{CORES['AVISO']}Interrompido.{CORES['RESET']}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{CORES['ERRO']}Erro: {e}{CORES['RESET']}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
