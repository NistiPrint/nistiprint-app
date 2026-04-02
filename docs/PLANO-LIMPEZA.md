# Plano de Limpeza de Documentação

**Data:** 2026-04-02  
**Status:** Aguardando aprovação

Este documento lista os arquivos de documentação que podem ser deletados ou movidos para arquivo morto após a consolidação.

---

## ✅ Documentos Consolidados (MANTER)

Estes são os **4 documentos principais** que substituem toda a documentação legada:

| Documento | Finalidade |
|-----------|------------|
| `TECNICO-MODELO-DADOS.md` | Modelo de dados ER completo |
| `TECNICO-ARQUITETURA.md` | Arquitetura técnica e fluxos |
| `NEGOCIO-REGRAS.md` | Regras de negócio e dependências |
| `MANUAL-USUARIO.md` | Manual do usuário e UX |

---

## 🗑️ Arquivos para DELETAR (Obsoletos)

### Diário de Implementação
- [ ] `02-features/implementacao_semana1.md`
- [ ] `02-features/implementacao_semana2.md`
- [ ] `02-features/implementacao_completa.md`
- [ ] `02-features/implementacao_gestao_pedidos.md`

### Debug e Correções Pontuais
- [ ] `02-features/debug_frontend.md`
- [ ] `02-features/correcao_lista_pedidos.md`
- [ ] `02-features/correcoes_gestao_pedidos.md`
- [ ] `02-features/correcoes_tela_pedidos.md`
- [ ] `CORRECAO_VALIDACAO_SHOPEE_SYNC.md`
- [ ] `CORRECAO_VINCULOS_ORFAOS.md`
- [ ] `CORRECOES_BUSCA_PEDIDO_SHOPEE.md`
- [ ] `CORRECOES_TELA_PEDIDOS.md`

### Soluções Já Implementadas
- [ ] `SOLUCAO_IS_FLEX.md`
- [ ] `SOLUCAO_IS_FLEX_REVISADA.md`
- [ ] `MELHORIAS_PEDIDOS_FLEX.md`
- [ ] `GUIDE_FRONTEND_PEDIDOS_FLEX.md`
- [ ] `DIAGNOSTICO_INTEGRACAO_SHOPEE.md`
- [ ] `FILTROS_CONTEXTUAIS_PEDIDOS.md`
- [ ] `SCRIPT_SYNC_PEDIDOS_STATUS.md`

### Planos e Propostas Concluídas
- [ ] `02-features/proposta_ux_pedidos.md`
- [ ] `02-features/solucao_rpc_nova.md`
- [ ] `02-features/instrucoes_rpc_pedidos.md`
- [ ] `plano-refatoracao-nistiprint.md`
- [ ] `REFACTORING-SUMMARY.md`

### Webhooks (conteúdo consolidado)
- [ ] `02-features/webhook_bling.md`
- [ ] `02-features/webhook_shopee.md`
- [ ] `02-features/webhooks_fluxo_correto.md`

### Análise de Fluxo (consolidado)
- [ ] `02-features/analise_fluxo_pedido_demanda.md`
- [ ] `02-features/plano_producao_multinivel_estoque.md`

---

## 📦 Arquivos para MOVER para `archive/`

### Arquitetura Legada
- [ ] `01-architecture/` (pasta completa)
- [ ] `02-architecture/` (pasta completa)

### Planning Antigo
- [ ] `05-planning/` (pasta completa)
- [ ] `05-planning/active_implementation_plan.md`
- [ ] `05-planning/maturity_assessment_2026.md`
- [ ] `05-planning/processar_fila_eventos_bling.md`

### Issues Resolvidas
- [ ] `99-issues/` (pasta completa)

### Contexto Histórico (opcional)
- [ ] `CONTEXTO_PRODUCAO_UX.md` → `archive/` (conteúdo consolidado em MANUAL-USUARIO)
- [ ] `LEVANTAMENTO-ER-DEMANDAS.md` → `archive/` (conteúdo consolidado em TECNICO-MODELO-DADOS)
- [ ] `ARQUITETURA-SISTEMA.md` → `archive/` (conteúdo consolidado em TECNICO-ARQUITETURA)
- [ ] `02-features/business_rules_overview.md` → `archive/` (conteúdo consolidado em NEGOCIO-REGRAS)

---

## ✅ Arquivos para MANTER (Referência)

### Documentação Ativa
- [ ] `README.md` (atualizado)
- [ ] `CONTEXTUALIZACAO-CONSOLIDACAO-DEMANDAS.md` (contexto histórico)
- [ ] `03-guides/` (pasta completa - guias ativos)
- [ ] `04-operations/` (pasta completa - operações ativas)

### Integrações
- [ ] `02-features/integration_store.md`
- [ ] `02-features/integrations/` (pasta completa)
- [ ] `02-features/api_bling.md`
- [ ] `02-features/api_shopee.md`

### Módulo de Estoque
- [ ] `02-features/controle-estoque/` (pasta completa)

### Outros
- [ ] `02-features/order_enrichment.md` (IA/enriquecimento)

---

## 📊 Resumo

| Ação | Quantidade |
|------|------------|
| **Deletar** | ~25 arquivos |
| **Mover para archive/** | ~4 pastas + ~8 arquivos |
| **Manter** | ~4 documentos principais + ~10 arquivos/pastas de referência |

---

## 🔧 Comandos Sugeridos

### Deletar arquivos obsoletos
```bash
cd docs

# Diário de implementação
rm 02-features/implementacao_semana*.md
rm 02-features/implementacao_completa.md
rm 02-features/implementacao_gestao_pedidos.md

# Debug e correções
rm 02-features/debug_frontend.md
rm 02-features/correcao_*.md
rm CORRECAO_*.md
rm CORRECOES_*.md

# Soluções implementadas
rm SOLUCAO_IS_FLEX*.md
rm MELHORIAS_PEDIDOS_FLEX.md
rm GUIDE_FRONTEND_PEDIDOS_FLEX.md
rm DIAGNOSTICO_INTEGRACAO_SHOPEE.md
rm FILTROS_CONTEXTUAIS_PEDIDOS.md
rm SCRIPT_SYNC_PEDIDOS_STATUS.md

# Planos concluídos
rm 02-features/proposta_ux_pedidos.md
rm 02-features/solucao_rpc_nova.md
rm 02-features/instrucoes_rpc_pedidos.md
rm plano-refatoracao-nistiprint.md
rm REFACTORING-SUMMARY.md

# Webhooks
rm 02-features/webhook_*.md
rm 02-features/webhooks_fluxo_correto.md

# Análise
rm 02-features/analise_fluxo_pedido_demanda.md
rm 02-features/plano_producao_multinivel_estoque.md
```

### Mover para archive/
```bash
cd docs

# Criar pasta archive se não existir
mkdir -p archive

# Mover pastas completas
mv 01-architecture/ archive/
mv 02-architecture/ archive/
mv 05-planning/ archive/
mv 99-issues/ archive/

# Mover arquivos individuais (opcional)
mv CONTEXTO_PRODUCAO_UX.md archive/
mv LEVANTAMENTO-ER-DEMANDAS.md archive/
mv ARQUITETURA-SISTEMA.md archive/
mv 02-features/business_rules_overview.md archive/
```

---

## ⚠️ Precauções

1. **Faça backup** antes de deletar qualquer arquivo
2. **Verifique links** em outros documentos antes de deletar
3. **Considere manter** no `archive/` em vez de deletar permanentemente
4. **Comunique a equipe** antes de fazer limpeza em larga escala

---

*Plano gerado em 2026-04-02*
