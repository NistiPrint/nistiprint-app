# Changelog Frontend - Pedidos Flex

## Data: 2026-03-28

### ✅ Implementado

#### 1. Filtro "Apenas Entrega Rápida" (Flex)

**Arquivo:** `apps/frontend/src/components/pedidos/FiltrosPedidos.jsx`

- Adicionado toggle switch para filtrar pedidos Flex
- Ícone `Zap` (raio) para identificação visual
- Filtro envia `is_flex=true` para API

```jsx
<Switch
  id="filtro-flex"
  checked={filtros.is_flex === true}
  onCheckedChange={(checked) => 
    onFiltroChange({ is_flex: checked ? true : null })
  }
/>
```

---

#### 2. Badge de Pedido Flex

**Arquivo:** `apps/frontend/src/components/pedidos/TabelaPedidos.jsx`

- Badge laranja com ícone de raio
- Exibido apenas para pedidos com `is_flex=true`
- Texto: "🚀 Flex"

```jsx
{pedido.is_flex && (
  <Badge variant="secondary" className="bg-orange-500 text-white text-xs px-1.5 py-0">
    <Zap className="h-3 w-3 mr-0.5" />
    Flex
  </Badge>
)}
```

---

#### 3. Coluna "Enviar Até"

**Arquivo:** `apps/frontend/src/components/pedidos/TabelaPedidos.jsx`

- Nova coluna entre "Pedido" e "Data"
- Formato: `DD/MM/YYYY HH:MM`
- Destaque visual para pedidos Flex (negrito + cor laranja)

```jsx
<TableHead>Enviar Até</TableHead>

<TableCell>
  <div className={pedido.is_flex ? 'font-semibold text-orange-700' : ''}>
    {formatarDataHora(pedido.data_limite_envio || pedido.enviar_ate_formatado)}
  </div>
</TableCell>
```

---

#### 4. Cores Dinâmicas de Status

**Arquivo:** `apps/frontend/src/components/pedidos/TabelaPedidos.jsx`

- Componente `StatusBadge` atualizado para receber `statusCor` e `statusNome`
- Prioriza cor da API (inline style)
- Fallback para mapeamento por ID

```jsx
function StatusBadge({ statusId, statusNome, statusCor }) {
  // Se tiver cor dinâmica da API, usa inline style
  if (statusCor) {
    return (
      <Badge style={{ backgroundColor: statusCor, color: '#fff' }}>
        {statusNome || `Status ${statusId}`}
      </Badge>
    );
  }
  
  // Fallback para mapeamento por ID
  const statusMap = { ... }
}
```

**IDs de Status Suportados:**

| ID | Nome | Cor Padrão |
|----|------|------------|
| 1 | Em Aberto | Amarelo |
| 2 | Em Andamento | Azul |
| 3 | Produzido | Roxo |
| 4 | Pronto p/ Envio | Ciano |
| 5 | Enviado | Verde |
| 6 | Entregue | Verde Escuro |
| 7 | Cancelado | Vermelho |

---

#### 5. Destaque Visual na Linha

**Arquivo:** `apps/frontend/src/components/pedidos/TabelaPedidos.jsx`

- Linhas de pedidos Flex têm fundo laranja suave
- Hover effect destacado

```jsx
<TableRow className={pedido.is_flex ? 'bg-orange-50/50 hover:bg-orange-50' : ''}>
```

---

#### 6. Mapeamento de Campos da API

**Arquivo:** `apps/frontend/src/pages/pedidos/PedidosListPage.jsx`

Novos campos mapeados:

```javascript
const pedidosMapeados = ordersData.map(order => ({
  // ... campos existentes
  is_flex: order.is_flex || false,
  data_limite_envio: order.data_limite_envio,
  enviar_ate_formatado: order.enviar_ate_formatado,
  status: order.status || {
    id: order.situacao_pedido_id,
    nome: order.situacao_nome,
    cor: order.situacao_cor,
  },
}));
```

---

### 📊 Visualização

#### Filtro Flex
```
┌─────────────────────────────────────────┐
│  ⚡ Apenas Entrega Rápida               │
│     Pedidos Flex (prioritários)        │
└─────────────────────────────────────────┘
```

#### Tabela com Pedidos Flex
```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Pedido  │ Enviar Até       │ Data      │ Cliente   │ Status  │ Total       │
├─────────┼──────────────────┼───────────┼───────────┼─────────┼─────────────┤
│ 🚀 Flex │ 29/03/2026 16:00 │ 28/03     │ João      │ Em And. │ R$ 150,00   │ ← Laranja
│ #12345  │ (destacado)      │           │           │ (azul)  │             │
├─────────┼──────────────────┼───────────┼───────────┼─────────┼─────────────┤
│ #12346  │ 30/03/2026 16:00 │ 28/03     │ Maria     │ Em And. │ R$ 200,00   │ ← Normal
└──────────────────────────────────────────────────────────────────────────────┘
```

---

### 🔧 Como Testar

1. **Acessar página de pedidos:**
   ```
   http://localhost:5173/pedidos
   ```

2. **Ativar filtro Flex:**
   - Ligar toggle "Apenas Entrega Rápida"
   - Verificar se apenas pedidos com badge 🚀 aparecem

3. **Verificar coluna "Enviar Até":**
   - Deve mostrar data/hora formatada
   - Pedidos Flex em negrito + laranja

4. **Verificar cores de status:**
   - Devem corresponder às cores da API
   - Fallback para cores padrão funciona

---

### 📝 Próximos Passos (Opcional)

- [ ] Adicionar atalho de teclado para filtro Flex (ex: `Ctrl+F`)
- [ ] Mostrar contador de pedidos Flex no header
- [ ] Adicionar filtro rápido "Flex Hoje" e "Flex Amanhã"
- [ ] Exportar lista Flex para CSV/Excel
- [ ] Notificação em tempo real para novos pedidos Flex

---

### 🐛 Problemas Conhecidos

Nenhum no momento.

---

### 📚 Referências

- Backend: `docs/MELHORIAS_PEDIDOS_FLEX.md`
- API: `GET /api/v2/order/list-advanced?is_flex=true`
- Componentes: `FiltrosPedidos.jsx`, `TabelaPedidos.jsx`
