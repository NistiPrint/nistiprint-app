# Logging — Nistiprint

**Última atualização:** 2026-04-29

A aplicação usa o **journald** (systemd) para os processos no host (API, Worker, Beat, Caddy) e o **driver de logs do Docker** para os containers remanescentes (Redis, n8n, NPM).

---

## 1. Onde estão os logs

| Componente | Onde | Como ler |
|---|---|---|
| API (Flask + gunicorn) | journald | `journalctl -u nistiprint-api` |
| Worker (Celery) | journald | `journalctl -u nistiprint-worker` |
| Beat (Celery scheduler) | journald | `journalctl -u nistiprint-beat` |
| Caddy (frontend) | journald | `journalctl -u caddy` |
| Redis | docker | `docker logs nistiprint-redis` |
| n8n | docker | `docker logs nistiprint-n8n` |
| nginx-proxy-manager | docker | `docker logs nginx-proxy-manager` |

---

## 2. Comandos essenciais (`journalctl`)

### Ler logs de um serviço
```bash
# Últimas 100 linhas
journalctl -u nistiprint-worker -n 100 --no-pager

# Em tempo real (Ctrl+C para sair)
journalctl -u nistiprint-worker -f

# Desde determinado horário
journalctl -u nistiprint-api --since "2026-04-29 14:00"

# Última hora
journalctl -u nistiprint-worker --since "1 hour ago"

# Apenas a inicialização atual do serviço
journalctl -u nistiprint-api -b
```

### Filtros úteis
```bash
# Apenas erros (severity)
journalctl -u nistiprint-worker -p err

# Buscar texto
journalctl -u nistiprint-worker --since today | grep -i "shopee"

# Múltiplos services ao mesmo tempo
journalctl -u nistiprint-api -u nistiprint-worker -f

# Saída em JSON (útil para tooling)
journalctl -u nistiprint-api -o json | head
```

### Ver consumo de disco
```bash
journalctl --disk-usage
```

---

## 3. Logs do Worker (Celery)

O fluxo padrão de um job aparece no journal assim:

```
Task tasks.process_bling_webhook[abc-123] received
Task tasks.process_bling_webhook[abc-123] succeeded in 1.42s
```

### Acompanhar uma task específica
```bash
# Pegue o task_id (UUID) e filtre
journalctl -u nistiprint-worker --since today | grep <task_id>
```

### Ver apenas erros de tasks
```bash
journalctl -u nistiprint-worker -p err --since "1 day ago"
```

### Verificar se o worker está consumindo a fila
```bash
# 1) Worker ativo?
systemctl status nistiprint-worker

# 2) Fila acumulando?
docker exec nistiprint-redis redis-cli LLEN celery

# 3) Inspecionar workers ativos via Celery
sudo -u nistiprint /opt/nistiprint/.venv/bin/celery \
    -A worker_entrypoint -b redis://127.0.0.1:6379/0 inspect active
```

---

## 4. Retenção e rotação

`journald` aplica rotação automaticamente. Padrão Ubuntu: até **10% do disco** ou **4GB**, o que for menor. Para ajustar:

```bash
sudo nano /etc/systemd/journald.conf
```

Variáveis úteis:
```ini
SystemMaxUse=2G          # tamanho máximo total
MaxRetentionSec=30day    # quanto tempo manter
Compress=yes
```

```bash
sudo systemctl restart systemd-journald
```

### Limpar logs antigos manualmente
```bash
sudo journalctl --vacuum-time=7d     # mantém últimos 7 dias
sudo journalctl --vacuum-size=500M   # mantém até 500MB
```

---

## 5. Containers Docker (Redis, n8n, NPM)

```bash
# Em tempo real
docker logs -f nistiprint-redis
docker logs -f nistiprint-n8n
docker logs -f nginx-proxy-manager

# Últimas N linhas
docker logs --tail 100 nistiprint-n8n

# Desde determinado horário
docker logs --since 1h nginx-proxy-manager

# Buscar erro
docker logs nistiprint-n8n 2>&1 | grep -i error
```

---

## 6. Atalhos recomendados

Adicione ao `~/.bashrc` do seu user de operação:

```bash
alias logs-api='journalctl -u nistiprint-api -f'
alias logs-worker='journalctl -u nistiprint-worker -f'
alias logs-beat='journalctl -u nistiprint-beat -f'
alias logs-all='journalctl -u nistiprint-api -u nistiprint-worker -u nistiprint-beat -f'
```

---

## 7. Erros comuns

| Sintoma | Onde olhar |
|---|---|
| `503` do NPM | `docker logs --tail 30 nginx-proxy-manager` |
| API retorna 500 | `journalctl -u nistiprint-api -p err -n 50` |
| Worker travado / sem consumir fila | `journalctl -u nistiprint-worker -f` + `docker exec nistiprint-redis redis-cli LLEN celery` |
| Task disparada nunca executa | confira se Beat está vivo: `systemctl status nistiprint-beat` |
| Frontend abre em branco | `journalctl -u caddy -n 30` |

---

## 8. Centralização (futuro)

Para ambientes com múltiplos servidores ou maior auditoria, considere:
- **Grafana Loki** — barato, integra direto com journald via `promtail`
- **Better Stack / Logtail** — SaaS, sem infra adicional

Hoje (servidor único) o `journalctl` é suficiente.
