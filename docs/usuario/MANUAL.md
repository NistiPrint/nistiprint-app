# Manual do Usuário - Nistiprint

**Última atualização:** 2026-04-02  
**Status:** Consolidado

Este documento descreve os fluxos de usuário, interface e operações do sistema Nistiprint.

---

## 1. Visão Geral do Sistema

### 1.1 O que é o Nistiprint?

O Nistiprint é um sistema de gestão de produção que consolida pedidos de múltiplas plataformas (Shopee, Mercado Livre, Amazon, etc.) em demandas de produção organizadas para a fábrica.

### 1.2 Princípios de Design

| Princípio | Descrição |
|-----------|-----------|
| **O usuário nunca consolida do zero** | O sistema pré-monta as consolidações; o usuário apenas revisa e publica |
| **Ordenação inteligente** | Produção ordenada por prioridade de coleta |
| **Sinalização contextual** | Alertas visuais guiam o usuário |
| **Autopreenchimento** | Sistema aproveita dados cadastrados para reduzir digitação |

---

## 2. Fluxo de Consolidação de Pedidos

### 2.1 Visão Geral

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    FLUXO DE CONSOLIDAÇÃO                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. PEDIDOS CHEGAM (automático via webhook)                             │
│     • Bling envia pedido                                                │
│     • Sistema processa e classifica                                     │
│                                                                         │
│  2. CONSOLIDAÇÃO AUTOMÁTICA                                             │
│     • Sistema agrupa pedidos compatíveis                                │
│     • Cria RASCUNHO de demanda                                          │
│                                                                         │
│  3. USUÁRIO REVISÃO                                                     │
│     • Visualiza rascunhos                                               │
│     • Edita se necessário                                               │
│     • Publica demanda                                                   │
│                                                                         │
│  4. PRODUÇÃO                                                            │
│     • Fábrica produz demanda publicada                                  │
│     • Atualiza status                                                   │
│                                                                         │
│  5. COLETA/ENTREGA                                                      │
│     • Separação por horário de coleta                                   │
│     • Entrega ao cliente                                                │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Ciclo de Vida da Demanda

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    ESTADOS DA DEMANDA                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  RASCUNHO ─────────────────────────────────────┐                        │
│    │                                            │                        │
│    │ • Novo pedido chega                        │                        │
│    │ • Entra na demanda automaticamente         │                        │
│    │ • Janela de tempo aberta (ex: 4h)          │                        │
│    │                                            │                        │
│    │ [Usuário clica em EDITAR]                  │                        │
│    ▼                                            │                        │
│  EDITADO (✏️)                                   │                        │
│    │                                            │                        │
│    │ • Usuário altera quantidade/produto        │                        │
│    │ • Sistema marca editado_pelo_usuario       │                        │
│    │                                            │                        │
│    │ [Novo pedido compatível chega]             │                        │
│    ▼                                            │                        │
│  MODIFICADO (⚠️ +N) ←───────────────────────────┘                        │
│    │                                            │                        │
│    │ • Pedido chegou após edição                │                        │
│    │ • Sistema sinaliza requer_revisao          │                        │
│    │ • Usuário vê badge "+N"                    │                        │
│    │                                            │                        │
│    │ [Usuário clica em PUBLICAR]                │                        │
│    ▼                                            │                        │
│  AGUARDANDO                                     │                        │
│    │                                            │                        │
│    │ • Demanda fechada para novos pedidos       │                        │
│    │ • Pronto para produção                     │                        │
│    │                                            │                        │
│    ▼                                            │                        │
│  EM_PRODUCAO                                    │                        │
│    │                                            │                        │
│    ▼                                            │                        │
│  CONCLUIDO                                      │                        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Interface do Usuário

### 3.1 Dashboard de Demandas

**Layout:**
```
┌─────────────────────────────────────────────────────────────────────────┐
│  NISTIPRINT - Demandas de Produção                                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  [Filtros]                                                              │
│  Canal: [Todos ▼]  Modalidade: [Todos ▼]  Status: [Todos ▼]            │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│  RASCUNHOS (3)                                                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ ✏️ Shopee - EXPRESS - 02/04/2026                    [Ver] [Editar] │   │
│  │    3 pedidos • 5 unidades • Coleta: 14:00                       │   │
│  │    Capa iPhone 14 • Miolo: Agenda 2026                          │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ ⚠️ +2 Mercado Livre - STANDARD - 02/04/2026         [Ver] [Editar] │   │
│  │    5 pedidos • 8 unidades • Coleta: 18:00                       │   │
│  │    Capa Samsung S23 • Miolo: Planner                            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│  DEMANDAS ATIVAS (5)                                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 🚚 Shopee - EXPRESS - 02/04/2026                    [Produzir]    │   │
│  │    Coleta: 14:00 • 5 unidades                                   │   │
│  │    Status: AGUARDANDO                                           │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Indicadores Visuais

| Ícone | Significado |
|-------|-------------|
| ✏️ | Demanda editada pelo usuário |
| ⚠️ +N | N novos pedidos após edição |
| 🚚 | Demanda em produção |
| ✅ | Demanda concluída |
| 🕐 | Horário de corte próximo |
| 🔥 | Urgente/Flex |

### 3.3 Estados dos Cards de Rascunho

#### Estado: Limpo
```
┌─────────────────────────────────────────────────────────────────┐
│ Shopee - EXPRESS - 02/04/2026                       [Editar] [Publicar] │
│    3 pedidos • 5 unidades • Coleta: 14:00                       │
│    Capa iPhone 14 • Miolo: Agenda 2026                          │
└─────────────────────────────────────────────────────────────────┘
```

#### Estado: Editado
```
┌─────────────────────────────────────────────────────────────────┐
│ ✏️ Shopee - EXPRESS - 02/04/2026                    [Editar] [Publicar] │
│    3 pedidos • 5 unidades • Coleta: 14:00                       │
│    Capa iPhone 14 • Miolo: Agenda 2026                          │
│    Editado há 15 minutos                                        │
└─────────────────────────────────────────────────────────────────┘
```

#### Estado: Modificado
```
┌─────────────────────────────────────────────────────────────────┐
│ ⚠️ +2 Shopee - EXPRESS - 02/04/2026                 [Ver novos] [Publicar] │
│    5 pedidos • 8 unidades • Coleta: 14:00                       │
│    Capa iPhone 14 • Miolo: Agenda 2026                          │
│    2 pedidos chegaram após edição                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Operações do Usuário

### 4.1 Revisar e Publicar Rascunho

**Passo a passo:**

1. **Acessar Dashboard**
   - Navegar para "Demandas" → "Rascunhos"

2. **Visualizar Rascunho**
   - Clicar em [Ver] para ver detalhes
   - Verificar pedidos agrupados
   - Conferir quantidade total

3. **Editar (opcional)**
   - Clicar em [Editar]
   - Ajustar quantidade
   - Modificar produto/miolo se necessário
   - Salvar alterações

4. **Ver Novos Pedidos (se houver ⚠️ +N)**
   - Clicar em [Ver novos]
   - Revisar pedidos chegados após edição
   - Confirmar inclusão

5. **Publicar**
   - Clicar em [Publicar]
   - Confirmar publicação
   - Demanda vai para "Demandas Ativas"

### 4.2 Criar Demanda Manualmente

**Quando usar:**
- Reposição de estoque
- Produção para B2B
- Demanda não originada de pedido

**Passo a passo:**

1. **Clicar em [Nova Demanda]**

2. **Selecionar Origem**
   - [ ] Importar de Pedido
   - [x] Criar Manualmente

3. **Preencher Dados**
   ```
   Canal de Venda: [Shopee - CNPJ 01 ▼]
   Modalidade:     [EXPRESS ▼]
   Produto:        [Capa iPhone 14 ▼]
   Miolo:          [Agenda 2026 ▼]
   Quantidade:     [10]
   Data Entrega:   [02/04/2026]
   Observações:    [Reposição de estoque]
   ```

4. **Autopreenchimento (automático)**
   - Horário de coleta: 14:00 (do canal)
   - Ponto de coleta: Comércio Local (da regra)
   - Categoria temporal: HOJE (calculado)

5. **Confirmar**
   - Clicar em [Criar Demanda]

### 4.3 Acompanhar Produção

**Status de Produção por Item:**

| Status | Descrição | Ação |
|--------|-----------|------|
| `PENDENTE` | Aguardando início | [Iniciar Produção] |
| `EM_PRODUCAO` | Sendo produzido | [Registrar Avanço] |
| `CONCLUIDO` | Finalizado | — |

**Etapas de Produção:**

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    ETAPAS DE PRODUÇÃO                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. CAPAS IMPRESSAS                                                     │
│     [__________] 3/10                                                   │
│                                                                         │
│  2. CAPAS PRODUZIDAS                                                    │
│     [______] 2/10                                                       │
│                                                                         │
│  3. MIÓLOS PRONTOS                                                      │
│     [________] 4/10                                                     │
│                                                                         │
│  4. MONTAGEM                                                            │
│     [____] 1/10                                                         │
│                                                                         │
│  5. EXPEDIÇÃO                                                           │
│     [__] 0/10                                                           │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.4 Registrar Entrega Parcial

**Quando usar:**
- Demandas grandes com coleta fracionada
- Clientes que aceitam entregas parciais

**Passo a passo:**

1. **Acessar Demanda**
   - Clicar na demanda em "EM_PRODUCAO"

2. **Clicar em [Registrar Entrega]**

3. **Preencher Quantidade**
   ```
   Quantidade a entregar: [5]
   Data de entrega:       [02/04/2026]
   ```

4. **Confirmar**
   - Sistema atualiza `entregas_producao`
   - Status muda para `COLETA_PARCIAL` se aplicável

---

## 5. Sinalizações e Alertas

### 5.1 Tipos de Sinalização

| Tipo | Ícone | Severidade | Descrição |
|------|-------|------------|-----------|
| `FLEX` | 🔥 | INFO | Entrega no mesmo dia |
| `FULFILLMENT` | 📦 | INFO | Reposição externa |
| `HORARIO_CORTE_PROXIMO` | 🕐 | ATENCAO | Corte nas próximas 2h |
| `ESTOQUE_INSUFICIENTE` | ⚠️ | CRITICO | Produção incompleta |
| `PRODUCAO_ATRASADA` | 🚨 | CRITICO | Risco de atraso |
| `INTEGRACAO_ERRO` | ❌ | CRITICO | Erro de sincronização |

### 5.2 Como Responder a Alertas

#### Alerta: Horário de Corte Próximo (🕐)

**Significado:** Horário de coleta em ≤ 2 horas

**Ação:**
1. Priorizar produção desta demanda
2. Alocar recursos adicionais
3. Considerar entrega parcial se necessário

#### Alerta: Estoque Insuficiente (⚠️)

**Significado:** Componentes faltando para produção

**Ação:**
1. Verificar itens faltantes
2. Registrar entrada de estoque ou
3. Ajustar quantidade da demanda

#### Alerta: Produção Atrasada (🚨)

**Significado:** Risco de não cumprir prazo de entrega

**Ação:**
1. Revisar status de produção
2. Alocar recursos extras
3. Comunicar cliente sobre possível atraso

---

## 6. Preferências de Usuário

### 6.1 Configurar Vista Padrão

**Acessar:** Configurações → Preferências

**Opções:**

| Configuração | Opções |
|--------------|--------|
| Vista Padrão | KANBAN, LISTA, CALENDÁRIO |
| Ordenação Padrão | PRIORIDADE, HORÁRIO CORTE, DATA ENTREGA |
| Agrupamento Padrão | CANAL, MODALIDADE, SETOR, STATUS |

### 6.2 Autopreenchimento

**Habilitar/Desabilitar:**
```
[✓] Habilitar autopreenchimento inteligente

Quando habilitado, o sistema:
  • Preenche horário de coleta automaticamente
  • Sugere data de entrega baseada no canal
  • Calcula setores envolvidos (via BOM)
  • Valida conflitos de horário
```

### 6.3 Filtros Salvos

**Criar Filtro Personalizado:**

1. Aplicar filtros desejados
2. Clicar em [Salvar Filtro]
3. Nomear filtro (ex: "Meus Urgentes")
4. Acessar rapidamente depois

---

## 7. Pedidos Não Classificados

### 7.1 O que é?

Pedidos que o sistema não conseguiu classificar automaticamente porque o `servico_logistico` recebido não casa com nenhum padrão configurado.

### 7.2 Como Resolver

**Acessar:** Pedidos → Não Classificados

**Lista de Pedidos:**
```
┌─────────────────────────────────────────────────────────────────────────┐
│  Pedidos Aguardando Classificação                                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Pedido #1001 • Shopee • "Entrega Expressa Plus"                        │
│  [Classificar Manualmente]                                              │
│                                                                         │
│  Pedido #1002 • Mercado Livre • "Envio Prioritário"                     │
│  [Classificar Manualmente]                                              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Classificar Manualmente:**

1. Clicar em [Classificar Manualmente]
2. Selecionar modalidade:
   - [ ] STANDARD
   - [ ] EXPRESS
   - [ ] FULFILLMENT
   - [ ] RETIRADA
3. [Opcional] Criar padrão para futuro:
   ```
   Padrão: "%expressa%"
   Modalidade: EXPRESS
   ```
4. Confirmar

---

## 8. Tabelas de Referência

### 8.1 Modalidades Logísticas

| Modalidade | Descrição | Horário Típico |
|------------|-----------|----------------|
| `STANDARD` | Envio padrão | 18:00 - 21:00 |
| `EXPRESS` | Entrega expressa (Flex) | 14:00 - 17:00 |
| `FULFILLMENT` | Reposição externa | Agendado |
| `RETIRADA` | Retirada no local | Balcão |

### 8.2 Categorias Temporais

| Categoria | Descrição | Prazo |
|-----------|-----------|-------|
| `URGENTE` | Atrasado | < hoje |
| `HOJE` | Entrega hoje | = hoje |
| `AMANHA` | Entrega amanhã | = amanhã |
| `FUTURO` | Entrega futura | > amanhã |

### 8.3 Tipos de Demanda

| Tipo | Origem | Exemplo |
|------|--------|---------|
| `PLATAFORMA` | Pedido de marketplace | Venda Shopee |
| `B2B` | Venda corporativa | Pedido empresarial |
| `FULFILLMENT` | Reposição de fulfillment | Armazém externo |
| `ESTOQUE_INTERNO` | Produção para estoque | Reposição interna |

---

## 9. Atalhos de Teclado

| Atalho | Ação |
|--------|------|
| `N` | Nova demanda |
| `R` | Refresh da lista |
| `F` | Abrir filtros |
| `?` | Mostrar atalhos |

---

## 10. Perguntas Frequentes

### 10.1 Por que meu pedido não foi consolidado?

**Possíveis motivos:**
- Modalidade não mapeada (verificar "Não Classificados")
- Fora da janela de tempo configurada
- Produto/miolo diferente dos pedidos existentes
- Regra de consolidação específica do canal

### 10.2 Como alterar a janela de consolidação?

1. Acessar Configurações → Regras de Consolidação
2. Selecionar canal e modalidade
3. Editar "Janela de Agrupamento (horas)"
4. Salvar

### 10.3 Posso separar pedidos de uma demanda publicada?

**Não diretamente.** Após publicar:
- Criar nova demanda manual com os pedidos desejados
- Cancelar demanda original (se ainda não iniciada produção)

### 10.4 O que acontece se eu editar um rascunho e chegarem mais pedidos?

O sistema:
1. Adiciona os pedidos automaticamente
2. Marca a demanda com ⚠️ +N
3. Sinaliza `requer_revisao = true`
4. Você decide se publica ou revisa

---

## 11. Referências

### Documentos Relacionados
- [Modelo de Dados](./TECNICO-MODELO-DADOS.md)
- [Arquitetura Técnica](./TECNICO-ARQUITETURA.md)
- [Regras de Negócio](./NEGOCIO-REGRAS.md)

### Contato e Suporte
- **Documentação:** `/docs`
- **Issues:** GitHub Issues
- **Status:** Dashboard de monitoramento

---

*Documento consolidado em 2026-04-02*
