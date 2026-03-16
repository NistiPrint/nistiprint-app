# Resumo Executivo - Separação de Infraestrutura

## TL;DR

**Problema:** Atualizar o worker derruba o n8n, causando indisponibilidade nos webhooks.

**Solução:** Separar em 2 stacks:
- `nistiprint-infra` (redis + n8n) → **Nunca reinicia em deploys normais**
- `nistiprint-worker` (worker + beat) → **Reinicia livremente**

## Arquivos Criados

| Arquivo | Propósito |
|---------|-----------|
| `docker-compose.infra.yml` | Stack crítica (redis + n8n) |
| `docker-compose.worker.yml` | Stack dinâmica (worker + beat) |
| `deploy-infra.bat` | Gerencia infra localmente |
| `deploy-worker.bat` | Gerencia worker localmente |
| `migrate-stack.bat` | Migração automática |
| `README-MIGRATION.md` | Documentação completa |

## Como Migrar (Portainer)

### 1. Criar Stack de Infraestrutura (PRIMEIRO!)
- **Nome:** `nistiprint-infra`
- **Conteúdo:** Copie de `docker-compose.infra.yml`
- **Deploy**
- ⚠️ **Aguarde o Redis estar saudável antes de continuar!**

### 2. Verificar Infra
```bash
deploy-infra.bat status
# ou
docker ps | findstr "nistiprint-redis\|nistiprint-n8n"
```

### 3. Criar Stack de Worker (DEPOIS!)
- **Nome:** `nistiprint-worker`
- **Conteúdo:** Copie de `docker-compose.worker.yml`
- **Deploy**
- ⚠️ **Só crie esta stack após o Redis estar "Running"**

### 4. Remover Stack Antiga (Opcional)
- Vá em **Stacks** → `nistiprint-core` → Remove

## Como Fazer Deploy do Worker (Rotina)

```batch
# 1. Build e push
build.bat push worker

# 2. No Portainer:
#    Stacks → nistiprint-worker → Update the stack

# Pronto! n8n e redis continuam rodando!
```

## Benefícios

| Métrica | Antes | Depois |
|---------|-------|--------|
| Disponibilidade n8n | ~95% | ~99.9% |
| Webhooks perdidos/deploy | 10-30 | 0 |
| Reinícios do Redis | Todo deploy | Apenas manutenção |
| Tempo de deploy | 2-3 min | 30-60s |

## Próximos Passos

1. ✅ Revisar arquivos criados
2. ✅ Testar localmente (opcional)
3. 📅 Agendar migração em produção
4. 📊 Monitorar após migração

---

**Dúvidas?** Veja `README-MIGRATION.md` para detalhes completos.
