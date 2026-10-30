# Catálogo, anúncios e Gestão — execução de 29/10/2026

## Estado da entrega

Alterações locais preparadas para revisão e publicação pelo responsável pelo
repositório. O usuário reservou para si commit e push; não houve commit, push,
merge, deploy da aplicação ou ativação de coletores novos nesta execução.

Sete migrações incrementais foram aplicadas pelo MCP Supabase HTTP. O histórico
comercial granular foi preenchido e reconciliado. A liberação integral em
produção ainda depende da publicação e do piloto completo de importação.
O acesso de leitura ao Mercado Livre passou a funcionar no reteste posterior
descrito abaixo. Não declarar o plano completo
até observar uma varredura completa e uma execução diária de estatísticas.

## Evidência da base

Consultas e migrações usaram o MCP HTTP configurado em
`http://127.0.0.1:18000/mcp`. Não foi usado `supabase db push`, nem reaplicado o
histórico local para tentar corrigir o drift. O túnel caiu durante a execução;
foi restabelecido pelo usuário e o ledger foi consultado antes de repetir DDL.

| Migração local | Nome e versão atribuída pelo MCP |
| --- | --- |
| `20261029180000_catalogo_completion.sql` | `catalogo_completion` — `20261029180806` |
| `20261029190000_gestao_historical_review.sql` | `gestao_historical_review` — `20261029180820` |
| `20261029200000_catalogo_clone_compat.sql` | `catalogo_clone_compat` — `20261029181508` |
| `20261029210000_catalogo_reconciliation_pending.sql` | `catalogo_reconciliation_pending` — `20261029182840` |
| `20261029220000_gestao_traffic_calendar.sql` | `gestao_traffic_calendar` — `20261029183823` |
| `20261029230000_gestao_preserve_attribution.sql` | `gestao_preserve_attribution` — `20261029185112` |
| `20261029235900_catalogo_canonical_activation.sql` | `catalogo_canonical_activation` — `20261029185126` |

O snapshot de funções anteriores está em `catalogo-baseline-20261029.sql`.
Esse arquivo é evidência, não uma migração a executar. Os objetos anteriores de
catálogo/Gestão já existiam, apesar de seus nomes não aparecerem no ledger;
portanto, a ausência dos nomes não foi tratada como ausência dos objetos.

Antes: 18.861 fatos de pedidos, zero fatos por item. Após o backfill: **18.861
pedidos materializados em 19.027 grupos**. A reconciliação por chave comercial
encontrou **zero grupos ausentes e zero diferenças de quantidade/subtotal**.
17.320 grupos continuaram sem produto atribuído: o backfill não resolveu
novamente vínculos históricos nem transformou pendências em atribuições.

Consulta de desempenho para 01–29/10/2026: 5.919 pedidos elegíveis, 6.178
unidades e R$ 243.482,74 em subtotais conhecidos. Cancelamentos, devoluções e
reembolsos aparecem em populações próprias. É uma evidência datada; os números
mudam com a operação normal.

## Correções implementadas

- A materialização falhava por ambiguidade entre o alias SQL `old` e o registro
  `OLD` do PL/pgSQL. A gravação de famílias também tinha ambiguidade entre a
  variável `nome` e a coluna homônima. Ambos os erros foram reproduzidos em
  PostgreSQL real e corrigidos.
- Backfill por RPC paginada, sem atualizar artificialmente os pedidos projetados
  ou disparar novamente solicitações financeiras. Atualizações ordinárias
  preservam atribuição tanto nos fatos granulares quanto no payload gerencial.
- Cadastro/edição individual de variações e serviço legado delegam à RPC de
  família. Clonagem preserva composição e materializa eixos/combinações na mesma
  transação. Ativação de clones valida o estado relacional final, evitando que o
  trigger legado inspecione um JSON ainda não projetado.
- Versão carregada junto do editor, sem buscar uma versão nova antes de salvar;
  prévia de diferenças, inativação explícita e rascunho preservado em conflitos.
- Unidades de modelo bloqueadas para vínculo vendável e novas movimentações
  diretas de estoque. Exclusão pelo serviço passa a inativar o produto.
- Aliases normalizados por conta; remoção dos índices legados que impediam
  códigos iguais em contas diferentes. Aliases sem aprovação geram pendência.
- Reconciliação atual preserva vínculos confirmados, não escolhe candidatos
  arbitrários e registra conflitos. Há reconciliação paginada independente da
  importação, além de tarefas retomáveis por página.
- Sincronização libera a posse entre páginas, rejeita trabalhador antigo e só
  marca ausências após varredura completa. Erros de permissão suspendem as
  tentativas automáticas. SKU/preço/atributos externos ficam separados.
- Estatísticas de tráfego têm token de posse, renovação e persistência
  transacional das projeções diária e por período. `Retry-After`, ausência,
  zero, parcialidade e contadores acumulados são preservados.
- Desempenho tem ordenação validada, paginação, cobertura e gráfico do recorte.
  Moedas não são somadas sem conversão. Visitas são compartilhadas no anúncio;
  razões comerciais não são calculadas entre calendários incompatíveis.
- Operações manuais de catálogo/reconciliação/backfill aparecem na Central de
  Operações existente. Atualizações meramente observacionais de anúncios não
  invalidam todo o histórico comercial da conta.

## Contratos acrescentados

- Fachada com conta obrigatória: capacidades, listagem, detalhes, variações e
  estatísticas normalizadas, com `ProviderCallResult`.
- `POST /api/v2/integracoes/{id}/catalogo/reconciliar`: agenda reconciliação
  atual, com `produtos.editar`, sem remapear fatos históricos.
- `GET /api/v2/gestao/desempenho`: acrescenta `sort` (`sales`, `orders`, `units`,
  `group_label`) e `direction` (`asc`, `desc`), `total_rows`, paginação e cobertura.
- `POST /api/v2/gestao/itens/reprocessamento/previa`: recebe `scope` com
  `account_id`, `date_from`, `date_to`, filtros opcionais `product_id` e
  `announcement_id`, mais `motivo`. Retorna contagens e token de 30 minutos.
- `POST /api/v2/gestao/itens/reprocessamento`: recebe o token, exige o mesmo
  administrador e permissões de produtos/relatórios, revalida a prévia e agenda
  execução. `GET /api/v2/gestao/itens/reprocessamento/{token}` consulta o estado.
  Mudança de catálogo/fatos invalida a prévia. A execução guarda o estado
  anterior, processa lotes transacionais e recupera solicitações confirmadas
  após interrupção do broker. **Nenhum reprocessamento histórico foi confirmado
  ou executado em produção nesta entrega.**

## Validação autenticada e impedimentos

**Shopee, conta 6:** listagem autenticada com cinco anúncios; detalhe do primeiro
com SKU; leitura de estatísticas com `sale`, `views` e `likes`. A marca
`config.catalog_statistics_validated=true` foi registrada, sem ativar coletas.
Esses campos são snapshots acumulados, não visitas diárias nem histórico
retroativo. Os testes de contrato usam dados sintéticos; credenciais e respostas
comerciais brutas não foram colocadas no repositório. A documentação oficial
autenticada ainda deve ser conferida no piloto antes da expansão.

**Mercado Livre, conta 7091:**

```text
GET /users/me                                      -> 200
GET /users/{seller_id}/items/search?search_type=scan&limit=10 -> 403
code: PA_UNAUTHORIZED_RESULT_FROM_POLICIES
seller_matches_token: true
```

A identidade do token e o vendedor configurado coincidem. O erro corresponde a
permissão funcional do aplicativo, segundo a [documentação do Mercado
Livre](https://developers.mercadolivre.com.br/pt_br/permissoes-funcionais/).
Conferir o acesso de leitura aos recursos de anúncios no aplicativo e eventual
reautorização exigida pela plataforma. Nenhum escopo OAuth foi alterado.
`marketplace_catalog_sync` dessa conta foi marcado como `unavailable`; a
retomada manual após corrigir a permissão permite sair desse estado.

Reteste após o usuário habilitar leitura: a listagem continuou em 403, com
`/users/me` em 200 e vendedor correspondente ao token. Para catálogo, conferir
**Publicação e sincronização → Leitura**; para visitas, **Métricas do negócio →
Leitura**. Conferir a mesma aplicação usada pela integração; eventual nova
autorização deve ser feita pelo titular. Webhooks não concedem essas permissões.

Diagnóstico posterior de autorização: `GET /applications/2056757525653794` e
`GET /users/{seller_id}/applications` responderam 200. A aplicação ativa
**Nisti Print - ERP**, perfil **ML CNPJ01**, já inclui
`urn:ml:mktp:publish-sync:/read-only`; o grant da conta, criado em
17/05/2026, não incluía esse escopo naquele teste. Essa diferença motivou a
recomendação de reautorizar, mas o resultado posterior abaixo dispensa essa
etapa para liberar o catálogo. Não foram renovados/revogados tokens
nem iniciada uma autorização em nome do titular.

**Reteste posterior com a configuração de produção, ainda sem publicar o código
local:** a listagem passou a funcionar (10 anúncios na primeira página e detalhe
do primeiro com SKU). O grant existente agora inclui `publish-sync:/read-only`,
mesmo mantendo a data original de criação. Não é necessário completar uma nova
autorização para liberar o acesso de leitura que já está funcionando.

A tentativa OAuth mostrou um problema independente: o perfil usado em produção
tem `redirect_uri` igual a
`https://app.nistiprint.neolabs.com.br/api/v2/marketplace/auth/callback/mercadolivre`,
enquanto a resposta atual de `/applications/2056757525653794` registra somente
`https://automacao.nistiprint.neolabs.com.br/webhook/ml-auth-callback` em
`callback_url`/`callback_urls`. Essa divergência explica o bloqueio antes do
retorno ao NistiPrint. Para futuras autorizações pelo aplicativo atual, cadastrar
também o callback do NistiPrint no DevCenter, mantendo o antigo se houver fluxo
n8n dependente. Não confundir esses callbacks OAuth com a URL de notificações.

**Verificação após a atualização do usuário:** `/applications` passou a retornar
os dois callbacks, incluindo exatamente o URI do NistiPrint. A autorização
atual respondeu normalmente à listagem (10 anúncios) e ao detalhe do primeiro
anúncio. Não é necessário repetir a autenticação para acessar o catálogo.
Essa verificação confirma a configuração e o acesso atual; não constitui prova
de que uma tentativa OAuth específica tenha sido concluída pelo callback.

Ao iniciar o consentimento foi identificado outro defeito: o gerador OAuth e
o cadastro estático do módulo apontavam para `auth.mercadolibre.com.br`, domínio
inválido para o Brasil. Ambos foram corrigidos localmente para
`auth.mercadolivre.com.br`, com regressão sobre o hostname da URL gerada e
preservação dos parâmetros de state, callback e PKCE. Até a publicação, pode-se
corrigir somente o hostname na URL recém-gerada, preservando sua query string.

A resposta da aplicação também contém escopos `urn:mp:...`. A documentação de
[gerenciamento de aplicativos](https://developers.mercadolivre.com.br/devcenter/gerencie-seu-aplicativo)
exige separar aplicações Mercado Livre e Mercado Pago desde 30/08/2026.
Esse é um segundo ponto a revisar caso o 403 persista após atualizar o grant;
não foi demonstrado que seja a causa desta resposta específica.

O roteamento usa lista explícita: `orders`, `orders_v2`, `shipments`, `payments`,
`messages` e `post_purchase` apenas para claims tipadas. Outros tópicos são
finalizados como `skipped_unsupported_topic`, sem resolver integração/pedido,
sem chamadas ao provider e sem retentativa. Foram acrescentadas regressões com
tópicos adicionais/desconhecidos e reconhecimento terminal na fila confiável.
Notificações `items` não disparam importações a cada evento nesta versão;
o catálogo continua por sincronização manual/periódica.

## Testes e segurança

- 276 testes operacionais passaram (`scripts/test_integridade.py`).
- 60 testes de Gestão passaram, incluindo **23 PostgreSQL reais, sem skips**:
  atomicidade, duas transações concorrentes, clonagem/ativação, leases,
  atribuição histórica, moedas distintas e tráfego compartilhado/calendários.
- 12 testes de catálogo/família, um de consultas de anúncios, 18 de API e seis
  de worker passaram.
- 55 testes frontend, verificação das 102 rotas e build passaram. ESLint dos
  módulos alterados: zero erros; permanece um aviso de dependência de hook no
  modal de variação. O build mantém avisos de tamanho de bundle/Browserslist.
- O CI foi ampliado para criar um banco PostgreSQL separado e executar essas
  suítes obrigatórias; o CI remoto aguarda o push do usuário.
- Advisors foram executados antes/depois. As tabelas novas com RLS sem policies
  são intencionais: acesso de domínio pelo backend, não pelo navegador. Os RPCs
  transacionais possuem grants restritos à role de serviço.
- Achados globais anteriores permanecem como acompanhamento fora deste escopo:
  104 funções com aviso de `search_path`, permissões públicas em funções antigas,
  duas extensões em `public`, sete grupos de índices duplicados e FKs sem índice.
  O ERROR anterior da view `public.vw_pedidos_pendentes_despacho` com
  `SECURITY DEFINER` não foi introduzido por esta entrega e precisa de revisão
  própria. [Remediação do advisor](https://supabase.com/docs/guides/database/database-linter?lint=0010_security_definer_view).

## Publicação e ativação pendentes

1. Revisar, fazer commit/push e aguardar CI. Não executar novamente os arquivos
   já aplicados; conferir os nomes/versões do ledger acima.
2. Publicar API/frontend/workers/beat pelo fluxo existente. Conferir o serviço
   `nistiprint-marketplace-analytics-worker.service`, concorrência um, e os
   serviços de projeção/insights. Instalar unit e permitir restart no sudoers se
   ainda não estiverem instalados. Não há evidência de restart nesta execução.
3. Começar com `MARKETPLACE_CATALOG_ENABLED=0` e
   `MARKETPLACE_STATISTICS_ENABLED=0`. A projeção e as tarefas financeiras
   existentes permanecem separadas das novas coletas de tráfego.
4. Pilotar importação completa e reconciliação na conta Shopee 6. Revisar amostra
   dos vínculos e das pendências; repetir a página para confirmar idempotência.
   Não inferir famílias pela decomposição de SKU.
5. Pilotar a conta Mercado Livre 7091, cujo acesso de leitura já foi validado.
   O callback do DevCenter já foi alinhado e verificado após a atualização do usuário.
6. Ativar catálogo a cada seis horas e, nas capacidades verificadas e habilitadas
   por conta, estatísticas às 03h de São Paulo. Reconsultar sete dias de visitas;
   o backfill de visitas mantém os limites do provedor. Reiniciar o beat, pois
   a configuração efetiva é carregada no início do processo.
7. Observar um ciclo completo de importação e uma execução diária. Conferir
   reconciliação dos totais, filas, falhas, atraso, cobertura e estoque/produção
   antes de ampliar para outras contas.

Retorno operacional: desativar os dois flags novos e pausar capacidades nas
contas; preservar tabelas, auditoria e fatos históricos. Não desfazer migrações
aditivas nem reintroduzir escritores independentes de JSON para reverter telas.
