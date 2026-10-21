# Gestão e inteligência de negócio

## Entrega

Área `/gestao`: visão geral, vendas e canais, produtos/personalização, público,
rentabilidade, planejamento e qualidade de dados. A fonte é o pedido canônico;
espelhos de ERP/marketplaces enriquecem o pedido sem gerar novas vendas.

### Indicadores comerciais

- Elegíveis: preparação paga, documentação pronta, enviado, entregue. Estado
  desconhecido só entra com evidência de pagamento. Cancelados, devolvidos e
  aguardando pagamento têm populações separadas.
- Valor dos itens: soma de subtotais; não constitui receita líquida conciliada.
  Total pago, repasse e contribuição são conceitos independentes.
- Comparações: intervalo anterior de mesma duração; no dia atual, corte no
  mesmo horário. Fontes com precisão apenas de data usam dias completos.
  Comparações ficam indisponíveis quando uma conta não cobre o período anterior.
- Dias da semana: média por ocorrência completa, incluindo dias sem venda.
- Rankings: produto interno, anúncio/variação, família, categoria, formato,
  participação, curva ABC e desempenho por conta. Vínculos conflitantes não
  escolhem um produto arbitrariamente.
- Nomes: SUCCESS, normalização de espaços/capitalização, grafia e nomes compostos
  preservados. Unidades exigem quantidade explícita. Confirmações humanas são
  separadas de extrações automáticas.
- Público: destino de entrega; identidade pseudonimizada por plataforma/conta.
  Coortes, frequência e recompra são observadas apenas no histórico disponível.
  Identificadores de compradores não são devolvidos pelas APIs de Gestão.

### Resultado financeiro

`contribuição antes de publicidade = repasse líquido - custo dos produtos
- tributos variáveis - despesas operacionais variáveis`.

Taxas/frete já deduzidos do repasse são evidências explicativas, não novas
subtrações. Publicidade ausente impede apenas o cálculo após publicidade.
Qualquer componente obrigatório ausente impede a contribuição. Zero precisa
ser informado explicitamente. Custo atual usado para reconstrução histórica
permanece estimado. Custos com vigência são escolhidos na data da compra.

Pedidos cancelados/devolvidos com conciliação entram no resultado financeiro,
mas exigem `cogs` explícito: não se presume consumo ou recuperação do estoque.
Produtos em pedidos com múltiplos itens recebem rateio identificado como
estimativa, proporcional ao valor dos itens, preservando o custo de cada item.
Filtros de produto/categoria desabilitam a margem do pedido sem conciliação
específica para aquele recorte.

### Planejamento

Metas mensais de vendas, pedidos e contribuição por empresa ou conta. O realizado
é calculado desde o início do mês, independentemente do início escolhido no
filtro. Metas globais são ocultadas em recortes que não representam seu escopo.
Previsão: média por dia da semana em 28 dias; sete dias previstos e sete de
retrospectiva com erro absoluto médio, quando há histórico suficiente. Sem
sazonalidade anual ou extrapolação de participação no mercado total.

Estoque atual é comparado à média recente de unidades e necessidade de sete
dias; componentes são derivados da ficha técnica cadastrada. Não mistura
unidades de componentes em um total único nem executa compras/produção.
Apontamentos registram etapa, quantidade, duração e custo opcional. São
explícitos; falta de apontamento não é produtividade zero.

## Processamento e persistência

Migrações: `20261020160000_gestao_business_intelligence.sql`,
`20261020200000_marketplace_insights.sql` e `20261020210000_gestao_queries.sql`.
O painel executivo também usa `20261021200000_gestao_dashboard_aggregates.sql`,
que acrescenta agregados por UF e séries diárias de anúncios ao relatório em
cache, sem solicitar novas coletas aos marketplaces.

- `gestao_fatos_pedido`: uma projeção por pedido, com itens e personalizações.
- `gestao_outbox`: invalidação transacional de pedidos, itens, espelhos,
  personalizações e informações complementares. Alterações de catálogo/custos
  invalidam projeções; renovação de token não invalida o catálogo.
- `gestao_claim`/`gestao_finish`: lotes de até 250, lease de cinco minutos,
  SKIP LOCKED e geração monotônica. Atualização durante processamento impede
  gravar projeção obsoleta. Exclusão do pedido remove fatos e outbox por FK.
- `gestao_custos`: vigência/origem/custo estimado. Mudança cadastral registra
  vigência no momento da mudança, sem fabricar custos anteriores.
- `gestao_financeiro`: componentes, evidências, origem e estado da conciliação.
- `gestao_financeiro_historico`: revisões financeiras deduplicadas, preservando
  mudanças de componentes e evidências sem duplicar uma simples reexecução.
- `gestao_metricas_anuncio`: valores diários por conta/recurso/tipo. Contadores
  cumulativos ficam em tipo próprio; não são convertidos em visitas diárias.
- `gestao_coletas`: capacidade por conta, checkpoint, lease, estado e código de
  impedimento. Nunca guarda credenciais ou texto de exceções do provedor.
- `gestao_metas` e `gestao_apontamentos`: metas mensais e eventos idempotentes.

Worker `tasks.gestao_tasks.refresh`: até 100 pedidos a cada cinco segundos,
limites de tempo de 120/150 segundos, fila exclusiva `gestao_projection`.
Chamadas complementares usam `marketplace_insights`. Cada fila tem serviço
systemd próprio, concorrência um e prefetch um. Não existem chamadas externas
de analytics no caminho de ingestão dos pedidos.

Os serviços `platform_drivers/{shopee,mercadolivre,bling}_insights.py` interpretam
espelhos já persistidos e devolvem `OrderInsights`: conta, recurso, versão
semântica, fatos, lacunas, evidências e enriquecimentos. O núcleo de Gestão não
conhece endpoints, autenticação ou formatos dos marketplaces. A persistência
dos espelhos pertence a `platform_drivers/order_mirrors.py`; funções antigas
do serviço Bling são delegadores compatíveis.

Snapshots com itens e origem idênticos não executam novamente a sincronização
de itens. Isso evita recriar IDs na Shopee em notificações repetidas e preserva
as referências das personalizações. Anúncios com várias variações são agrupados
por recurso antes da coleta de visitas/contadores.

`marketplace_insight_requests` deduplica por conta/recurso/capacidade. A versão
é um hash dos campos comerciais, sem timestamps de manutenção. A gravação
financeira verifica e bloqueia a versão na mesma transação: resposta obsoleta
não grava componentes nem conclui a solicitação nova. Atualização de fatos
acorda a coleta financeira, preservando pausas e impedimentos da conta.
Uma alteração canônica ainda pendente na outbox também impede aceitar o
resultado anterior, mesmo antes de a nova projeção estar disponível.

Alterações de catálogo enfileiram escopos em `gestao_catalog_scopes`, expandidos
em lotes, sem enfileirar todo o histórico dentro da alteração do produto.
Atualizações somente de bookkeeping não invalidam pedidos.

`gestao_selected`, `gestao_report_data`, `gestao_order_page` e
`gestao_export_page` executam seleção, agregação e paginação no PostgreSQL.
Exportações usam cursor de ID e blocos de 500. `gestao_daily` guarda agregados
por dia/conta/canal. Cache SQL e cache da aplicação duram até 60 segundos,
separados por filtros e acesso financeiro, invalidados por revisão.
Rankings retornam até 100 posições; detalhes financeiros até 100 pedidos e
publicidade até 500 registros. Use filtros ou exportação para aprofundar.

## APIs e permissões

Todos os endpoints usam sessão ativa e permissão base `gestao`:

| Endpoint `/api/v2/gestao` | Contrato |
| --- | --- |
| `GET /resumo` | start/end ISO, marketplace, account_id, product_id, category_id, logistics; período máximo de 731 dias. Inclui `regions_by_state` para todas as UFs/destinos e `advertising_daily` completo por dia/conta/plataforma/tipo quando há permissão financeira. |
| `GET /pedidos` | Mesmo recorte; page, 50 por página; requer `gestao_detalhes.ler` |
| `GET /exportar` | CSV com proteção contra fórmulas; requer `gestao_detalhes.ler` |
| `PUT /metas` | month no primeiro dia, account_id opcional, metric, target positivo |
| `PUT /financeiro/:pedido_id` | components, settled booleano; requer `gestao_financeiro.editar` |
| `POST /custos` | produto_id, valid_from, unit_cost, source, estimated; permissão financeira |
| `POST /apontamentos` | event_key UUID, pedido_id, stage, occurred_at opcional, quantity/duration_minutes/cost opcionais |
| `POST /atualizar` | Agenda processamento, não executa refresh durante request |
| `POST /coletar/:account_id` | delegador compatível; exige administrador, edição de Gestão e financeira |

`components` financeiros: net_payout, taxes, operating_cost, ads, fees,
shipping, seller_discount, refunds e cogs. A conciliação manual substitui os
componentes daquele pedido e prevalece sobre novas estimativas de API.

Permissão `gestao_financeiro.ler` controla indicadores financeiros; acesso aos
pedidos individuais também exige `gestao_detalhes.ler`. Tabelas possuem RLS sem
políticas de navegador, e RPCs operacionais são exclusivas de service_role.
Novos recursos não concedem acesso automaticamente a setores existentes.

## Integrações e ativação

Configuração em `/configuracoes/integracoes/:id/insights`, seção **Dados e
inteligência** das contas Shopee e Mercado Livre. Gestão apresenta cobertura
e links para as contas. GET/PUT/POST em
`/api/v2/marketplace/installed/:id/insights` exigem administrador; configurações
financeiras também verificam a permissão financeira. Ações: enable, pause,
resume, run e backfill. Pausar/retomar preserva checkpoints; recuperar histórico
arquiva o checkpoint anterior antes de reiniciar a janela da capacidade.

Extração local é automática. Repasses Shopee e conciliação Mercado Livre são
solicitados automaticamente quando há identidade e lacuna financeira. Visitas,
contadores e publicidade exigem ativação explícita. Capacidades são resolvidas
na própria conta, sem fallback para ERP ou outra conta. Negação de acesso
suspende tentativas automáticas; retomar é uma ação explícita. Nenhuma ação
altera os escopos OAuth.

O orçamento analítico é compartilhado por aplicativo/provedor e limitado a 10%
da capacidade conhecida. `MARKETPLACE_INSIGHTS_BUDGET_FRACTION` pode reduzir
essa fração; `SHOPEE_KNOWN_RPS`, `MERCADOLIVRE_KNOWN_RPS` e `BLING_KNOWN_RPS`
configuram a capacidade. Sem configuração, o teto conservador é 0,1 req/s para
Shopee/ML e 0,3 req/s para Bling, além dos limitadores dos clientes existentes.
Limitação de orçamento preserva o checkpoint; erros transitórios recebem
retentativa progressiva, até seis horas. Solicitações financeiras estimadas
recebem até seis confirmações espaçadas (1, 2, 4, 8 e 16 dias entre consultas),
sem reconsultar integralmente pedidos encerrados a cada ciclo. Alteração
comercial ou recuperação explícita rearma a solicitação. Evidência sem repasse
completo continua incompleta; não é tratada como margem consolidada.

| Capacidade | Comportamento |
| --- | --- |
| shopee_escrow | Uma solicitação financeira por execução, repasse e evidências estimados até conciliação; não inventa tributos/despesas |
| shopee_product | Cinco anúncios por lote, contadores de vendas/visualizações/curtidas preservados como acumulados |
| shopee_ads | Resultados diários de loja, datas DD-MM-AAAA, janelas sobrepostas e upsert; revisita 14 dias para atribuição |
| ml_visits | Cinco anúncios por lote, visitas diárias dos últimos 90 dias |
| ml_ads | Advertiser MLB único ou advertiser_id explícito na configuração; métricas dos Ad Groups atuais, paginadas por dia |
| ml_billing | Uma solicitação por execução; evidências para conciliação, sem interpretar cobranças como repasse líquido |
| bling_history | Pedidos dos últimos 365 dias, cinco por página, via cliente com rate limit compartilhado e pipeline canônico existente |

Disponibilidade real, permissões e formatos precisam ser validados em cada
conta. Conciliação Mercado Livre ainda exige interpretação/manual dos documentos
coletados para informar um repasse completo; baixar evidência não torna uma
margem automaticamente consolidada. Atribuição de publicidade por grupo/loja
não é atribuída automaticamente a pedidos. Cadastro de custos não substitui
apuração contábil nem garante perdas/consumo realizado.

### Implantação

1. Aplicar as três migrações pelo processo habitual do projeto.
2. Publicar API, frontend com variáveis VITE_SUPABASE configuradas, beat e os
   serviços `nistiprint-gestao-projection-worker.service` e
   `nistiprint-marketplace-insights-worker.service`. Começar com
   `MARKETPLACE_INSIGHTS_ENABLED=0`, verificando a reutilização local e a projeção;
   ativar complementos com `MARKETPLACE_INSIGHTS_ENABLED=1` após conferir cobertura.
3. Conceder permissões por setor. Administradores existentes já passam pelo
   controle administrativo padrão.
4. Acompanhar `gestao_outbox`, erros do worker e cobertura do painel. O backfill
   é automático e os totais permanecem identificados como parciais enquanto há
   pendências.
5. Ativar visitas/publicidade por conta; conferir códigos de acesso, comparar
   amostras e totais com as plataformas e registrar conciliações/custos faltantes.

A implantação e a coleta nas contas reais não são realizadas pelos testes.
Para suspender os agendamentos: configurar `GESTAO_ENABLED=0` e reiniciar o beat;
preservar as tabelas históricas. Jobs já em andamento permanecem limitados pelo
tempo da tarefa. Falha de analytics não altera pedidos operacionais.

## Validação

- `python -m unittest discover -s packages/shared/tests/services -p "test_gestao*.py"`
- `python -m unittest discover -s apps/api/tests -p test_gestao_api.py`
- `python -m unittest discover -s apps/worker/tests -p test_gestao_tasks.py`
- PostgreSQL isolado: `scripts/check_gestao_sql.mjs`, com GESTAO_PGLITE_MODULE
  apontando para uma instalação temporária de PGlite; ou testes opcionais
  `test_gestao_postgres.py` com GESTAO_TEST_DSN apontando para banco descartável vazio.
- Agregados do painel: validar `regions_by_state` e `advertising_daily` com
  recortes vazios/incompletos, múltiplas contas e mais de 500 registros; conferir
  que publicidade não é retornada sem permissão financeira.
- Captura/concorrência/cache: `scripts/check_marketplace_insights.mjs`;
  `GESTAO_BENCHMARK=1` executa cargas sintéticas de 20 mil e 100 mil pedidos.
- Contratos locais e isolamento: `test_marketplace_insights.py`,
  `test_gestao_report_repository.py`, `test_marketplace_insights_api.py`.
- Frontend: build com configuração VITE válida, eslint do módulo e verificador
  de rotas. Prévia visual usa somente registros sintéticos.

Casos: pedidos/packs sem duplicação, comprador entre contas, vínculos ambíguos,
data sem horário, cancelamento/devolução, correções de personalização, custo
vigente, campos financeiros ausentes, taxa já descontada, acesso negado pelo
provedor, reexecução, geração concorrente, RLS e segregação financeira/detalhes.

Validação local: a suíte geral existente `test_celery_config.py` apresenta quatro
falhas de registro de tarefas Mercado Livre e um erro de configuração Supabase.
O mesmo resultado foi reproduzido carregando o arquivo original do HEAD, sem as
alterações de Gestão. Os testes específicos de Gestão executam sem essas
dependências externas. Os testes PostgreSQL opcionais exigem DSN explícito;
os contratos SQL equivalentes foram executados em PGlite isolado.

### Resultado da carga local (20/10/2026)

PGlite descartável, 20 amostras com cache SQL aquecido: p95 de 4 ms para
20 mil pedidos e 7 ms para 100 mil. Sem cache, consultas medidas entre
1,57–1,93 s e 5,55–8,18 s, respectivamente, após reduzir reconstruções de JSON e
cálculos de margem sem os componentes obrigatórios. Esses números medem SQL sintético,
não o p95 HTTP, as permissões reais das APIs ou o atraso de filas em produção.
A meta de regressão operacional de até 5% permanece como gate de implantação:
exige comparação da mesma carga no ambiente equivalente ao de produção.
Testes locais verificam zero chamadas HTTP na projeção, segregação entre contas,
versão obsoleta rejeitada, pausa, cache por revisão e permissões.
