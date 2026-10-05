# Manutencao logistica dos marketplaces

A tela Configuracoes → Janelas de despacho possui tres abas: Modalidades,
Identificadores de envio e Agenda e regras. Modalidades e identificadores sao
compartilhados pelas contas do mesmo marketplace; horarios pertencem a cada conta.

## Uso

1. Cadastre a modalidade com prazo por janela ou minutos apos a venda, politica de
   lote, prioridade e participacao na torre. Codigo e marketplace nao mudam depois
   do cadastro. Desative modalidades antigas para preservar o historico. Uma
   modalidade vinculada exige outro cadastro para mudar o tipo de prazo.
2. Associe o identificador informado na venda. Pode ser cadastrado antes de haver
   vendas. Servico e tags opcionais distinguem identificadores iguais; associacoes
   especificas vencem as gerais. Um identificador desconhecido fica nao classificado.
   O fallback canonico so atende vendas sem identificador.
3. Na conta, escolha agenda manual ou sincronizacao Mercado Livre. Configure corte
   fixo, informado pelo marketplace ou minutos antes do inicio da coleta. Os horarios
   manuais servem de contingencia quando nao existe um dia no cache. Um dia
   explicitamente sem atendimento nao usa contingencia.
4. Consulte a data e registre uma excecao com motivo, varias faixas ou sem coleta.
   Restaurar agenda original remove somente a excecao daquela regra/data.

## Prazos, alertas e saida

O SLA `/shipments/{id}/sla.expected_date` alimenta `pedidos.data_limite_envio`.
Agenda, corte e prazo oficial permanecem separados. SLA vazio/indisponivel conserva
o valor existente e a origem no snapshot. `buffering.date` nao e prazo oficial.
Snapshots legados que possuem esse campo sem SLA sao marcados para reconciliacao.

Os alertas aparecem em producao, despacho e estoque desde prazo menos antecedencia
(60 minutos por padrao), inclusive em pedidos cuja demanda ja foi publicada.
Continuam apos o vencimento ate a saida ou encerramento. A lista consulta o servidor
a cada minuto; o contador funciona entre consultas. Pedidos prontos aguardando
coleta aparecem separados dos que ainda estao em preparacao.

Demandas em rascunho acompanham a agenda e suas faixas. Publicadas conservam os
horarios e o prazo registrados, mostrando divergencias quando a agenda/SLA muda.
`despachado_em` continua sendo a publicacao da demanda.

Notificacoes `shipments` entram pelo N8N e sao verificadas/processadas na pipeline
existente do worker. O recurso atual e consultado, incluindo todos os pedidos do
envio. `ready_to_print` nao confirma coleta; `shipped`, `picked_up`,
`authorized_by_carrier` e `in_hub` usam o normalizador existente. O horario fisico
vem do envio/historico; sem ele, `coleta_confirmada_observada_em` registra somente
quando o fato foi observado. `order.date_closed` nao preenche data de coleta.
Eventos repetidos/antigos seguem a transacao canonica; esta entrega nao adiciona
movimentacao de estoque nem mensagens aos clientes.

## Ativacao

As migrations `20261002120000` e `20261002121000` precisam ser aplicadas antes de
publicar API, frontend e worker. Reinicie worker/beat para registrar as novas tasks.
As regras existentes recebem agenda manual, corte fixo e alerta de 60 minutos.

Habilite a agenda automatica em uma conta ML com uma origem de expedicao e compare
as faixas com o painel do marketplace antes de ampliar. Contas sem credenciais ou
com a tag `warehouse_management` ficam com cache/contingencia e motivo visivel;
devem manter a agenda manual. O botao Atualizar agora enfileira a consulta.

A agenda e os envios ativos sao reconciliados a cada 15 minutos; os envios usam
lotes de ate 40 pedidos, cursor e deduplicacao por shipment/conta. A API renova OAuth
apos 401, respeita `Retry-After` e conserva o cache em falhas, avisando depois de
30 minutos. Janelas vencidas sao verificadas a cada minuto, com registro idempotente
e recuperacao desde a ultima consulta concluida, mantendo uma janela minima de
26 horas. Falhas nao avancam esse registro; uma interrupcao prolongada e recuperada
na proxima execucao. O recalculo tambem se repete se a interrupcao acontecer depois
de registrar a janela e antes de atualizar os pedidos.

No painel da aplicacao Mercado Livre, confirme a assinatura do topico `shipments`
e o callback N8N. O export do workflow preserva corpo, `x-signature` e
`x-request-id`; a validacao usa a politica de assinatura e o segredo existentes
(`INGEST_SIGNATURE_POLICY_MERCADOLIVRE`, `INGEST_WEBHOOK_SECRETS_MERCADOLIVRE`).
Os testes verificam a pipeline assinada; nao alteram a configuracao remota do app.

## Validacao local

Execute `python packages/shared/tests/run_logistica.py` com as dependencias do
projeto. O runner usa um endereco local e chave ficticia para impedir acesso ao
Supabase de producao durante os testes.

O SQL pode ser executado em banco de testes apos as migrations com
`psql -v ON_ERROR_STOP=1 -f supabase/tests/logistica_agenda_e_alertas.sql`.
Alternativamente, instale `@electric-sql/pglite` em `temp/logistica-sql` e execute
`node supabase/tests/run_logistica.mjs`. Esse runner cria apenas o esquema minimo
isolado e aplica as duas migrations e os cenarios de regressao, sem dados reais.

Conclua com `npm run build` em `apps/frontend`. Esta entrega foi validada localmente;
nao aplica migrations nem habilita sincronizacao em contas de producao.
