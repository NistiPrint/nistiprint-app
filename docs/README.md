# 📚 Nistiprint - Documentação do Projeto

**Última atualização:** 2026-04-02

Bem-vindo à central de conhecimento da plataforma **Nistiprint**. A documentação foi consolidada em 4 documentos principais para facilitar a navegação e manutenção.

---

## 📖 Documentação Consolidada (Principal)

### Técnicos

| Documento | Descrição | Link |
|-----------|-----------|------|
| 📊 **Modelo de Dados** | ER completo, tabelas, colunas, índices, funções SQL | [TECNICO-MODELO-DADOS.md](./TECNICO-MODELO-DADOS.md) |
| 🏗️ **Arquitetura Técnica** | Componentes, serviços, fluxos, endpoints, workers | [TECNICO-ARQUITETURA.md](./TECNICO-ARQUITETURA.md) |

### Negócio

| Documento | Descrição | Link |
|-----------|-----------|------|
| 📋 **Regras de Negócio** | Regras, validações, cálculos, dependências entre entidades | [NEGOCIO-REGRAS.md](./NEGOCIO-REGRAS.md) |
| 📖 **Manual do Usuário** | Fluxos, interface, operações, atalhos, FAQ | [MANUAL-USUARIO.md](./MANUAL-USUARIO.md) |

---

## 🗂️ Estrutura Completa

```
docs/
│
├── 📄 README.md                         # Este arquivo (índice)
│
├── ⭐ TECNICO-MODELO-DADOS.md           # Modelo de dados consolidado
├── ⭐ TECNICO-ARQUITETURA.md            # Arquitetura técnica consolidada
├── ⭐ NEGOCIO-REGRAS.md                 # Regras de negócio consolidadas
├── ⭐ MANUAL-USUARIO.md                 # Manual do usuário consolidado
│
├── 📌 CONTEXTUALIZACAO-CONSOLIDACAO-DEMANDAS.md  # Contexto histórico
│
├── 📁 01-architecture/                  # Arquitetura (legado)
├── 📁 02-architecture/                  # Arquitetura (legado)
├── 📁 02-features/                      # Features (legado)
├── 📁 03-guides/                        # Guias (✅ manter)
├── 📁 04-operations/                    # Operações (✅ manter)
├── 📁 05-planning/                      # Planning (legado)
├── 📁 99-issues/                        # Issues (legado)
└── 📁 archive/                          # Arquivo morto
```

---

## 🎯 Como Usar Esta Documentação

### Para Desenvolvedores Novos

1. **[Arquitetura Técnica](./TECNICO-ARQUITETURA.md)** - Visão geral do sistema
2. **[Modelo de Dados](./TECNICO-MODELO-DADOS.md)** - Schema do banco
3. **[Regras de Negócio](./NEGOCIO-REGRAS.md)** - Lógica de negócio
4. **[03-guides/setup_local.md](./03-guides/setup_local.md)** - Setup do ambiente

### Para Desenvolvedores Plenos/Senior

1. **[Arquitetura Técnica](./TECNICO-ARQUITETURA.md)** - Seção de serviços e fluxos
2. **[Modelo de Dados](./TECNICO-MODELO-DADOS.md)** - Tabelas específicas
3. **[Regras de Negócio](./NEGOCIO-REGRAS.md)** - Regras da feature em questão

### Para Usuários de Negócio

1. **[Manual do Usuário](./MANUAL-USUARIO.md)** - Fluxos e interface
2. **[Regras de Negócio](./NEGOCIO-REGRAS.md)** - Políticas e validações

### Para Suporte

1. **[Manual do Usuário](./MANUAL-USUARIO.md)** - Seção de Perguntas Frequentes
2. **[Regras de Negócio](./NEGOCIO-REGRAS.md)** - Validações e restrições

---

## 📌 Status da Documentação

| Documento | Status | Data | Prioridade |
|-----------|--------|------|------------|
| Modelo de Dados | ✅ Consolidado | 2026-04-02 | ⭐ Principal |
| Arquitetura Técnica | ✅ Consolidado | 2026-04-02 | ⭐ Principal |
| Regras de Negócio | ✅ Consolidado | 2026-04-02 | ⭐ Principal |
| Manual do Usuário | ✅ Consolidado | 2026-04-02 | ⭐ Principal |
| Contextualização | 📌 Referência | 2026-04-02 | Secundário |
| Guias (03-guides) | ✅ Ativo | - | ⭐ Manter |
| Operações (04-operations) | ✅ Ativo | - | ⭐ Manter |
| Demais pastas | 📦 Legado | - | Arquivo |

---

## 🗑️ Plano de Limpeza

### Arquivos para Deletar (Obsoletos)

Estes arquivos documentam implementações pontuais já concluídas:

| Arquivo | Motivo |
|---------|--------|
| `02-features/implementacao_semana1.md` | Diário de implementação |
| `02-features/implementacao_semana2.md` | Diário de implementação |
| `02-features/debug_frontend.md` | Debug pontual |
| `02-features/correcao_*.md` | Correções já aplicadas |
| `SOLUCAO_IS_FLEX.md` | Solução já implementada |
| `SOLUCAO_IS_FLEX_REVISADA.md` | Solução já implementada |
| `MELHORIAS_PEDIDOS_FLEX.md` | Melhorias já aplicadas |
| `GUIDE_FRONTEND_PEDIDOS_FLEX.md` | Guia específico |
| `DIAGNOSTICO_INTEGRACAO_SHOPEE.md` | Diagnóstico concluído |
| `CORRECAO_*.md` | Correções aplicadas |
| `FILTROS_CONTEXTUAIS_PEDIDOS.md` | Feature implementada |
| `SCRIPT_SYNC_PEDIDOS_STATUS.md` | Script pontual |

### Arquivos para Mover para `archive/`

| Pasta/Arquivo | Motivo |
|---------------|--------|
| `01-architecture/` | Arquitetura legada |
| `02-architecture/` | Arquitetura legada |
| `05-planning/` | Planning antigo |
| `99-issues/` | Issues resolvidas |
| `plano-refatoracao-nistiprint.md` | Plano concluído |
| `REFACTORING-SUMMARY.md` | Refatoração concluída |

### Arquivos para Manter (Referência)

| Arquivo/Pasta | Motivo |
|---------------|--------|
| `CONTEXTUALIZACAO-CONSOLIDACAO-DEMANDAS.md` | Contexto histórico da consolidação |
| `CONTEXTO_PRODUCAO_UX.md` | Contexto de UX (parcialmente consolidado) |
| `LEVANTAMENTO-ER-DEMANDAS.md` | ER detalhado (consolidado em TECNICO-MODELO-DADOS) |
| `ARQUITETURA-SISTEMA.md` | Arquitetura (consolidado em TECNICO-ARQUITETURA) |
| `02-features/business_rules_overview.md` | Regras (consolidado em NEGOCIO-REGRAS) |
| `03-guides/` | Guias ativos |
| `04-operations/` | Operações ativas |
| `02-features/integrations/` | Documentação de integrações |
| `02-features/controle-estoque/` | Módulo de estoque |

---

## 🛠️ Como Contribuir com a Documentação

1. **Sempre documente** novas funcionalidades antes ou durante a implementação
2. **Atualize os documentos consolidados** quando houver mudanças significativas
3. **Mantenha o histórico** movendo arquivos obsoletos para `archive/` em vez de deletar
4. **Use o padrão** de assessment para avaliar maturidade de novos módulos

---

## 📞 Contato e Suporte

- **GitHub Issues:** Para dúvidas e sugestões
- **Documentação Técnica:** `docs/TECNICO-*.md`
- **Documentação de Negócio:** `docs/NEGOCIO-*.md`, `docs/MANUAL-USUARIO.md`

---

*Documentação consolidada em 2026-04-02*
