# Plano de Implementação: Refatoração do Estoque e Previsibilidade de Consumo

## 1. Contexto e Objetivos
O sistema de estoque está sendo refatorado para separar o rastreamento em tempo real (dashboard de produção) da contabilidade pesada de materiais (explosão de BOM).
O objetivo é garantir performance no dashboard (O(1)) e integridade nos dados de estoque (transações completas e auditáveis).
Adicionalmente, precisamos elevar o nível de **previsibilidade**, persistindo o "plano de consumo" de cada demanda em uma estrutura dedicada para análise agregada.

## 2. Arquitetura e Mudanças

### A. Tabela de Previsão de Consumo (`previsao_consumo_demanda`)
Em vez de um campo JSON genérico, teremos uma tabela dedicada para armazenar o snapshot do consumo previsto.
- **Estrutura:**
  - `id` (UUID)
  - `demanda_id` (FK -> demandas_producao)
  - `produto_id` (FK -> produtos)
  - `quantidade_prevista` (Numeric)
  - `unidade` (Text)
  - `status` (Enum: 'PLANEJADO', 'REALIZADO', 'CANCELADO')
  - `created_at`, `updated_at`
- **Fluxo:**
  - **Criação/Edição de Demanda:** O sistema calcula a explosão da BOM (Recursiva) e salva/atualiza os registros nesta tabela.
  - **Visualização:** Uma View `view_consolidado_previsao_materiais` permitirá ver o total de insumos necessários para todas as demandas abertas (ex: "Precisamos de 500kg de Papel Pólen para a próxima semana").

### B. Processamento Assíncrono (Fila de Estoque)
O processamento real do estoque (baixa de insumos, produção de intermediários) ocorre via worker.
- **Correção Imediata:** Corrigir erro "supabase not defined" na execução manual da fila.
- **Gatilhos:**
  - `FINALIZACAO_ITEM`: Dispara a explosão da BOM para baixar o estoque real baseado no que foi produzido.
  - **Validacao:** O worker deve comparar o consumido com o previsto (da tabela nova) e alertar discrepâncias graves (opcional futuro).

## 3. Plano de Ação

### Fase 1: Correção e Estabilização (Prioridade Alta)
- [x] **Task 1.1: Fix Manual Queue Trigger**
  - Investigar e corrigir o erro `supabase not defined` ao acionar o processamento manual da fila via API (`/api/v2/demanda_producao/processar-fila-estoque`).
  - Verificar importações em `apps/api/routes/demanda_producao.py` e `demanda_producao_service.py`.
  - Adicionar logs detalhados no início e fim do processamento para facilitar debug.

### Fase 2: Arquitetura de Previsão (Forecast)
- [x] **Task 2.1: Schema Migration**
  - Criar migration SQL para tabela `previsao_consumo_demanda`.
  - Criar índices para performance (por `produto_id`, `demanda_id`).
- [x] **Task 2.2: Serviço de Previsão**
  - Criar `PrevisaoConsumoService` em `nistiprint_shared`.
  - Implementar método `gerar_previsao_para_demanda(demanda_id)`:
    - Lê a demanda e seus itens.
    - Realiza explosão da BOM (usando `BomService`).
    - Salva os registros na tabela `previsao_consumo_demanda`.
- [x] **Task 2.3: Integração no Ciclo de Vida**
  - Atualizar `DemandaProducaoService.criar_demanda` para chamar `PrevisaoConsumoService`.
  - Atualizar `DemandaProducaoService.atualizar_demanda` para recalcular a previsão (delete/insert).
- [x] **Task 2.4: Views e Relatórios**
  - Criar View SQL `view_materiais_pendentes` que agrupa `previsao_consumo_demanda` por material, subtraindo o que já foi baixado (opcional) ou apenas mostrando o total planejado.

### Fase 3: Validação e Consistência
- [x] **Task 3.1: Auditoria de Consumo**
  - Criar script/rotina para comparar `previsao_consumo_demanda` vs `estoque_movimento` (via `correlation_id` ou `demanda_id`).
  - Garantir que a `correlation_id` seja propagada corretamente da previsão até a baixa real.

## 4. Próximos Passos e Manutenção
1. **Monitoramento:** Acompanhar a fila de processamento assíncrono para garantir que as baixas de BOM estão ocorrendo sem atrasos.
2. **Auditoria Periódica:** Executar o script `scripts/audit_consumption.py` semanalmente para identificar desvios entre o planejado (previsão) e o realizado (estoque).
3. **Expansão:** Integrar a View `view_consolidado_previsao_materiais` no dashboard administrativo para facilitar a compra de insumos.
