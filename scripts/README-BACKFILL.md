# Scripts de Backfill - Refatoração de Arquitetura

Esta pasta contém scripts para popular dados nas novas estruturas criadas durante a refatoração.

---

## 📋 Scripts Disponíveis

### 1. `backfill_channel_snapshot.py`

Popula o campo `channel_snapshot` em `pedidos` e `demandas_producao` existentes.

**Quando executar:** Após a migration `20260401000003_channel_snapshot.sql`

**Uso:**
```bash
# Processar todos os registros (padrão)
python scripts/backfill_channel_snapshot.py

# Processar apenas pedidos
python scripts/backfill_channel_snapshot.py --table pedidos

# Processar apenas demandas
python scripts/backfill_channel_snapshot.py --table demandas

# Simular sem modificar dados (dry-run)
python scripts/backfill_channel_snapshot.py --dry-run

# Processar em lotes de 5000 registros
python scripts/backfill_channel_snapshot.py --batch-size 5000

# Processar apenas 10000 registros (útil para teste)
python scripts/backfill_channel_snapshot.py --max-records 10000
```

**Opções:**
| Opção | Descrição | Padrão |
|-------|-----------|--------|
| `--batch-size` | Tamanho do lote | 1000 |
| `--max-records` | Máximo de registros para processar | Todos |
| `--dry-run` | Apenas simular, não salva | False |
| `--table` | Tabela: `pedidos`, `demandas` ou `all` | `all` |

**O que o script faz:**
1. Busca todos os canais de venda e cria cache
2. Para cada pedido/demanda sem `channel_snapshot`:
   - Busca dados do canal (`flex`, `fulfillment`, `horario_coleta`, `color`, `nome`)
   - Cria snapshot JSON
   - Atualiza registro no banco
   - Para pedidos: corrige `is_flex` se necessário

**Tempo estimado:**
- ~10.000 registros: 1-2 minutos
- ~100.000 registros: 10-15 minutos
- ~1.000.000 registros: 1-2 horas

---

### 2. `backfill_external_ids.py`

Migra `pedidos.codigo_pedido_externo` para `vinculos_integracao_pedido`.

**Quando executar:** Após a migration `20260401000004_consolidate_external_ids.sql`

**Uso:**
```bash
# Migrar todos os registros
python scripts/backfill_external_ids.py

# Simular sem modificar dados (dry-run)
python scripts/backfill_external_ids.py --dry-run

# Processar em lotes de 5000 registros
python scripts/backfill_external_ids.py --batch-size 5000

# Migrar e verificar resultado
python scripts/backfill_external_ids.py --verify
```

**Opções:**
| Opção | Descrição | Padrão |
|-------|-----------|--------|
| `--batch-size` | Tamanho do lote | 1000 |
| `--dry-run` | Apenas simular, não salva | False |
| `--verify` | Verificar migração após backfill | False |

**O que o script faz:**
1. Busca pedidos com `codigo_pedido_externo` não nulo
2. Para cada pedido:
   - Verifica se já existe vínculo em `vinculos_integracao_pedido`
   - Se não existir, cria novo vínculo com:
     - `pedido_id`
     - `plataforma` (derivado de `origem`)
     - `id_na_plataforma` (código externo)
     - `dados_brutos` (metadados da migração)

**Verificação:**
O script pode verificar se a migração foi completa:
- Conta pedidos que ainda têm `codigo_pedido_externo`
- Verifica se têm vínculo correspondente
- Reporta percentual migrado

**Tempo estimado:**
- ~10.000 registros: 2-3 minutos
- ~100.000 registros: 20-30 minutos
- ~1.000.000 registros: 3-5 horas

---

## 🔧 Pré-requisitos

1. **Variáveis de ambiente configuradas:**
   ```bash
   # .env ou variáveis do sistema
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_SERVICE_KEY=your-service-key
   ```

2. **Migrations aplicadas:**
   ```bash
   # Verificar se migrations foram aplicadas
   supabase db remote commit
   ```

3. **Python 3.10+:**
   ```bash
   python --version
   ```

4. **Dependências instaladas:**
   ```bash
   pip install -r requirements.txt
   ```

---

## 📊 Ordem de Execução

Execute os scripts na seguinte ordem:

```bash
# 1. Após migration 20260401000003_channel_snapshot.sql
python scripts/backfill_channel_snapshot.py --table pedidos --batch-size 5000
python scripts/backfill_channel_snapshot.py --table demandas --batch-size 5000

# 2. Após migration 20260401000004_consolidate_external_ids.sql
python scripts/backfill_external_ids.py --batch-size 5000 --verify
```

---

## ⚠️ Importante

### Dry-Run
Sempre execute com `--dry-run` primeiro para verificar quantos registros serão afetados:

```bash
python scripts/backfill_channel_snapshot.py --dry-run
python scripts/backfill_external_ids.py --dry-run
```

### Batch Size
Ajuste o `--batch-size` conforme a capacidade do banco:
- **Produção:** 1000-5000 (conservador)
- **Desenvolvimento:** 5000-10000 (mais rápido)

### Monitoramento
Os scripts logam progresso a cada:
- 10.000 registros (channel_snapshot)
- 5.000 registros (external_ids)

Monitore os logs para verificar se não há erros.

### Rollback
Em caso de problema:
1. Interrompa o script (Ctrl+C)
2. Registros já processados **não** são revertidos automaticamente
3. Para rollback manual, use SQL:

```sql
-- Rollback channel_snapshot
UPDATE pedidos SET channel_snapshot = NULL WHERE ...;
UPDATE demandas_producao SET channel_snapshot = NULL WHERE ...;

-- Rollback external_ids
DELETE FROM vinculos_integracao_pedido 
WHERE dados_brutos->>'migrated_from' = 'pedidos.codigo_pedido_externo';
```

---

## 🐛 Troubleshooting

### Erro: "Connection timeout"
**Solução:** Aumente o timeout ou reduza o batch size:
```bash
python scripts/backfill_channel_snapshot.py --batch-size 500
```

### Erro: "Rate limit exceeded"
**Solução:** Adicione delay entre batches (modifique o script):
```python
import time
time.sleep(1)  # 1 segundo entre batches
```

### Script muito lento
**Solução:** Aumente o batch size (se o banco aguentar):
```bash
python scripts/backfill_channel_snapshot.py --batch-size 10000
```

### Erro: "Column does not exist"
**Solução:** Verifique se as migrations foram aplicadas:
```bash
supabase db remote commit
# Ou aplique manualmente
psql -f supabase/migrations/20260401000003_channel_snapshot.sql
```

---

## 📈 Performance

### Otimizações Implementadas

1. **Cache de canais:** Busca todos os canais uma vez e mantém em memória
2. **Batch processing:** Processa em lotes para evitar memory overflow
3. **Offset pagination:** Usa range para paginação eficiente
4. **Skip já processados:** Verifica se `channel_snapshot` já existe

### Métricas Esperadas

| Registros | Channel Snapshot | External IDs |
|-----------|-----------------|--------------|
| 10.000 | 1-2 min | 2-3 min |
| 100.000 | 10-15 min | 20-30 min |
| 1.000.000 | 1-2 horas | 3-5 horas |

---

## 📝 Exemplo de Log

```
2026-04-01 14:00:00 - BackfillChannelSnapshot - INFO - ============================================================
2026-04-01 14:00:00 - BackfillChannelSnapshot - INFO - BACKFILL DE CHANNEL SNAPSHOT
2026-04-01 14:00:00 - BackfillChannelSnapshot - INFO - ============================================================
2026-04-01 14:00:00 - BackfillChannelSnapshot - INFO - Buscando canais de venda para cache...
2026-04-01 14:00:01 - BackfillChannelSnapshot - INFO - Cache de canais: 15 registros
2026-04-01 14:00:01 - BackfillChannelSnapshot - INFO - Processando lote de 1000 pedidos (offset=0)
2026-04-01 14:00:05 - BackfillChannelSnapshot - INFO - Lote atualizado: 950 registros
2026-04-01 14:00:05 - BackfillChannelSnapshot - INFO - Progresso: 1000 processados, 950 atualizados, 50 pulados
...
2026-04-01 14:15:00 - BackfillChannelSnapshot - INFO - Backfill de pedidos concluído: {'processed': 100000, 'updated': 95000, 'skipped': 5000, 'errors': 0}
```

---

## 📚 Referências

- `docs/REFACTORING-SUMMARY.md` - Resumo completo da refatoração
- `supabase/migrations/20260401*.sql` - Migrations relacionadas
- `packages/shared/nistiprint_shared/services/` - Serviços atualizados
