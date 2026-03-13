import os
import sys
from datetime import datetime
import uuid

# Adiciona o caminho do pacote compartilhado se necessário
sys.path.append(os.path.join(os.getcwd(), 'packages', 'shared'))

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
from nistiprint_shared.services.estoque_service import estoque_service
from nistiprint_shared.services.bom_service import bom_service
from nistiprint_shared.services.app_config_service import app_config_service

def test_async_bom_flow():
    print("\n=== INICIANDO TESTE DE FLUXO DE ESTOQUE ASSÍNCRONO (BOM CONSOLIDADA) ===\n")
    
    PRODUCT_ID = 188 # Produto com BOM (21 e 65)
    QTY_TEST = 2
    USER_ID = "Test_User_Async"
    
    # 1. Garantir saldo inicial positivo e verificar saldo inicial
    components = bom_service.get_bom_for_produto(PRODUCT_ID)
    print(f"[*] Produto {PRODUCT_ID} possui {len(components)} componentes na BOM.")
    
    saldos_iniciais = {}
    for comp in components:
        cid = comp.componente_id
        # Adiciona 100 de saldo para facilitar visualização
        estoque_service.registrar_entrada(cid, None, 100, "Carga Inicial Teste Async")
        
        saldo = estoque_service.get_saldo_atual(cid).get('quantidade_disponivel', 0)
        saldos_iniciais[cid] = saldo
        print(f"    - Componente {cid}: Saldo Inicial = {saldo}")

    # 2. Criar uma Demanda de Teste
    print("\n[*] Criando demanda de teste...")
    demanda = demanda_producao_service.criar_demanda_direta(
        nome_demanda=f"Teste Async BOM {uuid.uuid4().hex[:6]}",
        canal_venda_id=None,
        data_entrega_str=datetime.now().strftime('%Y-%m-%d'),
        lista_de_itens=[{
            'produto_id': PRODUCT_ID,
            'sku': 'SKU-TEST-ASYNC',
            'descricao': 'Item de Teste Async',
            'quantidade': QTY_TEST
        }],
        user_id=USER_ID
    )
    demanda_id = demanda['id']
    item_id = demanda['itens'][0]['id']
    print(f"    - Demanda ID: {demanda_id}, Item ID: {item_id}")

    # 3. Simular Incremento no Dashboard (Etapa de Capas)
    # No novo modelo, isso deve fazer apenas movimentação de 1º nível (Entrada/Saída do item da etapa)
    # E NÃO deve explodir a BOM dos insumos.
    print(f"\n[*] Simulando incremento de Capas Impressas (+{QTY_TEST})...")
    demanda_producao_service.registrar_producao_incremental(
        demanda_id=demanda_id,
        item_id=item_id,
        producao_absoluta={'capas_impressas_qtd': QTY_TEST},
        user_id=USER_ID
    )

    # 4. Validar que saldos dos componentes não mudaram (ou mudaram apenas se forem o 1º nível direto)
    print("\n[*] Validando saldos após incremento visual (não deve ter baixado BOM ainda)...")
    for comp in components:
        cid = comp.componente_id
        saldo_atual = estoque_service.get_saldo_atual(cid).get('quantidade_disponivel', 0)
        diff = saldos_iniciais[cid] - saldo_atual
        print(f"    - Componente {cid}: Saldo Atual = {saldo_atual} (Diff: {diff})")
        # Como o produto 188 tem 21 e 65 na BOM, e não são o produto principal da etapa, diff deve ser 0
        if diff != 0:
             print(f"    [!] AVISO: Componente {cid} teve baixa prematura de {diff}!")

    # 5. Finalizar o Item (Gatilho para explosão de BOM)
    print(f"\n[*] Finalizando o item {item_id} (Disparando ITEM_TOTAL_BOM_PROCESS)...")
    demanda_producao_service.finalizar_item(demanda_id, item_id, USER_ID)
    
    # 6. Verificar se há tarefa na fila
    res_fila = supabase_db.table('fila_processamento_estoque')\
        .select('*')\
        .eq('item_id', item_id)\
        .eq('campo', 'ITEM_TOTAL_BOM_PROCESS')\
        .eq('status', 'PENDENTE')\
        .execute()
    
    if res_fila.data:
        print(f"    [OK] Tarefa ITEM_TOTAL_BOM_PROCESS encontrada na fila.")
    else:
        print(f"    [ERRO] Tarefa não encontrada na fila!")

    # 7. Executar o Worker (Processar Fila)
    print("\n[*] Executando Worker para processar a fila...")
    processed = demanda_producao_service.processar_fila_estoque(limit=10)
    print(f"    - Tarefas processadas: {processed}")

    # 8. Validar Saldos Finais (BOM explodida)
    print("\n[*] Validando saldos finais (após processamento do Worker)...")
    success = True
    for comp in components:
        cid = comp.componente_id
        saldo_final = estoque_service.get_saldo_atual(cid).get('quantidade_disponivel', 0)
        baixa_esperada = comp.quantidade * QTY_TEST
        baixa_real = saldos_iniciais[cid] - saldo_final
        
        print(f"    - Componente {cid}:")
        print(f"        Baixa Esperada: {baixa_esperada}")
        print(f"        Baixa Real:     {baixa_real}")
        print(f"        Saldo Final:    {saldo_final}")
        
        if abs(baixa_real - baixa_esperada) < 0.001:
            print("        [OK] Baixa correta.")
        else:
            print(f"        [FALHA] Baixa incorreta! Diferença de {baixa_real - baixa_esperada}")
            success = False

    if success:
        print("\n[RESULTADO] TESTE CONCLUÍDO COM SUCESSO! O fluxo assíncrono consolidado está operando corretamente.")
    else:
        print("\n[RESULTADO] TESTE CONCLUÍDO COM FALHAS. Verifique os logs acima.")

if __name__ == "__main__":
    test_async_bom_flow()
