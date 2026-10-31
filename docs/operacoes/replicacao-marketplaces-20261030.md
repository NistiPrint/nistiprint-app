# Replicação de marketplaces — acompanhamento de 30/10/2026

## Estado

O desenvolvimento está em andamento. As migrações `catalogo_observacoes`,
`catalogo_webhook`, `replicacao_pedidos`, `mercadolivre_taxa_venda`,
`mercadolivre_taxa_pacotes`, `catalogo_tempo_observacao`, `replicacao_operacao`
e `mercadolivre_taxa_automatica` foram aplicadas pelo MCP; seus arquivos locais são
incrementais e não devem ser reaplicados sem conferir o ledger remoto.

O código de API, frontend e workers está no checkout e depende da publicação
para executar em produção. A réplica comercial não envia alterações aos
marketplaces. A coleta periódica nova inicia desabilitada por
`MARKETPLACE_ORDER_REPLICATION_ENABLED=0`; a ativação requer publicação,
configuração explícita e piloto acompanhado.

## Catálogo

- Adaptadores retornam campos observados extras, com lista explícita de rotas
  de leitura e armazenamento separado do produto interno.
- A notificação `items` do Mercado Livre é identificada como catálogo. O fluxo
  confirma a conta autenticada, verifica o vendedor do anúncio, consulta apenas
  o recurso e reconcilia os vínculos. A gravação pontual e a varredura completa
  mantêm checkpoints separados e descartam observações anteriores.
- Testados gravação, lease expirado, página antiga após atualização pontual,
  conta divergente e duas atualizações concorrentes no PostgreSQL descartável.
- Esses testes não substituem um webhook real após publicar o worker; é preciso
  acompanhar o evento e uma varredura completa antes de declarar o ciclo validado.

## Pedidos

- A carga histórica local foi ampliada para a data de criação desde
  01/01/2025, horário de São Paulo, em fatias diárias da mais recente para a
  mais antiga. O término da busca indica somente que as páginas responderam;
  não confirma disponibilidade integral do histórico na plataforma.
  O processamento é deliberadamente simples, com uma ordem por página e
  checkpoint entre páginas; a carga histórica é pontual.
- A documentação do Mercado Livre informa retenção de até 12 meses na busca
  de pedidos e exclusão de cancelados na consulta como vendedor. Assim, a parte
  anterior pode exigir dados já existentes ou exportações oficiais; não tratar
  períodos sem resultados como prova de ausência de vendas. A disponibilidade
  histórica da Shopee ainda precisa ser medida com a conta autorizada.
- Em 31/10/2026, ambas as migrações passaram no PostgreSQL descartável e
  foram aplicadas em produção após conferência do histórico remoto. Uma
  consulta autenticada de 01/01/2025 retornou dez pedidos Shopee e outra
  página; a busca Mercado Livre respondeu sem resultados para o mesmo dia,
  resultado que não comprova ausência de vendas.

- A coleta por conta usa janela móvel de 72 horas, checkpoint e lease no banco;
  pode reavaliar dados de até 90 dias em fatias de um dia, para reduzir o risco
  de atingir o limite de paginação em contas com muitas vendas.
- Foi validada uma chamada autenticada de listagem: a primeira página Shopee
  retornou dez pedidos e continuação; a primeira página Mercado Livre retornou
  dez de 491 pedidos na janela. Não foi executada a carga completa em produção.
- A consulta do Mercado Livre usa `order.date_last_updated.from/to`. A
  [documentação oficial](https://developers.mercadolivre.com.br/pt_br/gerenciamento-de-vendas/gerenciamento-de-vendas)
  informa que buscas como vendedor filtram pedidos cancelados e que os filtros
  de data consideram somente até a hora. Cancelamentos precisam de eventos e
  revisão de pedidos conhecidos; a busca não comprova cobertura integral.
- A coleta respeita o orçamento compartilhado e o prazo de nova tentativa do
  provedor. Atingir o limite de paginação suspende a conta com erro explícito;
  não é tratado como conclusão. A carga histórica exige administrador e pode
  ser retomada após interrupção pelo checkpoint.
- Falta executar o piloto e confirmar ciclos completos, recuperação de eventos
  perdidos, cobertura dos cancelados e tempo de processamento sob o volume real.

## Financeiro

- Os registros `ml_billing` já existentes têm resposta bruta e não continham
  componentes normalizados. A taxa líquida de venda documentada foi extraída
  apenas de resposta completa, sem erros e com uma correspondência única do
  ID do pedido. Em pacotes, outros pedidos são ignorados sem somar seus valores.
- Ao final, 4.033 dos 4.033 registros consultados tinham `sale_fee`; uma
  repetição completa não fez alterações. Nenhum repasse líquido foi inferido.
  Os lotes e a repetição estão em `temp/replicacao-20261030/` (ignorado pelo Git).
- Um gatilho de banco aplica a mesma validação a novas respostas do coletor
  legado. Dados parciais removem a taxa atual, sem alterar outros componentes
  ou a conciliação manual; a revisão financeira anterior permanece no histórico.
- A fila de projeção foi observada vazia após o processamento. A tela local de
  rentabilidade mostra a taxa como componente, separada do repasse e da margem.
- A resposta ainda não comprova cobertura de todas as taxas, custos, tributos,
  repasses ou liquidação. O Mercado Livre recomenda consultar detalhes de billing
  de forma sequencial e com cache, conforme suas [boas práticas](https://developers.mercadolivre.com.br/pt_br/referencias-de-dominios-produtos-e-atributos-para-autopecas/boas-praticas-para-o-consumo-das-apis-de-relatorios-de-faturamento).

## Validação realizada

- Testes focados de adaptadores, webhook, conta, coleta e financeiro; PostgreSQL
  descartável para atomicidade, concorrência, lease, retomada e idempotência.
- Suíte de integridade operacional e build frontend; confirmar novamente após
  as últimas alterações antes da publicação.
- As migrações e cenários SQL foram incorporados à suíte de PostgreSQL do CI;
  28 testes passaram em um banco descartável recém-criado.
- Fonte de verdade da publicação é um commit no repositório: `deploy.sh` usa
  `git reset --hard` para o commit publicado. Não executar o script contra
  alterações ainda não commitadas esperando que elas sejam implantadas.
