# Guia de Deploy — Nistiprint

**Última atualização:** 2026-04-29

---

## 1. Arquitetura

A aplicação roda em um **servidor único**, com os processos da aplicação gerenciados por **systemd** e dois serviços auxiliares ainda em containers Docker (Redis e n8n). O **nginx-proxy-manager** (em container) faz o roteamento público com SSL.

```
                         ┌──────────────────────────────────┐
                         │      Internet (HTTPS)            │
                         └───────────────┬──────────────────┘
                                         ▼
                         ┌──────────────────────────────────┐
                         │   nginx-proxy-manager (Docker)   │
                         │   Portas 80 / 443 / 81 (admin)   │
                         └───────────────┬──────────────────┘
                                         │
                  ┌──────────────────────┼──────────────────────┐
                  ▼                      ▼                      ▼
        ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
        │  Caddy (host)    │   │  gunicorn (host) │   │  n8n (Docker)    │
        │  127.0.0.1:3000  │   │  0.0.0.0:8080    │   │  :5678           │
        │  Frontend SPA    │   │  API Flask       │   │  Webhooks        │
        └──────────────────┘   └──────────────────┘   └────────┬─────────┘
                                         │                     │
                                         ▼                     ▼
                                ┌──────────────────────────────────┐
                                │  Redis (Docker, :6379)           │
                                └────────────┬─────────────────────┘
                                             ▼
                              ┌──────────────────────────────┐
                              │  Celery Worker + Beat (host) │
                              │  systemd                     │
                              └──────────────────────────────┘
```

### Componentes

| Componente | Onde roda | Como é gerenciado |
|---|---|---|
| Frontend (React/Vite) | Servido por **Caddy** no host | `systemctl … caddy` |
| API (Flask + gunicorn) | Processo no host | `systemd: nistiprint-api` |
| Worker (Celery) | Processo no host | `systemd: nistiprint-worker` |
| Beat (Celery scheduler) | Processo no host | `systemd: nistiprint-beat` |
| Redis | Container Docker (stack `nistiprint-infra`) | Portainer |
| n8n | Container Docker (stack `nistiprint-infra`) | Portainer |
| nginx-proxy-manager | Container Docker | Portainer |

### Por que sem containers para a aplicação?

- Build/push de imagem eliminado → deploy de ~30s em vez de ~5min
- `packages/shared` é compartilhado entre API e Worker via uma única **venv** com `pip install -e packages/shared` — qualquer alteração é refletida nos dois com um único `git pull`
- Logs centralizados via `journalctl`
- Rollback é `git checkout <sha> && ./deploy.sh`

---

## 2. Deploy automático (GitHub Actions)

A cada push em `main`, um workflow do GitHub roda no servidor via SSH e executa o script de deploy.

### Fluxo
```
git push (main)
    ↓
GitHub Actions (.github/workflows/deploy.yml)
    ↓
SSH no servidor → /opt/nistiprint/deploy.sh
    ↓
git pull + pip install + npm build + systemctl restart
    ↓
Aplicação atualizada (~30-60s)
```

### Secrets necessários no GitHub
- `SSH_HOST` — IP/hostname do servidor
- `SSH_USER` — `nistiprint`
- `SSH_KEY` — chave privada do usuário `nistiprint`

---

## 3. Deploy manual

```bash
ssh nistiprint@<servidor> /opt/nistiprint/deploy.sh
```

Conteúdo do `deploy.sh` (em `/opt/nistiprint/deploy.sh`):

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /opt/nistiprint

echo "→ git fetch + reset"
git fetch --prune origin
git reset --hard origin/main

echo "→ pip install"
.venv/bin/pip install -q -r apps/api/requirements.txt
.venv/bin/pip install -q -r apps/worker/requirements.txt
.venv/bin/pip install -q -e packages/shared

echo "→ frontend build"
( cd apps/frontend && npm ci --silent && npm run build )

echo "→ restart services"
sudo /bin/systemctl restart nistiprint-api nistiprint-worker nistiprint-beat

echo "✓ deploy $(git rev-parse --short HEAD) ok"
```

> O `git reset --hard` é seguro porque o servidor é apenas runtime — qualquer alteração local é acidental.

---

## 4. Rollback

```bash
ssh nistiprint@<servidor>
cd /opt/nistiprint
git log --oneline -10                  # localizar o commit alvo
git checkout <sha>
./deploy.sh                            # reaplica build e reinicia
```

Para voltar ao topo da `main`:
```bash
git checkout main && ./deploy.sh
```

---

## 5. Verificação pós-deploy

```bash
# API direta no host
curl http://127.0.0.1:8080/health

# Frontend (Caddy) direto no host
curl -I http://127.0.0.1:3000/

# Status dos services
systemctl status nistiprint-api nistiprint-worker nistiprint-beat --no-pager

# Públicos (via NPM)
curl -I https://app.nistiprint.neolabs.com.br/
curl https://app.nistiprint.neolabs.com.br/api/health
```

---

## 6. Atualizando dependências

### Python (api / worker / shared)
1. Edite `requirements.txt` correspondente
2. Commit e push → o `deploy.sh` roda `pip install` automaticamente

### Frontend
1. `npm install <pacote>` localmente
2. **Commit `package.json` e `package-lock.json` juntos** (lock fora de sincronia quebra o `npm ci` no servidor)
3. Push → `deploy.sh` faz o build

---

## 7. Variáveis de ambiente

Mantidas em `/opt/nistiprint/.env` (chmod 600, owner `nistiprint`). Não estão no Git.

Os 3 services systemd carregam o mesmo arquivo via `EnvironmentFile=/opt/nistiprint/.env`.

Para alterar uma variável:
```bash
sudo -u nistiprint nano /opt/nistiprint/.env
sudo systemctl restart nistiprint-api nistiprint-worker nistiprint-beat
```

> Cuidado: o parser do systemd **não** aceita aspas em volta dos valores nem `#` no meio da linha. Valores multi-linha (ex: JSON do Firebase) precisam estar em uma única linha com `\n` literais.

Lista completa das variáveis: [variaveis-ambiente.md](./variaveis-ambiente.md).

---

## 8. Comandos úteis

| Tarefa | Comando |
|---|---|
| Deploy manual | `/opt/nistiprint/deploy.sh` |
| Status dos 3 services | `systemctl status nistiprint-{api,worker,beat}` |
| Reiniciar tudo | `sudo systemctl restart nistiprint-{api,worker,beat}` |
| Logs API (live) | `journalctl -u nistiprint-api -f` |
| Logs Worker (live) | `journalctl -u nistiprint-worker -f` |
| Recarregar Caddy | `sudo systemctl reload caddy` |
| Containers ativos | `docker ps` |

---

## 9. Referências

- [infraestrutura.md](./infraestrutura.md) — detalhamento dos services systemd, Caddy e NPM
- [logging.md](./logging.md) — como ler logs (journalctl)
- [variaveis-ambiente.md](./variaveis-ambiente.md) — variáveis usadas pela aplicação
