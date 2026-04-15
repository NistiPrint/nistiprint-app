# Guia de Migração - Monolito para Microsserviços

## Status da Migração

### ✅ Concluído

- [x] `nistiprint-shared` criado e estruturado
- [x] Models e Services movidos para o pacote compartilhado
- [x] Database service refatorado com lazy loading (SupabaseDBService.table)
- [x] Inicialização de ambiente centralizada (env_loader)
- [x] Interface de query mock isolada (initializer)
- [x] `nistiprint-api` (ex-core) atualizado para usar shared
- [x] `nistiprint-worker` configurado com shared
- [x] Dockerfiles e Compose unificados
- [x] Templates e prompts migrados para o pacote compartilhado

### ⏳ Pendente

- [ ] Remover código morto/legado da pasta `nistiprint-api/services` (que já está no shared)
- [ ] Validar fluxo de deploy completo via Portainer
- [ ] Testar comunicação via Redis entre API e Worker

---

## Boas Práticas V3 (Padrões Estabelecidos)

### 1. Inicialização de Pontos de Entrada
Sempre chame `load_nistiprint_env()` e `setup_mock_query_interface()` no início de qualquer script ou microsserviço que use o `nistiprint-shared`.

### 2. Acesso ao Supabase
Utilize sempre `supabase_db.table('tabela')` em vez de acessar o cliente diretamente. Isso garante que o cliente seja inicializado sob demanda, evitando erros de importação circular.

### 3. Imports Absolutos
Todos os microsserviços consomem o pacote `nistiprint_shared` de forma absoluta:
- `from nistiprint_shared.models.pedido import Pedido`
- `from nistiprint_shared.services.order_service import order_service`

---

## Troubleshooting Comum

### AttributeError: 'NoneType' object has no attribute 'table'
Causa: Tentativa de acessar `supabase_db.client.table()` antes do cliente ser inicializado.
Solução: Substituir por `supabase_db.table('tabela')`.

### ModuleNotFoundError: No module named 'models'
Causa: Referência a nomes de módulos antigos (V2).
Solução: Atualizar para `from nistiprint_shared.models import ...`.

---

**Última Atualização:** Fevereiro de 2026 (Refatoração estrutural completa concluída com sucesso).
