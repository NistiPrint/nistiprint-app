# Data Model: Despacho e Modalidades Logisticas

Last updated: 2026-08-02

Status: target-state

Companheiro de [Despacho spec](./spec.md). Este documento define o modelo de
dados, a classificacao, o backfill e o sequenciamento das migrations.

## Decisoes estruturais

### 1. Plataforma define a regra, conta define o horario

A regra de prazo do Turbo (etiqueta em 40min, coleta em 60min) e uma regra da
Shopee, identica em toda conta Shopee. Ja o horario de corte do Flex e o ponto
de coleta variam por conta e regiao.

Por isso o cadastro e dividido em dois niveis:

- `modalidades_logisticas`: por plataforma. Identidade, `tipo_prazo`, offsets,
  politica de lote, interrupcao. E a regra publicada pelo marketplace.
- `modalidade_config_conta`: por instancia de marketplace instalada. Horarios de
  corte e coleta, ponto de coleta, ativacao. Sobrescreve o default da
  modalidade.

Cadastrar Turbo uma vez habilita todas as contas Shopee. Ajustar o corte do
Flex de uma loja nao afeta as outras.

### 2. Um unico campo de ordenacao para FIXO e RELATIVO

`pedidos.compromisso_logistico_em` e o instante do compromisso com a origem:

- `tipo_prazo = FIXO`: data operacional + `corte_horario`.
- `tipo_prazo = RELATIVO`: `data_pedido` + `offset_etiqueta_min`.

Isso implementa a ordenacao canonica da spec com um unico indice e um unico
`ORDER BY` compartilhado por torre de despacho, esteira, lista de demandas e
painel de producao. Sem esse campo, cada tela reimplementa a regra e as ordens
divergem.

### 3. Classificacao explicavel

O pedido guarda qual regra o classificou (`modalidade_regra_id`) e o valor cru
que veio da origem. Sem isso, "por que esse pedido caiu em Comum" vira
investigacao manual em `platform_fields`.

### 3b. Chave estavel separada de rotulo de exibicao

O caso Shopee Turbo mostra que a origem entrega duas informacoes com papeis
diferentes:

| Campo Shopee | Valor | Papel |
| --- | --- | --- |
| `logistics_channel_id` | `90011`, `90012` | identificador estavel |
| `shipping_carrier` | `Entrega Turbo`, `Entrega Turbo (SPF)` | rotulo de exibicao |

Classificar pelo rotulo e fragil: string de marketing muda por renomeacao,
acentuacao, parenteses e locale, e cada mudanca reclassificaria pedidos em
producao. Mas o rotulo e o que o admin precisa ler no alerta de metodo novo,
porque `90013` sozinho nao diz nada.

Por isso o pedido guarda os dois:

- `metodo_envio_chave`: base da classificacao e do agrupamento.
- `metodo_envio_rotulo`: exibicao, alerta e conferencia com a tela da origem.

Quando a plataforma nao expoe identificador estavel, `metodo_envio_chave`
recebe o proprio rotulo normalizado e o comportamento degrada sem quebrar.

### 4. `despachado_em` como predicado de saida da arvore

A arvore de totalizadores precisa de um predicado barato e indexavel para "o
que ainda nao foi despachado". Derivar isso de `demandas_pedidos` a cada
consulta impede indice parcial e degrada com o volume.

`pedidos.despachado_em` e preenchido na publicacao da demanda e serve de
predicado do indice parcial.

## DDL

### `modalidades_logisticas`

```sql
CREATE TABLE public.modalidades_logisticas (
    id                    serial PRIMARY KEY,
    plataforma_id         integer NOT NULL REFERENCES public.plataformas(id),
    codigo                varchar(50) NOT NULL,
    nome                  varchar(100) NOT NULL,
    tipo_prazo            varchar(20) NOT NULL
                          CHECK (tipo_prazo IN ('FIXO', 'RELATIVO')),
    politica_lote         varchar(20) NOT NULL DEFAULT 'LOTE'
                          CHECK (politica_lote IN ('LOTE', 'INDIVIDUAL')),
    nivel_interrupcao     smallint NOT NULL DEFAULT 0,
    corte_horario         time,
    coleta_horario        time,
    coleta_dia_offset     smallint NOT NULL DEFAULT 0,
    ponto_coleta_id       integer REFERENCES public.pontos_coleta(id),
    offset_etiqueta_min   integer,
    offset_coleta_min     integer,
    cor                   varchar(7),
    ordem_exibicao        smallint NOT NULL DEFAULT 100,
    ativo                 boolean NOT NULL DEFAULT true,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT modalidades_logisticas_plataforma_codigo_key
        UNIQUE (plataforma_id, codigo),
    CONSTRAINT modalidades_logisticas_prazo_fixo_ck CHECK (
        tipo_prazo <> 'FIXO' OR corte_horario IS NOT NULL
    ),
    CONSTRAINT modalidades_logisticas_prazo_relativo_ck CHECK (
        tipo_prazo <> 'RELATIVO' OR offset_etiqueta_min IS NOT NULL
    )
);
```

`coleta_dia_offset` cobre corte 18:00 com coleta no dia seguinte 08:00.
`nivel_interrupcao` 0 = nao interrompe, valores maiores furam fila.

### `modalidade_config_conta`

```sql
CREATE TABLE public.modalidade_config_conta (
    id                         serial PRIMARY KEY,
    modalidade_id              integer NOT NULL
                               REFERENCES public.modalidades_logisticas(id) ON DELETE CASCADE,
    marketplace_integration_id integer NOT NULL
                               REFERENCES public.installed_integrations(id) ON DELETE CASCADE,
    corte_horario              time,
    coleta_horario             time,
    coleta_dia_offset          smallint,
    ponto_coleta_id            integer REFERENCES public.pontos_coleta(id),
    ativo                      boolean NOT NULL DEFAULT true,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT modalidade_config_conta_key
        UNIQUE (modalidade_id, marketplace_integration_id)
);
```

Resolucao de horario: `COALESCE(config.campo, modalidade.campo)`. Ausencia de
linha significa "usa o default da plataforma", nao "desativado".

### `regras_classificacao_modalidade`

```sql
CREATE TABLE public.regras_classificacao_modalidade (
    id                         serial PRIMARY KEY,
    plataforma_id              integer NOT NULL REFERENCES public.plataformas(id),
    marketplace_integration_id integer REFERENCES public.installed_integrations(id),
    modalidade_id              integer NOT NULL
                               REFERENCES public.modalidades_logisticas(id) ON DELETE CASCADE,
    campo_origem               varchar(120) NOT NULL,
    operador                   varchar(20) NOT NULL DEFAULT 'IGUAL'
                               CHECK (operador IN ('IGUAL', 'CONTEM', 'PREFIXO', 'REGEX')),
    valor                      text NOT NULL,
    case_sensitive             boolean NOT NULL DEFAULT false,
    prioridade                 smallint NOT NULL DEFAULT 100,
    ativo                      boolean NOT NULL DEFAULT true,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_regras_class_modalidade_lookup
    ON public.regras_classificacao_modalidade (plataforma_id, ativo, prioridade, id);
```

`marketplace_integration_id` nulo significa regra valida para toda conta da
plataforma. Regra com conta preenchida tem precedencia sobre regra geral de
mesma prioridade.

`campo_origem` e o caminho logico dentro de `pedido_snapshots.platform_fields`
(ex.: `shipping_carrier`, `servico_logistico`, `logistics.shipping_method`).

### `metodos_envio_observados`

```sql
CREATE TABLE public.metodos_envio_observados (
    id                         serial PRIMARY KEY,
    plataforma_id              integer NOT NULL REFERENCES public.plataformas(id),
    marketplace_integration_id integer REFERENCES public.installed_integrations(id),
    campo_origem               varchar(120) NOT NULL,
    valor_bruto                text NOT NULL,
    valor_normalizado          text NOT NULL,
    rotulo_bruto               text,
    status                     varchar(20) NOT NULL DEFAULT 'NOVO'
                               CHECK (status IN ('NOVO', 'CLASSIFICADO', 'IGNORADO')),
    modalidade_id              integer REFERENCES public.modalidades_logisticas(id),
    ocorrencias                integer NOT NULL DEFAULT 1,
    primeira_ocorrencia_em     timestamptz NOT NULL DEFAULT now(),
    ultima_ocorrencia_em       timestamptz NOT NULL DEFAULT now(),
    pedido_exemplo_id          integer,
    alerta_emitido_em          timestamptz,

    CONSTRAINT metodos_envio_observados_key
        UNIQUE (plataforma_id, campo_origem, valor_normalizado)
);
```

`valor_bruto` guarda a chave estavel; `rotulo_bruto` guarda o texto de
exibicao. O alerta de metodo novo usa os dois: "Shopee: novo canal logistico
90013 (Entrega Turbo Noturna), 3 pedidos". So a chave nao permite ao admin
reconhecer o que e; so o rotulo nao permite escrever uma regra estavel.

`valor_normalizado` = `lower(btrim(valor_bruto))`, para nao gerar alerta
duplicado por variacao de caixa ou espaco quando a chave for textual.

### Alteracoes em `pedidos`

```sql
ALTER TABLE public.pedidos
    ADD COLUMN IF NOT EXISTS modalidade_logistica_id  integer
        REFERENCES public.modalidades_logisticas(id),
    ADD COLUMN IF NOT EXISTS modalidade_regra_id      integer
        REFERENCES public.regras_classificacao_modalidade(id),
    ADD COLUMN IF NOT EXISTS metodo_envio_chave       text,
    ADD COLUMN IF NOT EXISTS metodo_envio_rotulo      text,
    ADD COLUMN IF NOT EXISTS modalidade_classificada_em timestamptz,
    ADD COLUMN IF NOT EXISTS compromisso_logistico_em timestamptz,
    ADD COLUMN IF NOT EXISTS despachado_em            timestamptz;
```

Ambos sao denormalizados a partir de `platform_fields`: a arvore e o no "nao
classificada" precisam deles sem abrir jsonb a cada consulta.

`modalidade_logistica_id` nulo significa nao classificado. Nunca preencher com
uma modalidade default.

### Alteracoes em `demandas_producao`

```sql
ALTER TABLE public.demandas_producao
    ADD COLUMN IF NOT EXISTS modalidade_id     integer
        REFERENCES public.modalidades_logisticas(id),
    ADD COLUMN IF NOT EXISTS escopo_despacho   jsonb,
    ADD COLUMN IF NOT EXISTS demanda_origem_id integer
        REFERENCES public.demandas_producao(id);
```

`escopo_despacho` guarda o escopo reproduzivel:

```json
{
  "marketplace_integration_id": 12,
  "modalidade_id": 4,
  "horizonte": ["atrasado", "hoje"],
  "data_operacional": "2026-08-03",
  "total_pedidos_no_lancamento": 122,
  "total_conferido_pelo_operador": 122
}
```

`demanda_origem_id` liga o lote complementar de retardatarios a demanda
original do mesmo escopo.

`modalidades_logistica` (varchar existente) permanece durante a transicao e
passa a ser espelho de `modalidade_id`.

### Indices

```sql
CREATE INDEX idx_pedidos_arvore_despacho
    ON public.pedidos (marketplace_integration_id, modalidade_logistica_id, data_limite_envio)
    WHERE despachado_em IS NULL;

CREATE INDEX idx_pedidos_compromisso
    ON public.pedidos (compromisso_logistico_em)
    WHERE despachado_em IS NULL;

CREATE INDEX idx_pedidos_modalidade_nao_classificada
    ON public.pedidos (marketplace_integration_id, metodo_envio_chave)
    WHERE modalidade_logistica_id IS NULL AND despachado_em IS NULL;
```

O indice parcial e o que sustenta a arvore em tempo interativo: ele so cobre o
backlog aberto, nao o historico.

## Algoritmo de classificacao

Executado no ingest, apos resolver `marketplace_integration_id`.

1. Extrair `metodo_envio_chave` e `metodo_envio_rotulo` do `platform_fields`
   conforme o mapeamento configurado para a plataforma. Persistir em `pedidos`.
2. Registrar o par em `metodos_envio_observados` (upsert pela chave,
   incrementa `ocorrencias`, atualiza `ultima_ocorrencia_em` e `rotulo_bruto`).
3. Selecionar regras ativas da plataforma, ordenadas por:
   `marketplace_integration_id NULLS LAST`, `prioridade`, `id`.
   Primeira regra que casa vence.
4. Se houve match: gravar `modalidade_logistica_id`, `modalidade_regra_id`,
   `modalidade_classificada_em`, e calcular `compromisso_logistico_em`.
5. Se nao houve match: deixar `modalidade_logistica_id` nulo. O pedido cai no
   no `Modalidade nao classificada` e recebe prioridade maxima. Se o metodo
   observado esta com `status = 'NOVO'` e `alerta_emitido_em` nulo, emitir
   alerta de administracao e marcar o carimbo.

Determinismo: a ordenacao de desempate inclui `id`, entao a mesma entrada
sempre produz a mesma modalidade. Sem isso, dois pedidos identicos podem cair
em grupos diferentes conforme o plano de execucao do Postgres.

### Calculo de `compromisso_logistico_em`

```
FIXO:
  base   = data operacional (hoje se agora <= corte, senao proximo dia util)
  valor  = base + COALESCE(config.corte_horario, modalidade.corte_horario)

RELATIVO:
  valor  = pedidos.data_pedido + modalidade.offset_etiqueta_min

NAO CLASSIFICADO:
  valor  = pedidos.data_pedido
           (deliberadamente no passado, para ordenar no topo)
```

Nao classificado ordenar primeiro e intencional: prazo desconhecido pode ser um
Turbo com 40 minutos correndo.

### Reclassificacao retroativa

Ao cadastrar uma modalidade ou regra nova, um job reclassifica pedidos com
`despachado_em IS NULL` cujo `metodo_envio_bruto` casa com a regra, recalcula
`compromisso_logistico_em` e move `metodos_envio_observados.status` para
`CLASSIFICADO`. Pedidos ja despachados nao sao tocados: alterar o passado
quebraria a rastreabilidade do lote.

## Exemplo trabalhado: Shopee Turbo

Fonte: `get_order_detail` da Shopee expoe `logistics_channel_id` (90011 para
Entrega Turbo, 90012 para Entrega Turbo SPF) e `shipping_carrier` com os
rotulos correspondentes. Regra operacional: etiqueta em ate 40 minutos apos o
pedido, coleta 1 hora apos o pedido.

Mapeamento de extracao para a plataforma Shopee:

```
metodo_envio_chave  <- platform_fields.logistics_channel_id
metodo_envio_rotulo <- platform_fields.shipping_carrier
```

Modalidade:

```sql
INSERT INTO public.modalidades_logisticas (
    plataforma_id, codigo, nome, tipo_prazo, politica_lote,
    nivel_interrupcao, offset_etiqueta_min, offset_coleta_min, ordem_exibicao
) VALUES (
    :shopee_id, 'TURBO', 'Turbo', 'RELATIVO', 'INDIVIDUAL',
    10, 40, 60, 10
);
```

Duas regras apontando para a mesma modalidade:

```sql
INSERT INTO public.regras_classificacao_modalidade (
    plataforma_id, modalidade_id, campo_origem, operador, valor, prioridade
) VALUES
    (:shopee_id, :turbo_id, 'logistics_channel_id', 'IGUAL', '90011', 10),
    (:shopee_id, :turbo_id, 'logistics_channel_id', 'IGUAL', '90012', 10);
```

Cardinalidade N regras para 1 modalidade e o caso normal, nao excecao: um
marketplace costuma ter varios canais logisticos com a mesma regra operacional.

Regras de fallback por rotulo, com prioridade mais alta (avaliadas depois),
existem para o caso de a Shopee lancar um canal Turbo com ID novo antes de
alguem cadastrar:

```sql
INSERT INTO public.regras_classificacao_modalidade (
    plataforma_id, modalidade_id, campo_origem, operador, valor, prioridade
) VALUES
    (:shopee_id, :turbo_id, 'shipping_carrier', 'CONTEM', 'Entrega Turbo', 900);
```

O fallback por rotulo e defensivo e nunca deve ser a regra principal. Se ele
disparar, o alerta de metodo novo ja terra registrado o ID desconhecido e o
admin cadastra a regra estavel.

### Ponto em aberto: Turbo e Turbo SPF sao a mesma modalidade?

O modelo acima assume que 90011 e 90012 compartilham a regra de 40/60 minutos.
Se o SPF tiver prazo, ponto de coleta ou politica de lote diferente, sao **duas
modalidades**, nao uma com duas regras. A separacao e barata agora e cara
depois, porque `compromisso_logistico_em` ja teria sido gravado errado em
pedidos despachados. Confirmar antes do seed.

### Efeito no fluxo

Turbo tem `tipo_prazo = RELATIVO`, entao nao aparece como no acumulavel na
arvore de conferencia: entra na esteira FIFO com relogio proprio por pedido.
Com `politica_lote = INDIVIDUAL`, uma demanda de 1 pedido e o resultado
esperado. Com `nivel_interrupcao = 10`, o item entra a frente da fila de
producao corrente sem pedir decisao ao operador.

## RPC da arvore

```sql
CREATE OR REPLACE FUNCTION public.despacho_arvore(p_data date DEFAULT CURRENT_DATE)
RETURNS TABLE (
    marketplace_integration_id integer,
    marketplace_nome           text,
    modalidade_id              integer,
    modalidade_nome            text,
    tipo_prazo                 text,
    bucket_prazo               text,
    qtd_pedidos                integer,
    qtd_itens                  integer,
    compromisso_mais_proximo   timestamptz
)
```

`bucket_prazo` derivado de `data_limite_envio` contra `p_data`:
`atrasado` (< p_data), `hoje`, `amanha`, `depois`, `sem_prazo`.

Agregacao com `GROUPING SETS` para devolver os tres niveis em uma chamada. A
API nao faz tres consultas nem soma no cliente; a invariante "soma dos filhos
igual ao pai" e garantida pela propria agregacao.

`qtd_pedidos` e o numero de conferencia contra o painel do marketplace.
`qtd_itens` e carga de producao e nao deve ser exibido como numero
comparavel com a origem.

`sem_prazo` existe porque `data_limite_envio` pode nao vir preenchido em toda
origem, e o pedido ainda assim precisa pertencer a exatamente um caminho.

## Backfill

Ordem obrigatoria, cada etapa idempotente.

1. Seed de `plataformas` ja existente. Criar `modalidades_logisticas` a partir
   das combinacoes hoje representadas por `canais_venda.flex`,
   `canais_venda.fulfillment` e `regras_logisticas_canal.modalidade`.
2. Migrar `regras_logisticas_canal` para `modalidade_config_conta`, traduzindo
   `canal_venda_id` para `marketplace_integration_id` pela mesma resolucao ja
   usada no ingest.
3. Backfill de `pedidos.metodo_envio_chave` e `metodo_envio_rotulo` a partir de
   `pedido_snapshots.platform_fields` e de `pedidos.servico_logistico`.
4. Popular `metodos_envio_observados` com os valores distintos encontrados,
   status `NOVO`, sem emitir alerta em massa (`alerta_emitido_em = now()` no
   backfill inicial para nao inundar a administracao).
5. Criar regras de classificacao para os valores conhecidos e reclassificar.
6. Backfill de `pedidos.modalidade_logistica_id` com fallback:
   `is_flex = true` mapeia para a modalidade Flex da plataforma do pedido.
7. Backfill de `compromisso_logistico_em` para pedidos abertos.
8. Backfill de `despachado_em` a partir de `demandas_pedidos` para demandas ja
   publicadas.

Pedido que nao casar em nenhuma etapa fica com modalidade nula. Isso e o
resultado correto, nao uma falha do backfill.

## Transicao do `is_flex`

`is_flex` e lido hoje em API, worker, impressao, alertas e consolidacao. Nao e
possivel usar coluna gerada porque o valor depende de join com
`modalidades_logisticas`.

Estrategia em tres fases:

1. **Coexistencia.** Trigger em `pedidos` mantem `is_flex` sincronizado com
   `modalidade_logistica_id` sempre que a modalidade muda. Nenhum consumidor
   e alterado. `is_flex` deixa de ser escrito por qualquer outro caminho.
2. **Migracao de leitura.** Consumidores passam a ler
   `modalidade_logistica_id` / `tipo_prazo`. Prioridade para os que decidem
   agrupamento e prioridade, porque sao os que quebram com o Turbo:
   `consolidation_tasks.py`, `producao_contexto.py`, `alertas.py`.
3. **Remocao.** Drop da coluna e do trigger, apos nenhum consumidor
   referenciar.

Enquanto `is_flex` existir, ele nao pode ser criterio de agrupamento em codigo
novo. Um booleano nao representa tres modalidades.

## Sequenciamento das migrations

| Arquivo | Conteudo | Reversivel |
| --- | --- | --- |
| `2026MMDD000000_modalidades_logisticas_catalogo.sql` | 4 tabelas novas, sem tocar em `pedidos` | sim |
| `2026MMDD000001_pedidos_modalidade_colunas.sql` | Colunas em `pedidos` e `demandas_producao`, indices | sim |
| `2026MMDD000002_seed_modalidades_e_regras.sql` | Seed de modalidades e regras conhecidas | sim |
| `2026MMDD000003_backfill_modalidade_pedidos.sql` | Backfill em lote, idempotente | dados |
| `2026MMDD000004_trigger_is_flex_compat.sql` | Trigger de compatibilidade | sim |
| `2026MMDD000005_rpc_despacho_arvore.sql` | RPC da arvore | sim |

As tres primeiras podem ir a producao sem nenhuma mudanca de frontend. O ganho
de classificar Turbo corretamente e independente da torre de despacho.

## Riscos

- **Campo de origem do metodo de envio.** Resolvido para Shopee
  (`logistics_channel_id` + `shipping_carrier`). Mercado Livre e Bling ainda
  exigem inspecao de payload real para definir o par chave/rotulo.
- **Ausencia de chave estavel.** Se uma plataforma so expuser rotulo, a
  classificacao herda a fragilidade da string. Nesse caso o rotulo vira chave e
  a renomeacao pelo marketplace aparece como metodo novo, com alerta, em vez de
  reclassificacao silenciosa. E o comportamento correto, mas gera ruido.
- **Data operacional e virada de dia.** Corte apos meia-noite e fuso ainda sao
  gap aberto na spec e afetam `compromisso_logistico_em`.
- **`despachado_em` fora de sincronia.** Se a publicacao de demanda falhar
  parcialmente, pedidos somem da arvore sem estar em producao. A escrita deve
  ocorrer na mesma transacao da publicacao, e uma checagem de consistencia
  deve comparar `despachado_em` contra `demandas_pedidos`.
- **Volume do backfill.** `pedidos` historico e grande; o backfill deve rodar
  em lotes com limite, nao em statement unico.

## Acceptance criteria

- Cadastrar Shopee Turbo (`RELATIVO`, +40min, +60min, `INDIVIDUAL`) e uma regra
  de classificacao habilita a modalidade em todas as contas Shopee sem deploy.
- Um pedido Turbo recebe `compromisso_logistico_em = data_pedido + 40min`.
- Um metodo de envio novo cria linha em `metodos_envio_observados` com status
  `NOVO`, emite um unico alerta e nao altera a modalidade de nenhum pedido.
- `despacho_arvore` devolve os tres niveis em uma chamada e a soma dos filhos e
  igual ao pai em todos os nos.
- Reclassificar apos cadastro move pedidos abertos e nao move pedidos ja
  despachados.
- Dois pedidos com o mesmo `metodo_envio_chave` sempre recebem a mesma
  modalidade.
- Pedidos com `logistics_channel_id` 90011 e 90012 caem ambos em Turbo.
- Renomear o rotulo de exibicao na origem, mantendo o mesmo
  `logistics_channel_id`, nao reclassifica nenhum pedido.
- Todo pedido aberto pertence a exatamente um caminho da arvore, inclusive os
  sem `data_limite_envio` e os sem modalidade.
