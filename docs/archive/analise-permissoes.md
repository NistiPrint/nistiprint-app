# Análise do Sistema de Permissões

## Status Atual

### Arquivos Principais
- `apps/api/routes/auth.py` - Decorators de autenticação
- `packages/shared/nistiprint_shared/services/permissao_service.py` - Serviço de permissões
- `packages/shared/nistiprint_shared/services/usuario_service.py` - Serviço de usuários

### Estrutura de Autenticação

#### Decorators em `auth.py`
1. **`login_required`**: Verifica se `user_id` está na sessão
2. **`admin_required`**: Verifica se `user_id` e `user_is_admin` estão na sessão
3. **`check_permission(recurso, acao)`**: Verifica permissão específica, admin tem acesso total

#### Serviço de Permissões em `permissao_service.py`
- **`has_permission(usuario_id, recurso_nome, acao)`**: Verifica permissão
- **`get_setor_permissions(setor_id)`**: Obtém permissões de um setor
- **`update_setor_permission(...)`**: Atualiza permissões de setor

### Regras de Admin
Usuários com `is_admin=True` ou setor nome 'Administrativo' têm acesso total.

## Problemas Identificados

### 1. Inconsistência na Verificação de Admin
- **Problema**: A verificação de admin é feita em múltiplos lugares com lógica diferente
- **Locais**:
  - `auth.py` - Verifica `session.get('user_is_admin', False)`
  - `permissao_service.py` - Verifica `is_admin=True` OU `setor.nome == 'Administrativo'`
- **Impacto**: Pode haver casos onde um usuário é considerado admin em um lugar mas não em outro

### 2. Decorator `admin_required` Não é Utilizado
- **Problema**: O decorator `admin_required` existe em `auth.py` mas não é usado em nenhum endpoint
- **Impacto**: Cada endpoint implementa sua própria verificação de admin manualmente

### 3. Endpoints de Tasks Não Verificam Permissões de Admin
- **Problema**: `task_schedules_api.py` tem função `_check_admin_permission()` customizada em vez de usar decorator padrão
- **Impacto**: Inconsistência na verificação de permissões

### 4. Código Duplicado para Dois Modos de Banco
- **Problema**: Cada função em `permissao_service.py` tem implementação separada para SQLAlchemy e Supabase
- **Impacto**: Dificuldade de manutenção, maior chance de bugs

### 5. Falta de Validação de Sessão em Alguns Endpoints
- **Problema**: Alguns endpoints usam `login_required` mas não verificam se o usuário está ativo
- **Impacto**: Usuários desativados podem ter acesso

### 6. Não Há Verificação de Permissões em `tasks_api.py`
- **Problema**: Todos os endpoints em `tasks_api.py` usam apenas `@login_required`
- **Impacto**: Qualquer usuário autenticado pode acessar logs de tarefas, cancelar tarefas, etc.

## Correções Recomendadas

### 1. Centralizar Verificação de Admin
Criar função única em `auth.py`:

```python
def is_admin():
    """Verifica se o usuário atual é admin."""
    return session.get('user_is_admin', False)
```

### 2. Usar Decorator `admin_required` em Endpoints de Admin
Aplicar `@admin_required` em:
- `task_schedules_api.py` - Todos os endpoints
- `tasks_api.py` - Endpoints de reprocessamento e cancelamento

### 3. Adicionar Verificação de Admin em `tasks_api.py`
Endpoints sensíveis devem usar `@admin_required`:
- `/execution-logs/<task_log_id>/retry`
- `/execution-logs/<task_log_id>/cancel`
- `/stock/reprocess-events`
- `/stock/reprocess-fila`

### 4. Simplificar Código de Permissões
Criar funções auxiliares para eliminar duplicação entre SQLAlchemy e Supabase.

### 5. Adicionar Verificação de Usuário Ativo
No `login_required`, verificar se o usuário está ativo:

```python
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Autenticação requerida'}), 401
        
        # Verificar se usuário está ativo
        user = usuario_service.get_by_id(session['user_id'])
        if not user or not user.get('ativo'):
            session.clear()
            return jsonify({'error': 'Usuário desativado'}), 401
        
        return f(*args, **kwargs)
    return decorated_function
```

## Ações Imediatas

1. ✅ Corrigir imports de `login_required` em `tasks_api.py` e `task_schedules_api.py`
2. ✅ Remover configuração desnecessária do Flask-Login
3. ⏳ Aplicar `@admin_required` em endpoints de `task_schedules_api.py`
4. ⏳ Adicionar `@admin_required` em endpoints sensíveis de `tasks_api.py`
5. ⏳ Centralizar verificação de admin em função única
6. ⏳ Adicionar verificação de usuário ativo em `login_required`
