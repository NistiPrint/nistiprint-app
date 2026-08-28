# Correção de estoque — 28/08/2026

> **Status:** implementado. Decisão de arquitetura tomada: **Opção A** — alocar
> é reservar, não dar saída. As três etapas do fluxo real são
> **produção → alocação na demanda → saída física**.

Dois bugs independentes, mesmo subsistema. Bug 1 é contido. Bug 2 é uma
regressão de comportamento: a regra `[+] produz / [-] aloca` existia e foi
perdida quando a tela passou a mandar sempre `field`.

Princípio que rege tudo abaixo (confirmado pelo dono do produto):

> As alterações no dashboard da demanda **não** disparam movimentação de
> estoque imediata. A movimentação real acontece na reconciliação assíncrona,
> disparada pela finalização.

---

## Bug 1 — Coleta total não finaliza todos os itens

### Regra desejada

Ao marcar a demanda como totalmente coletada, **todos** os itens passam a
finalizados — independentemente de terem `produto_id` ou de impactarem estoque.

### Estado atual

`registrar_saida_coleta_demanda` (RPC no banco, sem migration no repositório)
percorre apenas:

```sql
FROM itens_demanda i JOIN produtos p ON p.id = i.produto_id
WHERE i.demanda_id = p_demanda_id AND i.produto_id IS NOT NULL
```

Itens sem `produto_id` nunca entram no loop, então não recebem
`finalizados_qtd` nem `status_item`. Demanda 139: 21 itens, 3 concluídos.

### Correção

**1.1 — Separar "finalizar itens" de "baixar estoque" dentro da RPC.**

Novo bloco, **antes** do loop de estoque, sem `JOIN produtos` e sem filtro de
`produto_id`:

```sql
UPDATE itens_demanda
   SET finalizados_qtd = quantidade,
       status_item     = 'Concluído',
       updated_at      = now()
 WHERE demanda_id = p_demanda_id
   AND COALESCE(quantidade, 0) > 0
   AND COALESCE(finalizados_qtd, 0) < quantidade;
```

`status_processamento = 'PENDENTE'` e o evento `LIQUIDACAO` continuam sendo
gravados **apenas** para itens com `produto_id NOT NULL` — item sem produto não
tem o que reconciliar, e enfileirá-lo só gera ruído no consolidador.

O loop de baixa (`SAIDA_COLETA`) permanece exatamente como está, restrito aos
itens mapeados.

**1.2 — Devolver e registrar a lacuna.**

A RPC já retorna `itens_sem_produto_mapeado`. Adicionar
`itens_finalizados_sem_estoque` ao retorno e, em
`_registrar_saida_por_coleta` (`packages/shared/nistiprint_shared/services/demanda/collections.py`),
logar `WARNING` quando esse número for `> 0` — hoje o código só olha para
`ok=false`, e a RPC retorna `ok=true` mesmo ignorando 20 de 21 itens.

**1.3 — Versionar a RPC.**

Criar `supabase/migrations/20260828xxxxxx_coleta_finaliza_todos_os_itens.sql`
com o `CREATE OR REPLACE FUNCTION` completo. Hoje a função existe só no banco
de produção — qualquer `db reset` a perde.

**1.4 — Backfill.**

Rodar a RPC corrigida para as demandas já em `COLETADO` com itens pendentes.
Como o bloco de baixa é idempotente (`SELECT count(*) ... SAIDA_COLETA`), ele
não duplica movimentação; só o `UPDATE` de finalização terá efeito.

### Fora de escopo (mas registrado)

`itens_demanda.contabiliza_estoque` — default `false`, 3 linhas `true` em
1.649, nenhuma linha de Python lê ou escreve. Coluna morta. Decidir em separado
se vira a chave oficial de "este item movimenta estoque" ou se sai do schema.

---

## Bug 2 — Controle de Produção não dá entrada no estoque

### Regra desejada

| Botão | Efeito                                                                 |
|-------|------------------------------------------------------------------------|
| `[+]` | Produção imediata do produto: **entrada no estoque** + consumo da BOM.  |
| `[-]` | Aloca estoque existente numa demanda: preenche a coluna "Miolo pronto". |

### Estado atual

**`[+]` está fazendo o trabalho do `[-]`.**

`ControleProducaoPage.jsx:145-148` sempre define `field`. Em
`producao_api.py:61-64`, a presença de `field` desvia para
`processar_alocacao_avulsa_otimizado` — que distribui a quantidade entre itens
de demandas ativas. O ramo `else`, `ordem_producao_service.registrar_producao_imediata`
(que chama `estoque_service.registrar_entrada` + BOM), virou código morto.

Resultado observado no banco (miolo 75, 27/08): `PROD_INT +1` seguido de
`CONS_INT -1`, mesmo `correlation_id`. Saldo líquido zero, matéria-prima
debitada. O miolo produzido nunca fica em estoque.

Três efeitos colaterais no mesmo caminho:

- Sem demanda ativa compatível, retorna `status: 'sem_alvo'` e **nada** é
  gravado — mas a API responde `{'success': True, 'message': 'Produção registrada!'}`,
  descartando o `result`. O `result.warning` que o frontend já trata nunca chega.
- Produzir para estoque (sem demanda) é impossível pela tela.
- `logs_producao_diaria` está vazia — o "produzido hoje" da tela é sempre 0.

### Correção

**2.1 — `[+]` volta a ser produção.**

Frontend (`ControleProducaoPage.jsx`, `handleProduction`): parar de enviar
`field`. A entrada é do produto, não de um estágio de demanda.

Backend (`producao_api.py`, `registrar_item_producao`): manter a bifurcação por
`field` apenas por compatibilidade, mas o caminho do `[+]` passa a ser
`ordem_producao_service.registrar_producao_imediata(produto_id, qtd, data, user, sincrono=True)`,
que já faz o correto: `registrar_entrada` + `processar_insumos_por_bom_recursivo`
com `tipo_operacao='PRODUCAO_AVULSA'` (item **fica** no estoque).

**2.2 — A API para de mentir.**

`registrar_item_producao` hoje descarta `result`. Passar a devolver
`status`, `quantidade_alocada`, `quantidade_nao_alocada` e um `warning` quando
`status != 'success'`. O frontend já sabe exibir `result.warning`.

**2.3 — Log diário: nada a fazer.**

`registrar_producao_imediata` **já** grava em `logs_producao_diaria`. A tabela
estava vazia porque a função nunca era chamada. Corrigido o roteamento do `[+]`,
o contador "produzido hoje" volta a funcionar sozinho.

**2.4 — `[-]`: decisão pendente (ver abaixo).**

**2.5 — Testes.**

`packages/shared/tests/services/` já tem a estrutura. Cobrir:

- `[+]` gera `ENTRADA`/`PROD_INT` positiva e `CONS_MP` da BOM; saldo do produto sobe.
- `[+]` sem demanda ativa não falha e ainda soma estoque.
- `[-]` preenche `miolos_prontos_retirada_qtd` e respeita saldo insuficiente.
- Finalização após `[+]` + `[-]` consome o miolo **uma vez só**.
- Coleta total finaliza item sem `produto_id` sem gerar movimentação.

---

## Opção A — alocar é reservar (implementado)

O `[-]` chamava `estoque_service.registrar_saida`: baixa física imediata.
Depois, na finalização, o motor explodia a BOM e consumia o mesmo componente
outra vez — o ledger `demanda_estoque_processado` não registrava a baixa da
tela, então nada impedia a repetição. Dupla baixa, e contra o princípio de que
o dashboard não movimenta estoque na hora.

O desenho novo tem três pontos:

**Alocação (`[-]`)** — `demanda_alocacao/estoque.py :: reservar_alocacao_para_demanda`.
Incrementa `estoque_atual.reservado` e grava uma linha `PENDENTE` por item em
`demanda_alocacoes_estoque` (tabela que já existia e estava sem uso). O saldo
físico não se move. `estoque_atual.disponivel` é coluna gerada
(`saldo_atual - reservado`), então o disponível cai sozinho — a tela, que já
exibe `quantidade_disponivel`, reage na hora sem mudança de query.

**Consumo da reserva** — `demanda_alocacao/estoque.py :: consumir_alocacoes_do_item`,
chamado por `motor_reconciliacao_estoque.reconcile_item` logo depois do cálculo
de deltas e **antes** de qualquer leitura de saldo. Sem esse passo o motor veria
`disponível = 0` para um produto reservado justamente para aquele item e
produziria JIT um segundo componente por cima do que já estava separado.

**Saída física** — acontece uma única vez, na explosão de BOM da reconciliação,
sobre o saldo que a liberação acabou de devolver.

Falha ao consumir alocação é logada e não derruba a reconciliação: a produção é
o fato, a reserva é contabilidade.

## As três portas da tela de Controle de Produção

| Ação | O que faz | Estoque |
|---|---|---|
| `[+]` **Produz** | Produção imediata do item | **Entrada** + consumo da BOM |
| `[-]` **Aloca** | Reserva o item para uma demanda | `reservado` sobe, disponível cai, físico não se move |
| **Saída avulsa** | Baixa imediata, sem demanda | **Saída** definitiva, na hora |

A saída avulsa (`POST /producao/registrar-saida-estoque`) é para o que sai sem
ser para uma demanda: perda, amostra, uso interno, venda fora do fluxo. Não
gera reserva e não passa por reconciliação — a baixa é definitiva no clique.

Duas guardas:

- A rota **recusa** `demanda_id`. Ela aceitava esse parâmetro e chamava
  `associar_saida_a_demanda` depois da baixa; com a alocação virando reserva
  isso viraria dupla contagem (sairia aqui e sairia de novo na reconciliação).
  Vínculo com demanda agora é exclusivamente `/demanda_producao/registrar-saida`.
- A checagem é sobre o **disponível**, não sobre o saldo físico: o que está
  reservado para uma demanda não pode ser levado por uma saída avulsa.

Na UI a saída avulsa é um **destino de primeira classe** dentro do modal do
`[-]`: aparece logo acima da lista de demandas, com a mesma afordância de
seleção, em tom destrutivo. O operador clica `[-]`, informa a quantidade e ali
mesmo escolhe entre uma demanda e a saída avulsa — a pergunta que o modal faz é
"para onde vão estas N unidades?", e a avulsa é uma das respostas possíveis, não
uma ação escondida no rodapé. A confirmação explica que a baixa é imediata e
sem reconciliação.

## O que foi feito

| # | Item | Estado |
|---|---|---|
| 1.1 | RPC separa finalização (todos os itens) de baixa (só mapeados) | feito |
| 1.2 | `_registrar_saida_por_coleta` alerta sobre itens sem produto | feito |
| 1.3 | RPC versionada em `supabase/migrations/` | feito |
| 1.4 | Backfill da demanda 139 | feito — 21/21 itens concluídos |
| 2.1 | `[+]` volta a ser produção imediata | feito |
| 2.2 | API devolve `status`/`warning` reais | feito |
| 2.3 | Log diário | já existia; volta a funcionar com 2.1 |
| A | `[-]` reserva em vez de baixar | feito |
| 2.5 | Testes | 6 testes novos, verdes |
| 3 | Saída avulsa na tela de Controle de Produção | feito |

Achado extra durante o backfill: um item podia ter `finalizados_qtd` completo e
`status_item` ainda `'Em Andamento'` (item 2685 da demanda 139). O `UPDATE` da
RPC passou a alcançar também esse caso (`status_item IS DISTINCT FROM 'Concluído'`),
mas sem enfileirar evento para ele — o array de reconciliação é capturado antes
do `UPDATE` e cobre só quem tinha produção em atraso **e** produto mapeado.

Backfill verificado: 1ª execução finalizou 17 itens, 2ª finalizou o item de
status divergente, 3ª finalizou 0. Idempotente, sem movimentação nova.

## Ainda em aberto

- **1.526 itens sem `produto_id`.** Agora são finalizados corretamente, mas
  continuam fora de qualquer regra de estoque. A view `v_itens_demanda_mapeamento`
  já marca `precisa_cadastro`; o caminho é cadastrar os SKUs Shopee em `produtos`.
- **`itens_demanda.contabiliza_estoque`** — coluna morta (default `false`, 3 de
  1.649 linhas `true`, nenhum código lê ou escreve). Decidir se vira a chave
  oficial ou se sai do schema.
- **Verificação em ambiente real** do ciclo completo `[+] → [-] → finalização`,
  conferindo que o miolo entra no estoque, fica reservado e sai uma única vez.

## Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `supabase/migrations/20260828120000_coleta_finaliza_todos_os_itens.sql` | RPC `registrar_saida_coleta_demanda` versionada e corrigida |
| `packages/shared/nistiprint_shared/services/demanda/collections.py` | `_registrar_saida_por_coleta`: log de itens não mapeados |
| `apps/frontend/src/pages/producao/ControleProducaoPage.jsx` | `handleProduction`: parar de enviar `field` |
| `apps/api/routes/producao_api.py` | `registrar_item_producao`: rota do `[+]` + resposta honesta |
| `packages/shared/nistiprint_shared/services/demanda_alocacao/estoque.py` | `reservar_alocacao_para_demanda` e `consumir_alocacoes_do_item` |
| `packages/shared/nistiprint_shared/services/demanda_producao_service.py` | fachada dos dois métodos novos |
| `packages/shared/nistiprint_shared/services/motor_reconciliacao_estoque.py` | consome reservas do item antes de ler saldo |
| `apps/api/routes/demanda_producao_api.py` | `[-]` reserva em vez de dar saída |
| `apps/api/routes/producao_api.py` | `registrar-saida-estoque` vira avulsa-only, com checagem de disponível |
| `apps/frontend/src/services/ProductionService.js` | `registerStandaloneRemoval` |
| `packages/shared/tests/services/test_alocacao_reserva_producao.py` | 6 testes novos |
