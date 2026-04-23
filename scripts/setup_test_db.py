import os
import requests
from supabase import create_client, Client
from dotenv import load_dotenv

# Carrega .env com as chaves de PROD e TEST
load_dotenv()

# Configurações de Produção (Origem)
PROD_URL = os.getenv("SUPABASE_URL_PROD")
PROD_KEY = os.getenv("SUPABASE_SERVICE_KEY_PROD")

# Configurações de Teste (Destino)
TEST_URL = os.getenv("SUPABASE_URL_TEST")
TEST_KEY = os.getenv("SUPABASE_SERVICE_KEY_TEST")

# Tabelas Estruturais para Clonar (Ordem importa para FKs)
TABELAS_ESTRUTURAIS = [
    "categorias",
    "unidades_medida",
    "produtos",
    "ficha_tecnica",
    "canais_venda",
    "contas_bling",
    "configuracoes_aplicacao",
    "conversoes_uom_produto",
    "depositos"
]

def clone_data():
    if not all([PROD_URL, PROD_KEY, TEST_URL, TEST_KEY]):
        print("Erro: Verifique se as variáveis SUPABASE_URL_PROD/TEST e SERVICE_KEY_PROD/TEST estão no .env")
        return

    prod_client: Client = create_client(PROD_URL, PROD_KEY)
    test_client: Client = create_client(TEST_URL, TEST_KEY)

    print("🚀 Iniciando clonagem de dados estruturais para ambiente de teste...")

    for tabela in TABELAS_ESTRUTURAIS:
        print(f"📦 Clonando tabela: {tabela}...")
        
        # 1. Buscar dados de PROD
        res_prod = prod_client.table(tabela).select("*").execute()
        dados = res_prod.data

        if not dados:
            print(f"⚠️ Tabela {tabela} está vazia em Produção. Pulando.")
            continue

        # 2. Limpar dados existentes em TEST (Cuidado!)
        # test_client.table(tabela).delete().neq("id", 0).execute() # Só se quiser resetar

        # 3. Inserir em TEST (em lotes de 100 para evitar timeout)
        batch_size = 100
        for i in range(0, len(dados), batch_size):
            batch = dados[i:i + batch_size]
            try:
                test_client.table(tabela).upsert(batch).execute()
            except Exception as e:
                print(f"❌ Erro ao inserir lote na tabela {tabela}: {e}")

    print("✅ Clonagem concluída com sucesso!")

if __name__ == "__main__":
    clone_data()
