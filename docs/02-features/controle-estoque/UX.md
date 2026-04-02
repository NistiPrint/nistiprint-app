# UX - Monitoramento de Estoque

**URL:** `/relatorios/monitoramento-estoque`

---

## Dashboard

4 cards com stats em tempo real:
- 🟡 Eventos Pendentes
- 🟢 Eventos Processados
- 🔵 Fila (Legado)
- 🟣 Última Atualização

---

## Abas

### 1. Eventos de Produção

**Colunas:**
| Status | Tipo | Item | Estágio | Qtd | Data |
|--------|------|------|---------|-----|------|

**Filtros:**
- Tipo: SINAL | LIQUIDACAO
- Busca: item ou demanda

**Badges:**
- 🟡 Pendente
- 🟢 Processado
- 🟣 SINAL
- 🟣 LIQUIDACAO

---

### 2. Fila (Legado)

**Colunas:**
| Status | Item/SKU | Operação | Qtd | Tentativas | Data |

**Ação:** Botão "Processar Fila"

---

## Auto-Refresh

- **Intervalo:** 15 segundos
- **Atualiza:** Stats + lista de eventos

---

## Rotas

| URL | Destino |
|-----|---------|
| `/relatorios/fila-estoque` | MonitoramentoEstoquePage |
| `/relatorios/monitoramento-estoque` | MonitoramentoEstoquePage |
| `/relatorios/monitoramento` | → Redirect |

---

## Arquivo

`apps/frontend/src/pages/admin/relatorios/MonitoramentoEstoquePage.jsx`
