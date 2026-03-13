# Relatório de Status: Refatoração do Consumo de Estoque (Asíncrono & BOM ao Final)

## 1. Situação Atual (Contexto)
Atualmente, o sistema utiliza um modelo **híbrido** de processamento de estoque que mistura operações síncronas e assíncronas durante o ciclo de vida da produção:

*   **Dashboard (Incrementos):** Cada vez que um usuário avança uma etapa (ex: Capas Impressas +5), o sistema tenta realizar a baixa de estoque do nível anterior e a entrada JIT do produto intermediário de forma **síncrona**.
*   **JIT Síncrono:** A lógica de "Just-in-Time" (produzir componentes faltantes automaticamente) é executada na mesma requisição do dashboard, o que pode causar lentidão e erros de transação se houver muitos componentes.
*   **Fila de Processamento:** Já existe uma fila (`fila_processamento_estoque`) e um worker (Celery), mas eles são usados de forma fragmentada para cada incremento de etapa, gerando muitos eventos pequenos na fila.
*   **Integridade:** A integridade do estoque (explosão completa da BOM) é tentada de forma incremental, o que dificulta o controle quando há erros no meio do processo ou estornos.

## 2. Problemas Identificados
1.  **Complexidade no Dashboard:** O frontend precisa lidar com erros de estoque (mesmo que permitindo negativo) e a performance é afetada pela lógica de JIT síncrona.
2.  **Fragmentação:** O consumo de componentes (BOM) é feito "picado" a cada avanço, dificultando a reconciliação final se as quantidades produzidas não baterem exatamente com a BOM.
3.  **Dificuldade em Estornos:** Reverter uma produção incremental exige reverter individualmente cada baixa de insumo feita na fila.

## 3. Solução Proposta (Arquitetura Nova)

O objetivo é simplificar o dashboard e garantir a consistência movendo a explosão da árvore de materiais (BOM) para o final do processo.

### A. Processo Síncrono (Dashboard)
*   **Ação:** O usuário incrementa qualquer etapa de produção.
*   **Comportamento:** 
    *   Atualiza visualmente as colunas no banco de dados (`itens_demanda`).
    *   Registra uma movimentação simples (1º nível) do produto daquela etapa (entrada/saída direta), permitindo estoque negativo.
    *   **NÃO** faz explosão de BOM, **NÃO** faz JIT síncrono, **NÃO** insere na fila para cada incremento.
*   **Resultado:** Dashboard rápido, fluido e focado apenas no rastreamento visual das etapas.

### B. Processo de Finalização (Gatilho)
*   **Ação:** O usuário clica em "Finalizar Item" ou o item atinge a última etapa (Expedição).
*   **Comportamento:**
    *   O sistema gera um **evento único** na fila de processamento: `FINALIZACAO_ITEM_BOM`.
    *   Este evento contém a quantidade total finalizada e o ID do produto final.

### C. Processo Assíncrono (Worker)
*   **Tarefa:** Processar o evento `FINALIZACAO_ITEM_BOM`.
*   **Ações:**
    1.  **Explosão de BOM:** Identifica todos os componentes (Miolo, Capa, Insumos, Wire-o, etc.) necessários para o produto final.
    2.  **JIT Assíncrono:** Se um componente for um produto composto (ex: Capa Laminada), o worker executa a produção dele e a baixa de seus respectivos insumos (Papel, BOPP).
    3.  **Baixa Consolidada:** Registra todas as saídas de estoque de uma vez, garantindo que o consumo reflita exatamente a BOM configurada para o total produzido.

## 4. Plano de Implementação (Próximos Passos)

1.  **Refatorar `DemandaProducaoService`:**
    *   Remover a lógica de JIT síncrono de `processar_alocacao_de_demanda_otimizado`.
    *   Desabilitar chamadas a `agendar_processamento_estoque` durante incrementos simples (opcionalmente manter apenas log visual).
    *   Aprimorar `finalizar_item` para disparar a tarefa de explosão de BOM consolidada.
2.  **Refatorar `processar_fila_estoque` (Worker):**
    *   Implementar o handler para o novo tipo de tarefa que realiza a explosão completa da árvore de produtos.
3.  **Migração de Dados (Se necessário):**
    *   Garantir que itens já em produção não tenham duplicidade de consumo ao serem finalizados.

Esta mudança reduzirá drasticamente o overhead do dashboard e centralizará a integridade do estoque no final da esteira produtiva.
