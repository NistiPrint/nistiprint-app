**MOTOR DE GERENCIAMENTO DE ESTOQUE**

*Projeto Técnico · Controle de Produção para Fábrica de Papelaria*

Versão 1.0 · Documento de Especificação e Lógica

# **1\. Visão Geral e Objetivo**

Este documento especifica o **Motor de Gerenciamento de Estoque (MGE)** — o núcleo lógico responsável por calcular, reconciliar e registrar todas as movimentações de estoque de uma fábrica de papelaria que vende em marketplaces.

O principal desafio que este motor resolve é a **atualização assíncrona e fora de ordem** dos estágios de produção pelos diferentes setores, mantendo a integridade do estoque sem permitir quantidades negativas em produtos intermediários.

## **1.1 Problema Central**

| Sintoma                                                     | Causa Raiz                                         | Solução no MGE                                                                         |
| ----------------------------------------------------------- | -------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Estoque de produtos intermediários ficando negativo        | Lançamentos síncronos sem verificação de saldo | Regra: intermediários nunca ficam negativos — se não há estoque, registra produção |
| Cálculo errado quando etapas são puladas                  | Sistema dependia de ordem sequencial perfeita      | Reconciliação por diferença: compara estado esperado vs. já registrado               |
| Processos assíncronos 'perdiam' movimentações síncronas | Ausência de ledger de movimentações por demanda | Ledger atômico por (demanda, produto, etapa)                                            |
| Item finalizado sem etapas preenchidas                      | Sem lógica de cascata retroativa                  | Algoritmo de liquidação explode BOM e calcula tudo de uma vez                          |

# **2\. Premissas do Sistema**

## **2.1 Premissas de Negócio**

* **P1 — Produtos intermediários nunca têm estoque negativo.** Uma capa impressa, capa produzida ou miolo são artefatos físicos. Se o sistema calcularia um saldo negativo, significa que houve produção não registrada — o sistema deve criar um lançamento de produção compensatório.
* **P2 — Matérias-primas podem ter saldo negativo.** Sulfite, tinta, folha adesiva, papelão etc. podem ir negativos, indicando erro de contagem no inventário físico. Isso é aceitável e rastreável.
* **P3 — A Finalização é o evento de liquidação.** Quando o Setor 4 marca X unidades como finalizadas, esse é o gatilho que consolida todo o consumo de estoque daquela quantidade. É o único momento em que o BOM completo é calculado.
* **P4 — Atualizações intermediárias são sinais, não transações definitivas.** Quando o Setor 1 registra '50 capas impressas', isso é um sinal de progresso, não um consumo definitivo de estoque. O consumo real é calculado na finalização.
* **P5 — O motor opera sobre deltas, não sobre totais absolutos.** Ao processar uma finalização, o motor compara o que JÁ foi consumido/produzido contra o que É NECESSÁRIO, e lança apenas a diferença.
* **P6 — Cada demanda tem seu próprio contexto de ledger.** Movimentações de estoque são sempre associadas a (demanda\_id \+ produto\_id \+ tipo\_movimento), evitando colisão entre demandas simultâneas.
* **P7 — Estoque reservado não é estoque consumido.** A reserva garante disponibilidade na demanda, mas só é efetivada (baixada) quando há finalização ou produção confirmada.

## **2.2 Premissas Técnicas**

* **P8 — Idempotência:** Re-executar o cálculo de uma finalização com os mesmos dados deve sempre produzir o mesmo resultado. O motor verifica o que já foi registrado antes de lançar.
* **P9 — Atomicidade:** Todo o conjunto de movimentações de uma finalização é processado em uma única transação. Falha parcial \= rollback total.
* **P10 — Auditabilidade:** Toda movimentação registra: origem (demanda, setor, etapa), timestamp, quantidade, tipo (consumo/produção/reserva/liberação) e saldo resultante.
* **P11 — BOM multinível:** O motor explode o BOM recursivamente até chegar nas matérias-primas, respeitando a hierarquia definida no cadastro de produtos.

# **3\. Glossário e Modelo de Dados Conceitual**

## **3.1 Entidades Principais**

| Entidade                    | Descrição                                                                                                      |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Demanda                     | Consolidação de pedidos de venda. Ex: 'Produzir 200 Agendas A5'. Tem um ID único e lista de itens de demanda. |
| Item de Demanda             | Um produto específico dentro de uma demanda com quantidade alvo. Ex: 'Agenda A5 × 200'.                        |
| Produto                     | Qualquer item do sistema: produto acabado, intermediário ou matéria-prima. Todo produto tem um tipo.           |
| BOM (Bill of Materials)     | Lista de materiais de um produto. Multinível: Agenda → Capa → Papelão, Tinta, etc.                           |
| Nó BOM                     | Um componente em um nível do BOM. Contém: produto\_pai, produto\_filho, quantidade\_por\_unidade.              |
| Estoque                     | Saldo atual de um produto. Separado por: disponível, reservado, comprometido.                                   |
| Ledger de Movimentação    | Registro histórico de cada entrada/saída de estoque por produto, demanda e etapa.                              |
| Evento de Produção        | Registro de atualização feito por um setor: (demanda, etapa, quantidade, timestamp).                           |
| Snapshot de Reconciliação | Estado calculado pelo motor antes de lançar movimentações, mostrando o delta necessário.                     |

## **3.2 Tipos de Produto**

| Tipo                      | Exemplos                                                    | Pode ir negativo? | Produzido internamente? |
| ------------------------- | ----------------------------------------------------------- | :---------------: | :---------------------: |
| **MATÉRIA-PRIMA**  | Sulfite, tinta, folha adesiva, papelão, espiral, plástico |   **SIM**   |          NÃO          |
| **INTERMEDIÁRIO**  | Capa impressa, capa produzida, miolo impresso               |  **NÃO**  |           SIM           |
| **PRODUTO ACABADO** | Agenda A5, Caderno, Bloco                                   |  **NÃO**  |           SIM           |

## **3.3 Tipos de Movimentação**

| Código      | Nome                         | Efeito no Saldo               | Quando Ocorre                                                  |
| ------------ | ---------------------------- | ----------------------------- | -------------------------------------------------------------- |
| CONS\_MP     | Consumo de Matéria-Prima    | −                            | Finalização ou confirmação de produção de intermediário |
| PROD\_INT    | Produção de Intermediário | \+                            | Quando motor detecta que intermediário não havia em estoque  |
| CONS\_INT    | Consumo de Intermediário    | −                            | Quando intermediário é usado na etapa seguinte               |
| PROD\_ACAB   | Produção de Acabado        | \+                            | Quando Setor 4 finaliza itens                                  |
| RESERVA      | Reserva de Estoque           | − disponível /\+ reservado  | Quando demanda é criada/aprovada                              |
| LIB\_RESERVA | Liberação de Reserva       | \+ disponível / − reservado | Quando reserva é consumida ou cancelada                       |
| AJUSTE       | Ajuste de Inventário        | \+/−                         | Correção manual com justificativa                            |

# **4\. Etapas do Processo de Produção**

Cada etapa do processo gera Eventos de Produção que são armazenados, mas só se convertem em movimentações de estoque definitivas no momento da reconciliação (finalização).

| ID Etapa | Setor   | Nome             | Campos Atualizados     | Produto Associado                    |
| -------- | ------- | ---------------- | ---------------------- | ------------------------------------ |
| E1       | Setor 1 | Capas Impressas  | qtd\_capas\_impressas  | Capa Impressa (INTERMEDIÁRIO)       |
| E2       | Setor 2 | Capas Produzidas | qtd\_capas\_produzidas | Capa Produzida (INTERMEDIÁRIO)      |
| E3       | Setor 1 | Capas Prontas    | qtd\_capas\_prontas    | Capa Produzida (aguardando retirada) |
| E4       | Setor 3 | Miolos Prontos   | qtd\_miolos\_prontos   | Miolo (INTERMEDIÁRIO)               |
| E5       | Setor 4 | Capas Retiradas  | qtd\_capas\_retiradas  | Capa Produzida (em montagem)         |
| E6       | Setor 4 | Miolos Retirados | qtd\_miolos\_retirados | Miolo (em montagem)                  |
| E7       | Setor 4 | Finalizados      | qtd\_finalizados       | Produto Acabado → LIQUIDAÇÃO      |

| ⚡ Ponto Crítico — Etapa E7 (Finalização) A finalização (E7) é o único evento que dispara o Motor de Reconciliação de Estoque (MRE). Todas as etapas anteriores apenas registram progresso. É na finalização que o motor calcula a diferença entre o que foi consumido/produzido e o que o BOM exige, e lança os movimentos de estoque compensatórios. |
| :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

# **5\. Arquitetura do Motor de Reconciliação de Estoque (MRE)**

## **5.1 Fluxo Geral do Motor**

| Fase             | Nome                             | Descrição                                                                                                                                                       |
| ---------------- | -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **FASE 1** | Explosão do BOM                 | Para os X itens finalizados, expande recursivamente o BOM e calcula a quantidade necessária de cada produto (MP e intermediários).                              |
| **FASE 2** | Leitura do Ledger                | Lê todos os movimentos já registrados para esta demanda+produto. Calcula o saldo já consumido/produzido por esta demanda.                                      |
| **FASE 3** | Cálculo do Delta                | Necessário − Já Registrado\= Delta a Lançar. Se delta ≤ 0, não há nada a fazer para aquele produto.                                                        |
| **FASE 4** | Verificação de Disponibilidade | Para cada produto no delta: verifica saldo em estoque. Para intermediários: se não há saldo, gera PROD\_INT. Para MP: sempre gera CONS\_MP (pode ir negativo). |
| **FASE 5** | Liberação de Reserva           | Lança LIB\_RESERVA para converter a reserva em consumo efetivo.                                                                                                  |
| **FASE 6** | Registro Atômico                | Persiste todos os movimentos em uma única transação. Atualiza saldos de estoque. Registra snapshot de reconciliação.                                         |

## **5.2 Pseudocódigo do Algoritmo Central**

| function processarFinalizacao(demanda\_id, item\_id, qtd\_finalizada):   // FASE 1 — Explosão do BOM   bom\_necessario \= explodirBOM(produto\_id, qtd\_finalizada)   // { 'capa\_impressa': 1×qtd, 'sulfite': 80×qtd, 'tinta': 0.05×qtd, ... }   // FASE 2 — Leitura do Ledger da Demanda   ja\_registrado \= lerLedger(demanda\_id, item\_id)   // { 'capa\_impressa': 50, 'sulfite': 4000, ... } ← já consumido nessa demanda   // FASE 3 — Cálculo do Delta   delta \= {}  // o que ainda falta registrar   para cada produto em bom\_necessario:     delta\[produto\] \= bom\_necessario\[produto\] − ja\_registrado.get(produto, 0\)     se delta\[produto\] ≤ 0: ignorar (já foi processado)   // FASE 4 — Verificação e Geração de Movimentos   movimentos \= \[\]   para cada (produto, qtd\_delta) em delta:     saldo \= buscarSaldoEstoque(produto)     se produto.tipo \== INTERMEDIÁRIO:       qtd\_disponivel \= min(saldo.disponivel, qtd\_delta)       qtd\_faltando   \= qtd\_delta − qtd\_disponivel       se qtd\_disponivel \> 0: movimentos \+= CONS\_INT(produto, qtd\_disponivel)       se qtd\_faltando \> 0:  movimentos \+= PROD\_INT(produto, qtd\_faltando) // produção compensatória                              // depois explode BOM do intermediário faltando →                              // consumir MPs dele recursivamente     se produto.tipo \== MATÉRIA\_PRIMA:       movimentos \+= CONS\_MP(produto, qtd\_delta) // pode gerar saldo negativo   // FASE 5 e 6 — Liberação de Reserva e Persistência Atômica   movimentos \+= liberarReservas(demanda\_id, bom\_necessario)   movimentos \+= PROD\_ACAB(produto\_acabado, qtd\_finalizada)   persistirAtomico(movimentos, snapshot\_reconciliacao) |
| :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

# **6\. Explosão de BOM — Exemplo Prático (Agenda A5)**

Estrutura hierárquica do produto 'Agenda A5' com quantidades por unidade:

| Nível | Produto                     | Tipo    | Qtd / unidade pai | Qtd p/ 100 Agendas |
| :----: | --------------------------- | ------- | ----------------- | :----------------: |
|   0   | **Agenda A5**         | ACABADO | —                |   **100**   |
|   1   | └ Capa Produzida A5        | INTERM. | 1                 |        100        |
|   2   | └ Capa Impressa A5         | INTERM. | 1                 |        100        |
|   3   | └ Folha Adesiva A5         | MP      | 1 folha           |     100 folhas     |
|   3   | └ Tinta (impressão capa)  | MP      | 0.003 L           |       0.3 L       |
|   2   | └ Papelão A5              | MP      | 2 folhas          |     200 folhas     |
|   2   | └ Cola / acabamento        | MP      | 0.005 kg          |       0.5 kg       |
|   1   | └ Miolo A5                 | INTERM. | 1                 |        100        |
|   2   | └ Sulfite A5 (80 fls)      | MP      | 80 fls            |     8.000 fls     |
|   2   | └ Tinta (impressão miolo) | MP      | 0.015 L           |       1.5 L       |
|   1   | └ Espiral A5               | MP      | 1 un              |       100 un       |
|   1   | └ Embalagem plástica      | MP      | 1 un              |       100 un       |

**Resultado da explosão para 100 Agendas A5:** O motor gera um mapa plano com os totais acumulados de cada produto em todos os níveis.

# **7\. Cenários de Exemplo**

Os cenários abaixo demonstram o comportamento do motor em situações reais, do mais simples ao mais complexo.

## **Cenário A — Fluxo Perfeito (ordem correta, sem estoque prévio)**

| Contexto Demanda: 100 Agendas A5. Nenhuma etapa preenchida anteriormente. Usuários preenchem na ordem exata E1→E2→E3→E4→E5→E6→E7. |
| :--------------------------------------------------------------------------------------------------------------------------------------- |

| Evento | Setor | Registrado            | Ação do Motor                    | Movimento de Estoque    |
| ------ | ----- | --------------------- | ---------------------------------- | ----------------------- |
| E1     | S1    | 100 capas impressas   | Registra evento, NÃO move estoque | Nenhum ainda            |
| E2     | S2    | 100 capas produzidas  | Registra evento, NÃO move estoque | Nenhum ainda            |
| E3     | S1    | 100 capas prontas     | Registra evento, NÃO move estoque | Nenhum ainda            |
| E4     | S3    | 100 miolos prontos    | Registra evento, NÃO move estoque | Nenhum ainda            |
| E5-6   | S4    | 100 retiradas de cada | Registra evento, NÃO move estoque | Nenhum ainda            |
| E7 ⚡  | S4    | 100 finalizados       | DISPARA MOTOR DE RECONCILIAÇÃO   | **Ver abaixo ↓** |

**Motor na E7 — Resultado da Reconciliação:**

| Produto        | Necessário | Já Registrado | Delta     | Movimento Gerado                              |
| -------------- | ----------- | -------------- | --------- | --------------------------------------------- |
| Capa Impressa  | 100         | 0              | 100       | Sem estoque → PROD\_INT 100 \+ CONS\_INT 100 |
| Capa Produzida | 100         | 0              | 100       | Sem estoque → PROD\_INT 100 \+ CONS\_INT 100 |
| Miolo A5       | 100         | 0              | 100       | Sem estoque → PROD\_INT 100 \+ CONS\_INT 100 |
| Folha Adesiva  | 100         | 0              | 100       | CONS\_MP −100 fls                            |
| Tinta capa     | 0.3 L       | 0              | 0.3 L     | CONS\_MP −0.3 L                              |
| Papelão       | 200 fls     | 0              | 200 fls   | CONS\_MP −200 fls                            |
| Sulfite        | 8.000 fls   | 0              | 8.000 fls | CONS\_MP −8.000 fls                          |
| Espiral        | 100 un      | 0              | 100 un    | CONS\_MP −100 un                             |
| Agenda A5      | —          | —             | —        | PROD\_ACAB \+100 un                           |

*Nota: No Cenário A, o motor gera PROD\_INT para todos os intermediários porque não havia saldo em estoque. Isso é correto — a produção ocorreu, mas como os lançamentos intermediários eram só sinais, o motor reconstitui a cadeia completa na finalização.*

## **Cenário B — Item finalizado sem nenhuma etapa preenchida**

| Contexto Demanda: 50 Cadernos B5. O Setor 4 marca diretamente 50 como finalizados sem que nenhuma outra etapa tenha sido registrada. O motor deve calcular toda a cadeia do zero. |
| :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

**Comportamento esperado:** O motor não tem nenhum evento anterior para consultar. O delta \= necessário − 0 \= necessário total. O motor explode o BOM completo e gera todos os movimentos como se fosse o Cenário A.

| Produto           | Necessário p/ 50 un | Já Registrado | Delta     | Ação                                             |
| ----------------- | -------------------- | -------------- | --------- | -------------------------------------------------- |
| Capa Impressa B5  | 50                   | 0              | 50        | PROD\_INT 50 (cria)  \+  CONS\_INT 50 (consume)    |
| Capa Produzida B5 | 50                   | 0              | 50        | PROD\_INT 50  \+  CONS\_INT 50                     |
| Miolo B5          | 50                   | 0              | 50        | PROD\_INT 50  \+  CONS\_INT 50                     |
| Sulfite B5        | 4.000 fls            | 0              | 4.000 fls | CONS\_MP −4.000 (pode ir negativo se não houver) |
| Caderno B5        | —                   | —             | —        | PROD\_ACAB \+50 un                                 |

| 💡 Insight Este cenário valida a Premissa P3: a finalização sozinha é suficiente para o motor processar toda a cadeia. O sistema não depende de que as etapas anteriores tenham sido preenchidas. |
| :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

## **Cenário C — Finalização parcial com estoque prévio de intermediários**

| Contexto Demanda: 200 Agendas A5. O Setor 2 havia produzido 300 capas para outra demanda anterior que foi cancelada — há 300 Capas Produzidas em estoque. O Setor 3 produziu miolos para outra demanda e há 150 miolos em estoque. |
| :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |

**Situação do estoque antes da finalização de 200 Agendas:**

| Produto                | Saldo em Estoque     | Necessário            | Consumo de Estoque               | Produção Compensatória     |
| ---------------------- | -------------------- | ---------------------- | -------------------------------- | ----------------------------- |
| Capa Produzida A5      | 300 un (disponível) | 200                    | CONS\_INT −200 (usa do estoque) | 0 (não precisa)              |
| Miolo A5               | 150 un (disponível) | 200                    | CONS\_INT −150 (usa tudo)       | PROD\_INT \+50 (faltaram 50\) |
| Capa Impressa A5       | 0                    | 0 (capa já produzida) | Não necessária                 | Não necessária              |
| Sulfite (p/ 50 miolos) | varia                | 4.000 fls              | CONS\_MP −4.000                 | —                            |

**Lógica chave:** O motor identifica que as 200 Capas Produzidas já existiam em estoque — não precisa gerar PROD\_INT para elas nem consumir suas matérias-primas. Para os miolos, havia 150 → consome todos, e gera PROD\_INT para os 50 faltantes, explorindo o BOM desses 50 miolos para consumir sulfite e tinta.

## **Cenário D — Finalização parcial incremental (30 agora, 70 depois)**

| Contexto Demanda: 100 Agendas A5. O Setor 4 finaliza 30 primeiro. Depois finaliza mais 70\. O motor deve processar cada finalização sobre o delta incremental, sem duplicar consumos. |
| :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

**Primeira finalização — 30 unidades:**

| Produto        | Necessário p/ 30 | Ledger da Demanda | Delta | Movimentos Gerados              |
| -------------- | ----------------- | ----------------- | ----- | ------------------------------- |
| Capa Produzida | 30                | 0                 | 30    | PROD\_INT \+30 / CONS\_INT −30 |
| Miolo A5       | 30                | 0                 | 30    | PROD\_INT \+30 / CONS\_INT −30 |
| Sulfite        | 2.400 fls         | 0                 | 2.400 | CONS\_MP −2.400                |
| Agenda A5      | —                | —                | —    | PROD\_ACAB \+30                 |

**Segunda finalização — 70 unidades (o ledger já tem os 30 anteriores):**

| Produto        | Necessário TOTAL | Ledger (já reg.) | Delta p/ esta rodada | Movimentos Gerados              |
| -------------- | ----------------- | ----------------- | -------------------- | ------------------------------- |
| Capa Produzida | 100               | 30                | **70**         | PROD\_INT \+70 / CONS\_INT −70 |
| Miolo A5       | 100               | 30                | **70**         | PROD\_INT \+70 / CONS\_INT −70 |
| Sulfite        | 8.000 fls         | 2.400             | **5.600**      | CONS\_MP −5.600                |
| Agenda A5      | —                | —                | —                   | PROD\_ACAB \+70                 |

| ✅ Garantia de Idempotência O motor sempre lê o ledger antes de lançar. Mesmo que E7 seja chamado duas vezes com os mesmos dados (bug de UI, por exemplo), o delta seria 0 e nenhum movimento seria gerado. |
| :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

## **Cenário E — Etapas registradas fora de ordem com quantidades inconsistentes**

| Contexto Demanda: 80 Agendas A5. O usuário registrou etapas em ordem aleatória e com quantidades que não batem: E4=90 miolos prontos, E7=80 finalizados, E2=60 capas produzidas (na ordem: E4 → E7 → E2). |
| :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

**Estado dos eventos quando E7 (80 finalizados) é disparado:**

* **E4 já foi registrado:** 90 miolos prontos (é um sinal, não movimentou estoque)
* **E2 ainda NÃO foi registrado** quando E7 é disparado
* **E7 dispara o motor:** A necessidade é calculada pelo BOM de 80 unidades

| Produto           | Necessário p/ 80 | Estoque disponível            | Delta a lançar | Movimento                                              |
| ----------------- | ----------------- | ------------------------------ | --------------- | ------------------------------------------------------ |
| Capa Impressa A5  | 80                | 0                              | 80              | PROD\_INT \+80 / CONS\_INT −80                        |
| Capa Produzida A5 | 80                | 0                              | 80              | PROD\_INT \+80 / CONS\_INT −80                        |
| Miolo A5          | 80                | 0 (sinal E4 não move estoque) | 80              | PROD\_INT \+80 / CONS\_INT −80                        |
| Sulfite           | 6.400 fls         | 5.000 (disponível)            | 6.400           | CONS\_MP −5.000 (estoque) \+ saldo −1.400 (negativo) |
| Agenda A5         | —                | —                             | —              | PROD\_ACAB \+80 un                                     |

**Depois, E2 é registrado (60 capas produzidas):** O motor verifica o ledger e identifica que o consumo de Capa Produzida já foi inteiramente processado pelo E7. O registro de E2 é armazenado como sinal de auditoria, mas não gera novas movimentações de estoque, pois o delta já é zero.

| 🔍 Por que os sinais importam mesmo sem mover estoque? Os eventos E1-E6 são preservados como auditoria do processo produtivo. Eles permitem análises de desempenho por setor (tempo entre etapas, gargalos) e servem como evidência de que as etapas foram realizadas, mesmo que o motor de estoque opere de forma independente. |
| :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

# **8\. Integração com o Sistema de Reserva de Estoque**

## **8.1 Como a Reserva Funciona**

Quando uma demanda é criada e aprovada, o sistema de reserva calcula a necessidade de matérias-primas (e opcionalmente de intermediários) e reserva o estoque disponível.

| Fase da Demanda           | Ação no Estoque                               | Tipo de Movimento                    |
| ------------------------- | ----------------------------------------------- | ------------------------------------ |
| Demanda Criada / Aprovada | Calcula BOM e reserva disponível por produto   | RESERVA (disponível → reservado)   |
| Produção em Andamento   | Saldo reservado mantido — nenhuma baixa ainda  | —                                   |
| Finalização (E7)        | Motor libera reserva e registra consumo efetivo | LIB\_RESERVA \+ CONS\_MP / PROD\_INT |
| Demanda Cancelada         | Reservas são devolvidas ao disponível         | LIB\_RESERVA (reverso)               |

## **8.2 Lógica de Consumo com Reserva**

Na Fase 4 do motor, quando há saldo reservado para aquela demanda:

1. **Consome primeiro da reserva:** LIB\_RESERVA converte reservado → consumido
2. **Se a reserva cobriu tudo:** nenhum consumo adicional do estoque disponível
3. **Se a reserva não cobriu tudo:** diferença é buscada no disponível geral
4. **Se nem disponível geral cobre:** para MP → saldo negativo; para intermediário → PROD\_INT compensatório

| ⚠️ Cuidado com a Reserva Bugada Se o módulo de reserva estiver calculando incorretamente (como mencionado), o motor de reconciliação NÃO depende da reserva para seu funcionamento correto — ele calcula o necessário diretamente do BOM. A reserva é um mecanismo auxiliar de planejamento. O motor deve tratá-la como 'bônus': se houver reserva correta, ótimo; se não houver ou estiver errada, o motor ainda funciona. |
| :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

# **9\. Estrutura do Ledger de Movimentações**

O ledger é o coração da auditabilidade e da idempotência do motor. Cada linha representa uma movimentação atômica.

| Campo             | Tipo          | Descrição                                                |
| ----------------- | ------------- | ---------------------------------------------------------- |
| id                | UUID          | Identificador único da movimentação                     |
| demanda\_id       | FK            | Demanda que originou a movimentação                      |
| item\_demanda\_id | FK            | Item específico da demanda                                |
| produto\_id       | FK            | Produto movimentado                                        |
| tipo\_movimento   | ENUM          | CONS\_MP                                                   |
| quantidade        | DECIMAL       | Quantidade movimentada (sempre positiva)                   |
| sinal             | ENUM          | ENTRADA (+) ou SAIDA (−)                                  |
| saldo\_anterior   | DECIMAL       | Saldo do produto antes do movimento                        |
| saldo\_posterior  | DECIMAL       | Saldo do produto após o movimento                         |
| etapa\_origem     | ENUM          | E1-E7 ou RECONCILIACAO ou RESERVA ou AJUSTE                |
| reconciliacao\_id | FK nullable   | ID do snapshot de reconciliação que gerou este movimento |
| timestamp         | TIMESTAMP     | Momento exato do registro                                  |
| usuario\_id       | FK            | Usuário ou sistema que disparou                           |
| observacao        | TEXT nullable | Notas adicionais (ex: 'produção compensatória')         |

## **9.1 Snapshot de Reconciliação**

Cada execução do motor gera um Snapshot que registra a 'fotografia' do momento do cálculo — usado para debug, auditoria e rollback.

| Campo                  | Descrição                                                   |
| ---------------------- | ------------------------------------------------------------- |
| id                     | UUID do snapshot                                              |
| item\_demanda\_id      | Item processado                                               |
| qtd\_finalizada        | Quantidade que disparou a reconciliação                     |
| bom\_necessario\_json  | JSON com toda a explosão do BOM calculada                    |
| ledger\_anterior\_json | JSON com o estado do ledger ANTES do processamento            |
| delta\_calculado\_json | JSON com os deltas calculados por produto                     |
| movimentos\_gerados    | Lista de IDs de movimentações criadas nesta reconciliação |
| timestamp              | Momento da execução                                         |
| status                 | SUCESSO                                                       |

# **10\. Regras de Negócio Críticas**

| ID              | Regra                                                     | Implementação                                                                                                                         |
| --------------- | --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| **RN-01** | Intermediário nunca fica negativo                        | Na Fase 4: se saldo\< qtd\_delta → PROD\_INT para a diferença antes de CONS\_INT                                                      |
| **RN-02** | Delta sempre sobre o total acumulado                      | bom\_necessario usa qtd\_total\_finalizada\_até\_agora, não só o incremento atual                                                    |
| **RN-03** | Finalização não pode ultrapassar quantidade da demanda | Validação prévia: soma(qtd\_finalizadas) ≤ qtd\_demanda. Rejeita se ultrapassar.                                                    |
| **RN-04** | Re-execução idempotente                                 | Motor verifica ledger antes de lançar. Se delta\= 0, não gera movimentos.                                                             |
| **RN-05** | Atomicidade da reconciliação                            | Todos os movimentos de uma reconciliação são commitados ou revertidos juntos.                                                        |
| **RN-06** | Estoque reservado não é disponível                     | saldo\_disponivel \= saldo\_total − saldo\_reservado. Motor sempre usa saldo\_disponivel.                                              |
| **RN-07** | Produção compensatória é auditável                   | PROD\_INT com observacao='produção compensatória — etapa não registrada' e link para reconciliacao\_id.                            |
| **RN-08** | Cancelamento de finalização                             | Gera movimentos inversos para todos os movimentos do snapshot. Restaura saldos.                                                         |
| **RN-09** | Sinais (E1-E6) não movem estoque                         | Eventos de produção são armazenados como log de processo, não como transações de estoque.                                         |
| **RN-10** | BOM versionado                                            | Snapshots de reconciliação gravam o BOM da versão vigente na data — mudanças futuras no BOM não afetam reconciliações passadas. |

# **11\. Estados do Item de Demanda**

| Estado                            | Condição                            | Descrição                                                |
| --------------------------------- | ------------------------------------- | ---------------------------------------------------------- |
| **PENDENTE**                | Nenhuma etapa registrada              | Item criado, aguardando início da produção              |
| **EM PRODUÇÃO**           | Pelo menos 1 etapa registrada (E1-E6) | Algum setor já atualizou progresso                        |
| **PRONTO PARA RETIRADA**    | E3 e E4 atingiram a quantidade alvo   | Capas e miolos prontos aguardando Setor 4                  |
| **EM MONTAGEM**             | E5 ou E6 registrado                   | Setor 4 iniciou a montagem/empacotamento                   |
| **PARCIALMENTE FINALIZADO** | E7\> 0 e E7 \< qtd\_demanda           | Algumas unidades finalizadas, produção continua          |
| **FINALIZADO**              | E7\= qtd\_demanda                     | Todas as unidades foram finalizadas e estoque reconciliado |
| **CANCELADO**               | Cancelamento manual                   | Reservas liberadas, movimentos revertidos                  |

# **12\. Recomendações de Implementação**

## **12.1 Prioridades de Desenvolvimento**

5. **Ledger de movimentações:** Implementar primeiro. É a base de tudo. Garante idempotência e auditoria.
6. **Algoritmo de explosão de BOM:** Recursivo com cache para evitar recalcular hierarquias iguais.
7. **Motor de reconciliação:** Implementar as 6 fases em sequência, com testes por cenário.
8. **Integração com reserva:** Depois que o motor estiver estável, integrar a liberação de reservas.
9. **Interface de auditoria:** Tela que mostra o snapshot de reconciliação de cada finalização.

## **12.2 Pontos de Atenção Técnica**

* **Concorrência:** Duas finalizações simultâneas da mesma demanda podem causar duplo consumo. Usar lock por item\_demanda\_id durante a reconciliação.
* **BOM versionado:** Gravar no snapshot a versão do BOM usada — essencial se o produto mudar de formulação no futuro.
* **Performance do ledger:** Indexar por (demanda\_id, item\_demanda\_id, produto\_id) para leitura rápida dos movimentos existentes antes do cálculo do delta.
* **Notificações:** Após reconciliação, emitir evento de domínio para que outros módulos (compras, dashboard) sejam notificados.
* **Reversão:** Toda reconciliação deve ser reversível através do snapshot — crítico para correção de erros operacionais.

*Motor de Gerenciamento de Estoque · Versão 1.0*

*Este documento deve ser revisado e aprovado antes de iniciar a implementação.*
