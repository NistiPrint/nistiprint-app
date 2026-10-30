# Plano de desenvolvimento — replicação de marketplaces e desempenho

Data: 30/10/2026. Escopo inicial: Shopee e Mercado Livre, por conta integrada.

## Objetivo e limites

Construir uma réplica local confiável de catálogo, pedidos, movimentações
comerciais, logística, financeiro e métricas disponíveis em cada marketplace.
APIs são a fonte de consulta; webhooks antecipam a atualização; reconciliações
periódicas recuperam alterações perdidas. A aplicação consulta sua base local.

Esta etapa não publica nem altera anúncios, preços, estoques, promoções,
campanhas ou logística nos marketplaces. Chamadas necessárias de autenticação
e renovação de credenciais continuam permitidas. O coletor não deve acionar
operações comerciais nem fluxos de escrita existentes como efeito da ingestão.
As planilhas serão evidência de conferência e eventual complemento identificado,
sem se tornar dependência da coleta regular.

## Base que será reaproveitada

- Ingestão confiável, arquivo de eventos, correlação, isolamento por conta e
  projeção canônica de pedidos já existentes.
- Sincronização paginada de catálogo com checkpoints e leases, reconciliação
  dos vínculos e organização local de famílias.
- `produtos`, `marketplace_anuncios`, `produto_anuncios`, fatos por item,
  custos com vigência, financeiro e métricas por período.
- Filas de catálogo, insights e projeção, controle de capacidades por conta,
  orçamento de chamadas e Central de Operações.

## Entregas, em ordem de execução

### 1. Contratos de coleta e infraestrutura de replicação — P0

- Auditar código, configuração publicada e capacidades reais das contas. Registrar
  recursos acessíveis, permissões, tópicos de webhook, paginação, limites,
  histórico disponível, semântica e granularidade das métricas.
- Validar os contratos em documentação oficial e respostas autenticadas antes
  de habilitar cada capacidade. Capacidade indisponível deve ter motivo visível.
- Definir lista explícita de operações de leitura permitidas nos adaptadores.
  Testes devem rejeitar qualquer operação comercial de escrita nesses fluxos.
- Consolidar por plataforma/conta/recurso: identidade externa em texto,
  payload/versionamento, origem, versão externa quando disponível,
  instante de ocorrência, recebimento e consulta, fingerprint e correlação.
- Manter estado de coleta por recurso: última tentativa, último sucesso,
  checkpoint, falha, próxima tentativa e cobertura. Preservar evidência bruta
  com acesso restrito, sem credenciais em payloads ou logs.

Aceite: uma coleta pode ser interrompida e retomada sem duplicar registros;
erro em uma conta não impede outras; limites e indisponibilidade são respeitados.

### 2. Pedidos e eventos comerciais completos — P0

- Reutilizar o endpoint/fila de webhook; confirmar o recebimento após persistência
  durável e processar o recurso fora da requisição HTTP.
- Tratar eventos suportados de pedidos, pagamentos, envios, cancelamentos,
  devoluções e reembolsos. Consultar o detalhe oficial quando a notificação
  for apenas um aviso. Recursos desconhecidos ficam registrados, sem disparar
  consultas arbitrárias nem processamento de pedidos por engano.
- Persistir pedido, itens, unidades externas, quantidades, valores, moeda,
  descontos/frete informados, situação e marcos temporais disponíveis.
- Evitar duplicações, regressão por eventos atrasados e concorrência entre
  polling e webhook. Agrupar avisos repetidos do mesmo recurso antes de consultar.
- Fazer carga inicial dos últimos 90 dias, limitada ao histórico acessível;
  registrar explicitamente períodos sem acesso. Retomar por conta e janela.
- Reconciliar a cada 15 minutos uma janela sobreposta de 72 horas; revisar
  diariamente pedidos ainda abertos e casos financeiros/devoluções pendentes,
  inclusive anteriores à janela. Adaptar os lotes ao orçamento de chamadas.
- Preservar atribuição histórica dos itens e a separação de eventos elegíveis,
  cancelados, devolvidos e reembolsados.

Aceite: repetição e reordenação de eventos não duplicam vendas nem fazem pedidos
regredir; um webhook perdido é recuperado pela reconciliação.

### 3. Catálogo, unidades e logística replicados — P0

- Completar anúncio: identificação, SKU de referência, título, descrição,
  situação, categoria/marca externas, imagens ordenadas e atualização da origem.
- Completar unidade comercial: identificador e nome externos, atributos,
  SKU, GTIN observado, preço/moeda, disponibilidade numérica e seu significado.
  Distinguir estoque disponível para venda de saldo físico interno.
- Replicar peso, dimensões e unidade de medida da embalagem no escopo fornecido
  pelo marketplace; permitir valores por anúncio e exceções por unidade.
- Representar canais logísticos por código externo/plataforma/conta,
  habilitação, escopo/herança e tarifas observadas com moeda e data.
- Reutilizar os campos físicos/GTIN já existentes de produtos quando houver
  correspondência revisada. O valor observado no anúncio permanece separado
  do cadastro canônico. Divergência gera pendência, sem sobrescrita automática.
- Incorporar notificações de catálogo suportadas a um handler próprio; elas
  devem atualizar o recurso específico, sem iniciar varredura da conta a cada
  evento. Manter varredura completa a cada seis horas.
- Registrar ausências somente após varredura completa bem-sucedida. Preservar
  diferenças entre vazio, ausente, zero, desativado e resposta parcial.
- Manter organização de famílias como projeção interna, preservando IDs,
  composição, saldos e vínculos históricos.

Aceite: comparar a réplica Shopee com os arquivos fornecidos, explicando os
dois anúncios/cinco unidades exclusivos de sales_info; todas as divergências
de identidade, GTIN, embalagem e cobertura devem estar classificadas.

### 4. Financeiro e resultado comercial — P1

- Completar leitura de valores cobrados, descontos/subsídios, comissões,
  tarifas, frete, reembolsos, ajustes e repasses conforme os contratos validados.
- Relacionar os componentes ao pedido e à unidade quando a origem permitir;
  valores apenas por pedido permanecem nesse nível até haver regra de rateio
  explícita, identificada como calculada.
- Separar valor dos itens, total pago pelo comprador, repasse e margem.
  Preservar estimado/confirmado/liquidado, moeda e revisão de cada informação.
- Coletar a cada seis horas os últimos 30 dias e revisar diariamente casos
  pendentes mais antigos até alcançar o estado terminal definido pela origem.
- Calcular resultado com custos vigentes na venda e componentes financeiros
  conhecidos, sem descontar novamente taxas já embutidas no repasse líquido.
  Cobertura incompleta gera resultado parcial ou indisponível, não zero.

Aceite: amostra de pedidos confere com o demonstrativo da plataforma;
cancelamentos, ajustes e reembolsos corrigem as projeções sem duplicação.

### 5. Tráfego, publicidade e histórico de performance — P1

- Validar e habilitar por conta as capacidades de visualizações/visitas,
  curtidas, avaliações, campanhas e desempenho de publicidade disponíveis.
- Preservar granularidade original: conta, campanha, anúncio ou unidade;
  contadores acumulados, valores diários e intervalos são tipos distintos.
- Coletar diariamente às 03h de São Paulo. Reconsultar sete dias recentes onde
  a API permitir revisões; janelas e datas consultadas seguem o fuso do contrato
  da origem. Contadores acumulados ganham snapshots a partir da ativação.
- Guardar investimento, impressões, cliques, vendas atribuídas e janela/modelo
  de atribuição quando fornecidos. Evitar somar venda atribuída à venda orgânica
  como se fossem receitas independentes.
- Calcular conversão e retorno apenas com numerador, denominador, período,
  granularidade e atribuição compatíveis. Não duplicar visitas nas variações.
- Conservar histórico de preço, disponibilidade e situação para análise de
  mudanças; falta de acesso ou dado permanece explicitamente indisponível.

Aceite: indicadores rastreáveis à origem e reproduzíveis por período;
nenhum contador acumulado aparece como movimento diário ou histórico inferido.

### 6. APIs locais, telas e operação — P1/P2

- Evoluir as consultas existentes de produtos, anúncios e desempenho, usando
  exclusivamente a réplica para navegação normal, com paginação no banco.
- Acrescentar consultas de saúde da replicação, capacidades e divergências por
  plataforma/conta/recurso; comandos locais para agendar coleta, reconciliar
  e repetir falhas retornam uma operação assíncrona, sem escrita no marketplace.
- Oferecer filtros por plataforma, conta, anúncio, família, produto, período,
  situação e moeda; mostrar origem, atualização e cobertura nos resultados.
- Entregar primeiro catálogo e pedidos consultáveis; depois painéis de vendas,
  repasses/margem e tráfego/publicidade conforme cada capacidade validada.
- Central de Operações mostra progresso e falhas; alertas cobrem atraso,
  credencial expirada, coleta incompleta e divergências persistentes.

## Modelo de dados e contratos

- Preservar o modelo canônico atual e adicionar campos/tabelas para conteúdo
  comercial externo, embalagem por escopo, canais logísticos e observações
  históricas. Acrescentar índices por conta/recurso/data e restrições de identidade.
- Dados comuns e usados em filtros ficam tipados; extensões específicas do
  provedor e evidência bruta ficam em JSON com versão de formato.
- Identidade de unidade usa conta + anúncio externo + unidade externa;
  SKU, GTIN e nome são atributos opcionais, nunca a chave de deduplicação.
- Toda métrica informa origem, recurso, período/fuso, moeda quando aplicável,
  semântica, parcialidade e instante de coleta. Valores monetários usam decimal.
- Notificações e snapshots preservam tempos distintos; a ordenação de aplicação
  usa versão da origem ou serialização por recurso quando ela não existir.
- Novas tabelas e RPCs seguem acesso restrito pelo backend. Contas e permissões
  são verificadas também nos endpoints locais de consulta e reprocessamento.

## Validação e implantação

1. Testes de contrato dos adaptadores com respostas completas, parciais, vazias,
   sem permissão, limites e mudanças de campos; testes de ausência de escrita.
2. PostgreSQL real: atomicidade, duplicação, concorrência, eventos fora de ordem,
   recuperação de checkpoints e separação entre contas com IDs externos iguais.
3. Testes ponta a ponta de webhook até consulta local, backfill junto com eventos
   ao vivo e reprocessamento sem alterações comerciais indevidas.
4. Reconciliação com planilhas, pedidos e demonstrativos da origem, usando o
   mesmo período e escopo. Toda diferença deve estar resolvida ou explicada.
5. Migrações aditivas, verificação do ledger, capacidades inicialmente
   desabilitadas e piloto em uma conta Shopee; depois uma conta Mercado Livre.
6. Ampliar após observar webhook, varredura completa, recuperação de lacuna e
   coleta diária de métricas. Proposta de metas operacionais: webhook persistido
   em até 2s no p95 e recurso atualizado em até 5 minutos no p95, sob orçamento
   e disponibilidade normais da origem; exibir atrasos quando essas condições
   não forem atendidas.
7. Retorno operacional desabilita os coletores novos por capacidade/conta e
   preserva réplica, evidências e histórico. Não altera os dados do marketplace.

## Decisões e premissas

- Primeiro ciclo cobre as integrações Shopee e Mercado Livre existentes.
  Outros provedores entram depois pelos mesmos contratos de leitura.
- As frequências e janelas acima são defaults de desenvolvimento; limites
  confirmados por conta prevalecem e são apresentados como cobertura efetiva.
- A conclusão de cada entrega depende da coleta validada, e não apenas da
  existência de uma tabela ou tela. Recursos indisponíveis não bloqueiam a
  liberação dos recursos independentes já confiáveis.
- Nenhum desenvolvimento de publicação externa integra este plano.
