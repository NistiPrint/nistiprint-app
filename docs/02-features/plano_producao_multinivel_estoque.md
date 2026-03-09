# Relatório Técnico (Revisado): Evolução da Produção Multi-nível e Controle de Estoque

## 1. Alinhamento de Processo e Colunas Atuais

Após revisão do processo de negócio, confirmamos que o dashboard já contempla as etapas necessárias, mas requer a implementação da lógica de dependência entre elas. O fluxo de vida de uma capa no sistema é:

| Coluna Dashboard | Role do Produto (BOM) | Descrição do Processo | Ação no Estoque (JIT) |
| :--- | :--- | :--- | :--- |
| `capas_impressas_qtd` | `CAPA_IMPRESSAO` | Impressão da arte em papel adesivo. | Consome: Papel Adesivo, Tinta. |
| `capas_produzidas_qtd`| `CAPA_ACABADA` | Montagem da Capa Dura (Fechamento). | Consome: `CAPA_IMPRESSAO`, Papelão, Elástico, etc. |
| `capas_prontas_retirada_qtd` | (N/A) | Casamento administrativo com o pedido. | Movimentação visual de prontidão. |

## 2. Diagnóstico da Falha de Continuidade

O problema central não é a falta de colunas, mas a **interrupção da cadeia de suprimentos automatizada**:

1.  **Falta de Recursividade**: Quando o usuário registra um incremento em `capas_produzidas_qtd`, o sistema tenta consumir a `CAPA_IMPRESSAO` do estoque. Se não houver saldo de `CAPA_IMPRESSAO`, o estoque fica negativo em vez de disparar a produção automática da impressão (nível inferior).
2.  **Desconexão de Incremento**: Atualmente, o sistema permite incrementar uma etapa avançada sem que a anterior tenha sido registrada. Se 10 capas forem "Produzidas", o sistema deve assegurar que 10 capas foram "Impressas", mantendo a integridade dos dados granulares.

## 3. Sugestão de Solução Técnica (Atualizada)

### 3.1. Motor de Produção JIT Recursivo
A alteração principal deve ocorrer no `nistiprint_shared/services/demanda_producao_service.py`. 

A função de alocação deve ser alterada para:
- Ao solicitar a produção de um item (ex: `CAPA_ACABADA`):
  - Percorrer os componentes da sua Ficha Técnica (BOM).
  - Para cada componente que for identificado como "Produzível" (possui Role de Miolo ou Capa):
    - Se `Estoque_Disponivel < Quantidade_Necessaria`:
      - Disparar automaticamente o processo de produção para esse componente (gerando as entradas/saídas de insumos básicos como Tinta e Papel).
  - Só então efetivar a produção do item pai.

### 3.2. Sincronização de Cadeia no Dashboard
Implementar uma regra de "Preenchimento Automático por Cascata" no backend (`registrar_producao_lote`):
- Se `Novo_Valor` de `capas_produzidas_qtd` > `capas_impressas_qtd`:
  - O sistema deve igualar `capas_impressas_qtd = Novo_Valor`.

## 4. Evolução da Interface (UX/UI) - Controle de Produção

Atualmente, a tela de `ControleProducaoPage.jsx` possui duas abas principais: **Miolos** e **Capas (Impressão)**. 

### 4.1. Recomendação de Estrutura
Para a inclusão da etapa de **Capas Produzidas (Fechamento)**, a melhor abordagem de UX é a utilização de **Sub-Abas** dentro da categoria "Capas":

- **Justificativa**: O colaborador que trabalha com capas geralmente lida com o fluxo completo (impressão -> fechamento). Criar um novo item de menu principal fragmentaria o processo. Manter dentro de "Capas" centraliza o contexto e permite que o usuário alterne rapidamente entre "O que preciso imprimir?" e "O que preciso fechar?".
- **Novo Layout Sugerido**:
  - Aba Principal: `Miolos`
  - Aba Principal: `Capas`
    - Sub-Aba: `Impressão` (Visualiza demandas aguardando `capas_impressas_qtd`)
    - Sub-Aba: `Fechamento / Produção` (Visualiza demandas que já têm impressão mas aguardam `capas_produzidas_qtd`)

### 4.2. Funcionalidade de Registro Facilitado
Na nova aba de "Fechamento", o sistema deve exibir o saldo de capas impressas disponíveis para aquele SKU. Ao registrar a produção de uma capa acabada, o sistema deve sugerir automaticamente a baixa da capa impressa correspondente, simplificando a jornada do usuário.

## 5. Resiliência e Desacoplamento (Prioridade de Operação)

1.  **Independência de Falha (Fail-Safe)**: A atualização do progresso visual no dashboard é a operação primária. Erros de estoque não devem travar o registro do colaborador.
2.  **Processamento "Best-Effort"**: O motor JIT tenta a recursividade; se falhar, loga o erro para auditoria administrativa sem interromper o fluxo da fábrica.

## 6. Plano de Implementação Sugerido

1.  **Backend**: Atualizar `processar_alocacao_de_demanda_otimizado` para suportar a recursividade e cascata.
2.  **Frontend**: Refatorar `ControleProducaoPage.jsx` para introduzir o sistema de sub-abas em "Capas".
3.  **Configuração**: Adicionar a nova Role `CAPA_FECHADA` (ou reutilizar `CAPA_ACABADA` conforme alinhado) no mapeamento de estágios.

Este plano consolidado garante que a evolução técnica do estoque acompanhe uma interface intuitiva, mantendo a agilidade operacional necessária para a gráfica.
