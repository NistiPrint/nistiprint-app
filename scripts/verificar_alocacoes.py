"""
Script para verificar se a tabela demanda_alocacoes_estoque existe e está funcionando

Uso:
  # Opção 1: Definir variáveis de ambiente primeiro
  set SUPABASE_URL=https://seu-project.supabase.co
  set SUPABASE_SERVICE_KEY=seu-service-key
  python scripts\verificar_alocacoes.py
  
  # Opção 2: Executar dentro do container Docker
  docker exec -it local-nistiprint-api python scripts/verificar_alocacoes.py
"""

import sys
import os
import json

# Tentar carregar do arquivo .env se existir
env_file = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(env_file):
    print(f"Carregando variáveis de ambiente de {env_file}...")
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())

# Configurar path do projeto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Verificar se variáveis estão configuradas
if not os.environ.get('SUPABASE_URL') or not os.environ.get('SUPABASE_SERVICE_KEY'):
    print("=" * 80)
    print(" ERRO: Variáveis de ambiente não configuradas")
    print("=" * 80)
    print("\nOpções para executar este script:\n")
    print("1. Via Docker (RECOMENDADO):")
    print("   docker exec -it local-nistiprint-api python scripts/verificar_alocacoes.py")
    print("\n2. Via variáveis de ambiente:")
    print("   set SUPABASE_URL=https://seu-project.supabase.co")
    print("   set SUPABASE_SERVICE_KEY=seu-service-key")
    print("   python scripts\\verificar_alocacoes.py")
    print("\n3. Copiar .env.example para .env e preencher")
    print("=" * 80)
    sys.exit(1)

from nistiprint_shared.database.supabase_db_service import supabase_db

def verificar_tabela_alocacoes():
    print("=" * 80)
    print(" VERIFICAÇÃO: Tabela demanda_alocacoes_estoque")
    print("=" * 80)
    
    # 1. Verificar se a tabela existe
    print("\n1. Verificando se a tabela existe...")
    try:
        result = supabase_db.table('demanda_alocacoes_estoque').select('id').limit(1).execute()
        print(f"   ✅ Tabela existe e está acessível")
    except Exception as e:
        print(f"   ❌ ERRO: {e}")
        print("   A tabela pode não existir. Execute o migration 20260314000000_demanda_alocacoes_estoque.sql")
        return False
    
    # 2. Contar registros
    print("\n2. Contando registros na tabela...")
    try:
        result = supabase_db.table('demanda_alocacoes_estoque').select('*', count='exact').execute()
        count = len(result.data) if result.data else 0
        print(f"   Total de alocações: {count}")
    except Exception as e:
        print(f"   ERRO ao contar: {e}")
        count = 0
    
    # 3. Mostrar últimas alocações
    if count > 0:
        print("\n3. Últimas 10 alocações:")
        try:
            result = supabase_db.table('demanda_alocacoes_estoque')\
                .select('*')\
                .order('created_at', desc=True)\
                .limit(10)\
                .execute()
            
            if result.data:
                print(f"   {'ID':<8} {'ITEM':<8} {'PRODUTO':<10} {'QTD':<6} {'TIPO':<20} {'STATUS':<12}")
                print("   " + "-" * 70)
                for aloc in result.data:
                    print(f"   {aloc['id'][:8]:<8} {str(aloc['item_id'])[:8]:<8} {str(aloc['produto_id']):<10} {aloc['quantidade_alocada']:<6.1f} {aloc['tipo_alocacao']:<20} {aloc['status']:<12}")
        except Exception as e:
            print(f"   ERRO ao buscar: {e}")
    
    # 4. Verificar views
    print("\n4. Verificando views...")
    try:
        result = supabase_db.table('view_alocacoes_por_item').select('*').limit(5).execute()
        if result.data:
            print(f"   ✅ view_alocacoes_por_item: {len(result.data)} registros")
        else:
            print(f"   ⚠️  view_alocacoes_por_item: vazia")
    except Exception as e:
        print(f"   ⚠️  view_alocacoes_por_item não existe: {e}")
    
    try:
        result = supabase_db.table('view_alocacoes_por_demanda').select('*').limit(5).execute()
        if result.data:
            print(f"   ✅ view_alocacoes_por_demanda: {len(result.data)} registros")
        else:
            print(f"   ⚠️  view_alocacoes_por_demanda: vazia")
    except Exception as e:
        print(f"   ⚠️  view_alocacoes_por_demanda não existe: {e}")
    
    # 5. Verificar funções RPC
    print("\n5. Verificando funções RPC...")
    try:
        result = supabase_db.rpc('calcular_saldo_a_processar', {
            'p_item_id': '00000000-0000-0000-0000-000000000000',
            'p_produto_id': '0',
            'p_quantidade_necessaria': 0
        }).execute()
        print(f"   ✅ RPC calcular_saldo_a_processar: disponível")
    except Exception as e:
        print(f"   ❌ RPC calcular_saldo_a_processar: NÃO disponível ({e})")
    
    try:
        result = supabase_db.rpc('verificar_alocacao_existente', {
            'p_correlation_id': 'teste'
        }).execute()
        print(f"   ✅ RPC verificar_alocacao_existente: disponível")
    except Exception as e:
        print(f"   ❌ RPC verificar_alocacao_existente: NÃO disponível ({e})")
    
    print("\n" + "=" * 80)
    
    return True

if __name__ == '__main__':
    verificar_tabela_alocacoes()
