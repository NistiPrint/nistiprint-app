# Correção: Bug de Duplicação de Movimentações de Estoque

## Problema Identificado

Cada operação de consumo de insumos estava sendo registrada **DUAS VEZES** no banco de dados:
- Uma execução via **fallback síncrono**
- Uma execução via **Celery worker**

### Evidências

- Intervalo entre duplicações: **3-7 segundos**
- Mesmo `correlation_id` pai no motivo das movimentações
- `correlation_ids` DIFERENTES para cada duplicação (execuções independentes)
- 12 grupos de duplicação detectados em teste recente

## Causa Raiz

Condição de corrida no método `agendar_processamento_estoque()`:

```python
# PROBLEMA: Quando forcar_sincrono=True
if forcar_sincrono or not celery_success:
    # Processa IMEDIATAMENTE (fallback síncrono)
    self.processar_insumos_por_bom_recursivo(...)

# Celery FOI DISPARADO e também vai processar
celery_app.send_task('tasks.stock_tasks.process_stock_queue', ...)
```

### Fluxo Temporal do Bug

```
T0: finalizar_item() chamado
    |
T1: agendar_processamento_estoque(forcar_sincrono=True)
    |-- Insere tarefa na fila (status=PENDENTE)
    |-- Dispara Celery (send_task)
    |-- FALLBACK SÍNCRONO (forcar_sincrono=True)
        |
        T2: processar_insumos_por_bom_recursivo() [EXECUÇÃO 1]
            |-- Gera movimentações com correlation_id=A
        |
        T3: Marca tarefa como CONCLUÍDO

EM PARALELO (Celery):
    |
T1.5: Celery recebe task
    |
T2.5: processar_fila_estoque() busca tarefas PENDENTES
    |-- Encontra a MESMA tarefa (ainda não CONCLUÍDA)
    |
T3.5: processar_insumos_por_bom_recursivo() [EXECUÇÃO 2]
    |-- Gera movimentações com correlation_id=B
    |
T4: DUAS movimentações idênticas no banco!
```

## Solução Implementada

### 1. Remover Fallback Síncrono Forçado

**Arquivo:** `packages/shared/nistiprint_shared/services/demanda_producao_service.py`

**Mudança na condição (Linha ~2304):**

```python
# DE:
if forcar_sincrono or not celery_success:

# PARA:
if not celery_success:
    # Apenas usa fallback se Celery FALHOU
```

### 2. Remover Parâmetro `forcar_sincrono=True`

**Arquivos:**
- `finalizar_item()` (Linha ~2363)
- `finalizar_item_parcial()` (Linha ~2400)

```python
# DE:
self.agendar_processamento_estoque(
    demanda_id=demanda_id,
    item_id=item_id,
    campo='ITEM_TOTAL_BOM_PROCESS',
    incremento=total_qty,
    user_id=user_id,
    forcar_sincrono=True  # REMOVER
)

# PARA:
self.agendar_processamento_estoque(
    demanda_id=demanda_id,
    item_id=item_id,
    campo='ITEM_TOTAL_BOM_PROCESS',
    incremento=total_qty,
    user_id=user_id
)
```

### 3. Adicionar Verificação de Idempotência

**Arquivo:** `processar_fila_estoque()` (Linha ~2967)

```python
# 2. VERIFICAÇÃO DE IDEMPOTÊNCIA
# Verifica se já existe movimentação de estoque para este correlation_id
t_correlation_id = tarefa.get('correlation_id')

existing_mov = supabase_db.table('movimentacoes_estoque')\
    .select('id', count='exact')\
    .eq('correlation_id', t_correlation_id)\
    .execute()

if existing_mov.data and len(existing_mov.data) > 0:
    print(f"DEBUG: Tarefa {t_correlation_id} JÁ FOI PROCESSADA (idempotência)")
    # Marca como concluído sem processar novamente
    supabase_db.table('fila_processamento_estoque')\
        .update({'status': 'CONCLUIDO', 'processed_at': get_now_iso()})\
        .eq('id', tarefa_id)\
        .execute()
    processed_count += 1
    continue
```

## Comportamento Após Correção

### Fluxo Correto

```
T0: finalizar_item() chamado
    |
T1: agendar_processamento_estoque()
    |-- Insere tarefa na fila (status=PENDENTE)
    |-- Dispara Celery (send_task)
    |-- Celery sucesso? SIM → SEM FALLBACK
    |
T2: Celery processa a tarefa
    |-- processar_fila_estoque() busca tarefas
    |-- Verifica idempotência (movimentação já existe?)
    |-- Se NÃO existe: processa
    |-- Se JÁ existe: marca CONCLUÍDO sem processar
    |
T3: UMA única movimentação no banco ✅
```

### Camadas de Proteção

1. **Sem fallback síncrono** quando Celery está disponível
2. **Verificação de idempotência** no worker antes de processar
3. **Filtro por correlation_id** nas movimentações de estoque

## Script de Teste

**Arquivo:** `scripts/teste_integridade_estoque.py`

Executa o cenário crítico:
1. Cria demanda com 1 item de 5 unidades
2. Aloca manualmente 5 miolos via dashboard
3. Finaliza o item com 5 unidades
4. Valida que componentes foram consumidos APENAS UMA VEZ

```bash
cd scripts
python teste_integridade_estoque.py
```

## Validação

Após aplicar as correções:

1. **Verificar sem duplicação:**
   ```sql
   SELECT 
     correlation_id,
     COUNT(*) as qtd_movimentacoes
   FROM movimentacoes_estoque
   WHERE created_at > NOW() - INTERVAL '1 hour'
   GROUP BY correlation_id
   HAVING COUNT(*) > 1;
   ```
   Resultado esperado: **0 linhas** (sem duplicação)

2. **Executar script de teste:**
   ```bash
   python scripts/teste_integridade_estoque.py
   ```
   Resultado esperado: **✅ SUCESSO: Teste passou sem duplicação**

3. **Verificar filas:**
   ```sql
   SELECT status, COUNT(*) 
   FROM fila_processamento_estoque 
   WHERE created_at > NOW() - INTERVAL '1 hour'
   GROUP BY status;
   ```
   Resultado esperado: Maioria **CONCLUIDO**, sem **ERRO**

## Arquivos Modificados

1. `packages/shared/nistiprint_shared/services/demanda_producao_service.py`
   - Linha ~2304: Condição do fallback síncrono
   - Linha ~2363: Remoção de `forcar_sincrono=True` em `finalizar_item()`
   - Linha ~2400: Remoção de `forcar_sincrono=True` em `finalizar_item_parcial()`
   - Linha ~2967: Adição de verificação de idempotência em `processar_fila_estoque()`

2. `scripts/teste_integridade_estoque.py` (NOVO)
   - Script de teste para validar integridade de estoque

## rollback (se necessário)

Se precisar reverter:

```python
# Restaurar fallback síncrono forçado
if forcar_sincrono or not celery_success:  # Voltar para esta condição
```

Mas **NÃO RECOMENDADO** - a correção elimina a condição de corrida.

## Lições Aprendidas

1. **Nunca processar sincronamente E assincronamente a mesma tarefa**
2. **Sempre implementar idempotência** em processamento assíncrono
3. **Usar correlation_id único** para rastreabilidade e deduplicação
4. **Testar cenários de corrida** antes de deploy em produção
