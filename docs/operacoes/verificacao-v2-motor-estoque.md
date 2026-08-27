# Verificação V2 — o motor de estoque movimenta corretamente?

**Objetivo:** provar, com um item real, que a reconciliação de estoque produz os movimentos certos — antes de aposentar o motor legado (fase D2.1).

Por que agora: até o Sprint 4 o motor **nunca movimentou nada**, porque `itens_demanda.produto_id` era nulo em 94% dos casos e a reconciliação devolvia `item_sem_produto_mapeado`. O backfill do B1 destravou isso. Se houver defeito na cascata, é melhor descobrir com um item do que depois de remover o motor antigo.

---

## Pré-condições — já verificadas

| Verificação | Resultado |
|---|---|
| Itens com produto mapeado e ainda não finalizados | **116** |
| Desses, quantos bateriam na guarda da regra B5 | **0** — todas as fichas técnicas estão completas |
| Desses, quantos estão em demanda `RASCUNHO` | **114** |
| Saldos em `estoque_atual` | **0 linhas** — tudo será produção JIT |
| Movimentos e ledger | **0 linhas** — o "depois" é inequívoco |

Como não há saldo de nada, toda a cascata será JIT: produz o acabado, produz os intermediários e o consumo real recai sobre as matérias-primas, que ficam negativas. **Isso é o comportamento correto**, não um defeito.

---

## Item sugerido: 2436

`AGDGV_P01` · demanda 124 · status `RASCUNHO` · quantidade 1 · produto acabado com ficha técnica completa em 4 níveis.

Escolhido por ser rascunho (menor impacto), quantidade 1 (números fáceis de conferir) e por exercitar a recursão a fundo.

---

## Passo 1 — simular (não grava nada)

```sql
SELECT nivel, caminho, sku, tipo_produto, movimento, quantidade, observacao
  FROM simular_reconciliacao_item(2436);
```

Esperado: **24 linhas, 4 níveis, nenhum `BLOQUEADO`**.

Se aparecer `BLOQUEADO`, **pare**: é produto intermediário ou acabado sem ficha técnica, e a reconciliação vai falhar de propósito (regra B5). Cadastre a BOM ou escolha outro item.

## Passo 2 — foto do antes

```sql
SELECT * FROM snapshot_estoque_item(2436);
```

Esperado: todos com `saldo = 0`, `movimentos = 0`, `ledger = 0`.

## Passo 3 — finalizar o item pela tela

Produção › Demandas › demanda 124 › finalizar o item `AGDGV_P01`.

Use a tela, não SQL: o objetivo é exercitar o caminho real, do evento à reconciliação.

## Passo 4 — aguardar o worker

A tarefa `processar-eventos-producao-periodic` roda a cada **5 minutos**. Acompanhe:

```sql
SELECT created_at, status, metadata->>'result' AS resultado
  FROM task_execution_logs
 WHERE task_type = 'ESTOQUE'
 ORDER BY created_at DESC LIMIT 3;
```

Esperado no `resultado`: `'eventos_processados': 1, 'eventos_falha': 0, 'itens_reconciliados': 1`.

## Passo 5 — conferir o depois

```sql
SELECT * FROM snapshot_estoque_item(2436);
```

### Critérios de aceite

| # | Critério | Esperado |
|---|---|---|
| 1 | `movimentacoes_estoque` do item | **`SELECT sum(movimentos_gerados) FROM simular_reconciliacao_item(<id>)`** |
| 2 | `demanda_estoque_processado` do item | **≥ 1 linha** — é a coluna `ledger` do próprio `snapshot_estoque_item()` |
| 3 | Saldo das matérias-primas | negativo, batendo com o passo 1 |
| 4 | Saldo dos intermediários | 0 (PROD_INT e CONS_INT se anulam no mesmo ciclo) |
| 4b | Saldo do produto acabado | **positivo e permanece** — a saída só ocorre na coleta (ver QA-5) |
| 5 | `itens_demanda.status_processamento` | `PROCESSADO` |
| 6 | `eventos_producao_v2.processado` | `true` |

### Consumo esperado de matéria-prima (item 2436, quantidade 1)

| SKU | Quantidade |
|---|---|
| FOLHA-SULFITE-A4-75G | 54,0000 |
| WIRE-O-Rose Gold-7/8" | 10,0000 |
| COUCHE-A5-MATTE | 2,0000 |
| MP-16345860111 | 2,0000 |
| MP-16345860837 | 2,0000 |
| TASSEL-Laranja | 2,0000 |
| CANGURU | 1,0000 |
| ELASTICO-7mm-Laranja | 1,0000 |
| MP-16345864833 | 0,9180 |
| BOPP-Fosco | 0,5000 |
| MP-16354821286 | 0,3000 |
| ILHOS-Branco | 0,0002 |

Confira contra:

```sql
SELECT p.sku, sum(m.quantidade)::numeric(18,4) AS movimentado
  FROM movimentacoes_estoque m
  JOIN produtos p ON p.id = m.produto_id
 WHERE m.item_demanda_id = 2436 AND p.tipo_produto::text = 'MATERIA_PRIMA'
 GROUP BY 1 ORDER BY 1;
```

Os valores devem ser os da tabela acima com sinal negativo.

---

## Se der errado

**Desfazer.** A reconciliação carimba um `correlation_id` em tudo que grava:

```sql
-- 1. Descobrir o correlation_id
SELECT DISTINCT correlation_id FROM movimentacoes_estoque WHERE item_demanda_id = 2436;

-- 2. Reverter o saldo, apagar movimentos e ledger, e liberar o item
BEGIN;
UPDATE estoque_atual e
   SET saldo_atual = e.saldo_atual - x.delta, ultima_atualizacao = now()
  FROM (SELECT produto_id, deposito_id, sum(quantidade) delta
          FROM movimentacoes_estoque WHERE correlation_id = '<UUID>'
         GROUP BY 1,2) x
 WHERE e.produto_id = x.produto_id AND e.deposito_id = x.deposito_id;

DELETE FROM movimentacoes_estoque       WHERE correlation_id = '<UUID>';
DELETE FROM demanda_estoque_processado  WHERE correlation_id = '<UUID>';
UPDATE itens_demanda SET status_processamento = 'PENDENTE', finalizados_qtd = 0 WHERE id = 2436;
UPDATE eventos_producao_v2 SET processado = false WHERE item_demanda_id = 2436;
COMMIT;
```

Confira o resultado do `SELECT` antes de rodar o bloco — é a única parte deste roteiro que altera dados fora do fluxo normal.

**Diagnósticos comuns:**

| Sintoma | Provável causa |
|---|---|
| `itens_reconciliados: 1` mas zero movimentos | Guarda B5 ou `produto_id` nulo — rode o passo 1 de novo |
| `eventos_falha: 1` | Erro na reconciliação; veja `error_message` em `task_execution_logs` |
| Movimentos gravados, `demanda_estoque_processado` vazio | A RPC não alimentou o ledger — reprocessar duplicaria consumo. **Pare e investigue** |
| Item preso em `PROCESSANDO` | Lock não liberado; `UPDATE itens_demanda SET status_processamento='PENDENTE'` |

---

## Depois de passar

Com os seis critérios verdes, a fase **D2.1** fica liberada: aposentar `fila_processamento_estoque`, `movimentacoes_estoque` do motor legado, `estoque_atual` legado, `snapshots_reconciliacao`, `previsao_consumo_demanda` e, após a correção B2 já aplicada, `eventos_producao` (v1).


---

## Resultado da execução — item 2436, 25/08/2026

**Passou nos seis critérios.**

| Movimento | Linhas | Soma | Produtos |
|---|---|---|---|
| `CONS_MP` | 18 | −75,7182 | 12 |
| `CONS_INT` | 5 | −5,0000 | 5 |
| `PROD_INT` | 5 | +5,0000 | 5 |
| `PROD_ACAB` | 1 | +1,0000 | 1 |
| **Total** | **29** | | |

29 movimentos, **29 linhas de ledger**, 1 `correlation_id`, 18 saldos criados, item `PROCESSADO`, evento `processado = true`. As 12 matérias-primas bateram exatamente com a simulação, até `ILHOS-Branco` em −0,0002.

O balanço fecha do jeito certo: `PROD_INT` e `CONS_INT` se anulam (intermediários voltam a zero), o acabado fica com +1, e o consumo real recai sobre a matéria-prima.

### Correção na simulação

A previsão original dizia 24 movimentos. Errado: 24 era o número de ocorrências na árvore da BOM, e o motor gera **dois** movimentos por intermediário produzido JIT (`PROD_INT` + `CONS_INT`). A função ganhou a coluna `movimentos_gerados`; `sum(movimentos_gerados)` agora prevê 29, igual ao gravado.

### QA-5 · saída na coleta — resolvido em 25/08/2026

O acabado ficava com saldo +1 e nada o removia. **A intenção já existia no código e nunca funcionou:** `marcar_como_coletado` e o fluxo de conclusão enfileiravam `DEMANDA_TOTAL` via `agendar_processamento_estoque`, com o comentário "Agendar baixa final de estoque". Mas o processador da fila só trata `RECONCILIACAO_ITEM`, `ITEM_TOTAL_BOM_PROCESS`, `CONSUMO_BOM` e `ESTORNO_BOM` — `DEMANDA_TOTAL` caía num `print` de debug e era descartado em silêncio.

**Regra implementada:** a saída é registrada quando a demanda é coletada **por completo**. Coleta parcial não movimenta nada. A retirada pela expedição também não — naquele momento o produto ainda está na empresa e pode voltar ao estoque. A saída real é a coleta, quando a mercadoria sai fisicamente. Consistência vale mais que imediatismo.

| Peça | O que faz |
|---|---|
| `registrar_saida_coleta_demanda(demanda_id, user_id)` | Baixa o acabado de cada item finalizado. Recusa demanda fora de `COLETADO`; idempotente por demanda |
| Tipo `SAIDA_COLETA` | Novo tipo de movimento, acrescentado também ao CHECK do ledger |
| `collections.py` | Chama a baixa em `marcar_como_coletado` e ao status virar `COLETADO` após coleta consolidada |
| `status.py` | A baixa na **conclusão** foi removida: concluir a produção não é sair da empresa |

**Testado no item 2436** (demanda forçada a `COLETADO` e revertida em seguida):

| Chamada | Resultado |
|---|---|
| Demanda em `RASCUNHO` | `{ok: false, motivo: 'demanda_nao_coletada'}` — a guarda funciona |
| 1ª em `COLETADO` | `{ok: true, itens_baixados: 1, quantidade_total: 1}` |
| 2ª e 3ª | `{ok: true, motivo: 'ja_registrada'}` — não duplica |
| Saldo do acabado | 1 → **0**, com 2 movimentos e 2 linhas de ledger |

O estado de teste foi revertido: saldo de volta em 1, demanda em `RASCUNHO`, os 29 movimentos da V2 preservados.

---

## Teste de fumaça — motor único (D2.1, 25/08/2026)

Depois da unificação, o dashboard de produção grava estoque pelo mesmo caminho da finalização. Este roteiro confirma isso com uma etapa real.

### Antes

```sql
SELECT (SELECT count(*) FROM movimentacoes_estoque)      AS movimentos,
       (SELECT count(*) FROM demanda_estoque_processado) AS ledger,
       (SELECT count(*) FROM eventos_producao_v2)        AS eventos;
```

Anote os três números. Hoje: 29 / 29 / 2.

### Passo 1 — salvar uma etapa pelo dashboard

Produção › Demandas › escolha um item com produto mapeado e preencha **uma** etapa intermediária (por exemplo `capas_impressas_qtd`). Salve o lote.

Imediatamente depois, sem esperar o worker:

```sql
SELECT id, item_demanda_id, estagio, tipo_evento, processado, created_at
  FROM eventos_producao_v2 ORDER BY created_at DESC LIMIT 3;
```

Esperado: **uma linha nova**, `processado = false`, `estagio = 'progresso_item_atualizado'`, `tipo_evento = 'LIQUIDACAO'`.

Se não aparecer linha nenhuma, a gravação não chegou ao caminho único — pare e investigue antes de continuar.

### Passo 2 — aguardar o worker (até 5 min)

```sql
SELECT created_at, status, metadata->>'result' AS resultado
  FROM task_execution_logs WHERE task_type = 'ESTOQUE'
 ORDER BY created_at DESC LIMIT 3;
```

O resultado agora traz só `eventos_v2` — a chave `tarefas_fila` sumiu junto com o motor legado.

### Passo 3 — conferir o depois

```sql
SELECT (SELECT count(*) FROM movimentacoes_estoque)      AS movimentos,
       (SELECT count(*) FROM demanda_estoque_processado) AS ledger;
```

**O critério é a igualdade.** Movimentos e ledger têm de crescer na mesma medida. Se movimentos crescerem mais, algo ainda grava por fora do caminho único e a idempotência está furada — nesse caso, pare: reprocessar duplicaria consumo.

### Passo 4 — confirmar que a etapa parcial não duplica na finalização

Finalize o mesmo item. Confira de novo movimentos × ledger: continuam iguais, e o consumo total de cada matéria-prima bate com `simular_reconciliacao_item(<item_id>)` — **uma vez**, não duas. Era exatamente essa dupla contagem que a unificação evitou.
