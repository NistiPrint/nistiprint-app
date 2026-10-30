# Revisão do modelo a partir das planilhas Shopee — 30/10/2026

Fontes: `basic_info.xlsx`, `sales_info.xlsx` e `shipping_info.xlsx` fornecidas
pelo usuário, código do catálogo/Gestão e esquema atual consultado em leitura.
Conteúdos descritivos e instruções do template foram tratados como dados.
Nenhum cadastro ou valor comercial foi alterado nesta revisão.

## Evidências

| Arquivo | Anúncios distintos | Linhas de dados | Conteúdo |
| --- | ---: | ---: | --- |
| basic_info | 297 | 297 | Identificação, SKU de referência, título e descrição |
| sales_info | 299 | 492 | Identificação da unidade, nome, SKU, preço, GTIN e estoque |
| shipping_info | 297 | 487 | Identificação da unidade, peso, dimensões e canais logísticos |

`sales_info` é um retrato de configuração comercial, sem histórico de vendas.
Há cinco unidades, de dois anúncios, presentes somente nesse arquivo:
`58212864113` e `58263073466`. Os arquivos devem ser reconciliados por chaves,
sem pressupor que representam exatamente o mesmo conjunto no mesmo instante.

- Nove anúncios em basic_info não têm SKU de referência.
- Em sales_info, 247 linhas não têm SKU da unidade; cinco não têm nenhum dos
  dois SKUs. Os SKUs de unidade preenchidos não se repetem nesse arquivo.
- Todas as 492 linhas de sales_info têm identificador de unidade; 241 não têm
  nome de variação. Nome vazio não significa ausência de unidade identificável.
- Há 44 GTINs ausentes e 19 valores repetidos em mais de uma linha, incluindo
  o preenchimento `00`. GTIN e SKU não devem ser chaves de identidade externa.
- Não há preços nulos/zero/negativos na leitura feita; três unidades têm estoque
  zero, apesar de os arquivos serem um recorte informado como anúncios ativos.
- Todas as 487 linhas de shipping_info têm peso e três dimensões preenchidos.
  No anúncio `22496945684`, o peso varia entre opções: 0,62 e 0,63 kg.
- Os canais identificados no template são Turbo (9101), Retirada pelo Comprador
  (90024), Entrega Rápida (90033), Shopee Xpress (91003) e Expresso Aéreo (91006).
  Há valores `Ligado`, `Desativado` e células vazias. Vazio não deve ser
  convertido automaticamente em desativado; a possibilidade de herança do
  anúncio deve ser validada na importação.

## Diagnóstico do sistema existente

A separação entre `produtos`, `marketplace_anuncios`, `produto_anuncios` e fatos
de pedidos está correta e deve ser mantida. A conta integrada já delimita os
identificadores externos. A família interna não precisa espelhar cada anúncio.

O banco já possui em produtos: `gtin`, `gtin_embalagem`, `marca`, `peso_liquido`,
`peso_bruto`, `comprimento`, `largura` e `altura`. Na consulta realizada, nenhum
dos 3.979 produtos tinha GTIN, peso bruto ou as três dimensões preenchidos.
O caminho atual de cadastro/sincronização examinado não utiliza esses campos.

O catálogo sincronizado mantém título, imagem principal, identificação externa,
situação, preço observado e disponibilidade, mas não oferece uma representação
completa de descrição comercial, identificadores, embalagem e canais logísticos
por anúncio/unidade. O adaptador de catálogo examinado realiza leituras; ainda
falta um fluxo completo para publicar alterações e acompanhar sua confirmação.

Gestão já possui fatos por pedido/item, custos com vigência, financeiro,
métricas por período e estado das coletas. Não é necessário reconstruí-la.
O coletor Shopee de catálogo trata vendas/visualizações/curtidas como contadores
acumulados; isso não fornece diretamente um histórico diário retroativo.

## Alterações recomendadas

1. **Completar o cadastro canônico.** Expor e persistir os campos físicos e GTIN
   existentes. Separar a medida do produto da embalagem de envio quando forem
   diferentes. Adotar unidades explícitas e confirmar a unidade das dimensões
   do template antes de converter. Validar GTIN mantendo o texto original e a
   pendência, sem substituir identificadores por um código inventado.
2. **Enriquecer anúncio e unidade comercial.** Guardar SKU de referência,
   descrição, categoria/marca externas, imagens ordenadas e rótulo externo da
   unidade. No nível da unidade: GTIN observado, preço/moeda, disponibilidade
   numérica com seu significado e embalagem específica. Conservar atributos
   estruturados de variação e o nome externo original.
3. **Modelar logística da oferta.** Criar registros de canais por plataforma e
   conta, identificados pelo código externo, com nome, habilitação, escopo,
   tarifa observada, moeda e instante de coleta. Permitir configurações no
   anúncio e exceções por unidade, preservando origem/herança. Tarifa do template
   não equivale ao frete efetivamente cobrado em um pedido.
4. **Separar leitura de intenção de publicação.** Preservar os valores observados
   na plataforma e registrar alterações desejadas em operações próprias, com
   revisão, idempotência, tentativa, erro, confirmação e auditoria. Uma falha
   externa não pode aparecer como uma edição já publicada. Preço e estoque
   internos não devem ser sobrescritos apenas porque uma planilha foi recebida.
5. **Adicionar importação reconciliável.** Registrar conta, tipo de arquivo,
   impressão digital, instante, escopo declarado e resultado por linha. Usar
   `(conta, anúncio externo, unidade externa)` como referência, com IDs em texto.
   Ler cabeçalhos técnicos do template e ignorar suas linhas auxiliares.
   Preservar diferença entre ausência, vazio, zero e desativado. Não inativar
   anúncios ausentes de uma planilha sem comprovar completude do recorte.
6. **Evoluir histórico e desempenho.** Acrescentar histórico de preço,
   disponibilidade e configuração, para relacionar mudanças a resultados.
   Manter os fatos comerciais com a atribuição histórica e custos vigentes,
   sem remapear vendas antigas quando o catálogo for reorganizado.

Campos comuns devem ter estrutura consultável; particularidades e evidência
bruta do provedor podem ficar em JSON versionado. Evitar tanto duplicar tabelas
inteiras por marketplace quanto colocar todos os campos em um JSON genérico.

## Visão de produto e prioridades

- **Primeiro:** reconciliação dos arquivos e preenchimento revisado de campos
  existentes; embalagem/logística; pendências de identificação e cobertura.
- **Depois:** editor de anúncios por conta/plataforma, com alterações de conteúdo,
  preço, estoque e logística e acompanhamento das publicações.
- **Em paralelo à base confiável:** desempenho por plataforma, conta, anúncio,
  família e produto vendável: pedidos, unidades, faturamento dos itens,
  cancelamentos/devoluções, repasses e margem conforme cobertura dos custos.
- **Etapa seguinte:** tráfego e conversão quando houver métricas comparáveis;
  campanhas, investimento e retorno quando houver atribuição e permissões;
  alertas de ruptura, divergência, degradação de margem e falha de sincronização.

Cada indicador deve mostrar origem, período, moeda, atualização e cobertura.
Visitas de um anúncio não devem ser duplicadas para cada variação. Contadores
acumulados não devem ser apresentados como movimento diário. Publicidade e
venda orgânica precisam de atribuição explícita para evitar dupla contagem.

As planilhas não bastam para confirmar capacidades/permissões das APIs de
edição, promoções, publicidade ou histórico de tráfego. Esses contratos devem
ser validados por plataforma/conta antes de prometer funcionalidades ou fontes
de indicadores. O portal público oficial consultado retornou HTTP 403.
