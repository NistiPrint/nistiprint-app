# Manual de Infraestrutura — Nistiprint

**Última atualização:** 2026-04-29

Hospedagem em **servidor único (VPS)** rodando Ubuntu. A aplicação (API, Worker, Beat, Frontend) roda nativamente no host via **systemd** + **Caddy**. Apenas Redis, n8n e nginx-proxy-manager seguem em containers Docker.

---

## 1. Visão Geral

```
Servidor (VPS)
│
├── /opt/nistiprint/                      ← repo Git
│   ├── apps/api/         (Flask)
│   ├── apps/worker/      (Celery)
│   ├── apps/frontend/dist/   (build estático servido pelo Caddy)
│   ├── packages/shared/  (lib comum, instalada editável na venv)
│   ├── .venv/            (uma venv só para api + worker)
│   ├── .env              (variáveis, chmod 600, fora do Git)
│   └── deploy.sh
│
├── systemd
│   ├── nistiprint-api.service       (gunicorn :8080)
│   ├── nistiprint-worker.service    (celery worker)
│   ├── nistiprint-beat.service      (celery beat)
│   └── caddy.service                (frontend estático :3000)
│
└── Docker
    ├── nginx-proxy-manager           (proxy + SSL, :80/:443/:81)
    ├── nistiprint-redis              (broker Celery + cache, :6379)
    └── nistiprint-n8n                (webhooks, :5678)
```

---

## 2. Services systemd

Arquivos em `/etc/systemd/system/`. Todos rodam como user `nistiprint`.

### `nistiprint-api.service`
```ini
[Unit]
Description=Nistiprint API
After=network.target

[Service]
Type=simple
User=nistiprint
Group=nistiprint
WorkingDirectory=/opt/nistiprint/apps/api
EnvironmentFile=/opt/nistiprint/.env
ExecStart=/opt/nistiprint/.venv/bin/gunicorn -w 4 -b 0.0.0.0:8080 "main:create_app()"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### `nistiprint-worker.service`
```ini
[Unit]
Description=Nistiprint Celery Worker
After=network.target

[Service]
Type=simple
User=nistiprint
Group=nistiprint
WorkingDirectory=/opt/nistiprint/apps/worker
EnvironmentFile=/opt/nistiprint/.env
ExecStart=/opt/nistiprint/.venv/bin/celery -A worker_entrypoint worker --loglevel=info --concurrency=2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### `nistiprint-beat.service`
```ini
[Unit]
Description=Nistiprint Celery Beat
After=network.target

[Service]
Type=simple
User=nistiprint
Group=nistiprint
WorkingDirectory=/opt/nistiprint/apps/worker
EnvironmentFile=/opt/nistiprint/.env
ExecStart=/opt/nistiprint/.venv/bin/celery -A worker_entrypoint beat --loglevel=info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Após qualquer edição:
```bash
sudo systemctl daemon-reload
sudo systemctl restart nistiprint-api nistiprint-worker nistiprint-beat
```

---

## 3. Caddy (frontend)

Binário único, instalado via apt. Configuração em `/etc/caddy/Caddyfile`:

```
:3000 {
    root * /opt/nistiprint/apps/frontend/dist
    try_files {path} /index.html
    file_server
    encode gzip
}
```

`try_files {path} /index.html` faz o **SPA fallback** (rotas client-side do React).

```bash
sudo systemctl reload caddy        # após editar Caddyfile
sudo systemctl status caddy
```

---

## 4. nginx-proxy-manager (NPM)

Container que termina SSL e roteia o tráfego público para os services internos.

| Domínio | Forward target |
|---|---|
| `app.nistiprint.neolabs.com.br` | `172.18.0.1:3000` (Caddy/Frontend) — com Custom Location `/api` → `172.18.0.1:8080` (API) |
| `automacao.nistiprint.neolabs.com.br` | container `nistiprint-n8n:5678` |
| `gestao.nistiprint.neolabs.com.br` | container `portainer:9000` |

> `172.18.0.1` é o gateway da rede docker `gateway_net` — é como o NPM, dentro do container, alcança serviços que escutam no host.

UI do NPM: `http://<servidor>:81`.

---

## 5. Stacks Docker remanescentes

### `nistiprint-infra` (Portainer)
- **redis** — broker Celery, expõe `6379` para o host
- **n8n** — webhooks externos (Bling, Shopee), expõe `5678`

Atualizações dessas imagens são raras. Quando necessário: Portainer → Stacks → `nistiprint-infra` → Update.

> As stacks antigas `nistiprint-app` e `nistiprint-worker` foram **removidas** — agora rodam via systemd.

---

## 6. Domínios e Endpoints públicos

| Serviço | URL |
|---|---|
| Frontend + API | `https://app.nistiprint.neolabs.com.br` (UI) e `…/api/...` (API) |
| n8n (webhooks) | `https://automacao.nistiprint.neolabs.com.br` |
| Portainer | `https://gestao.nistiprint.neolabs.com.br` |

---

## 7. Fluxo de Dados

### Webhook Bling/Shopee
```
1. Plataforma externa
   ↓
2. Webhook → n8n (automacao.nistiprint.neolabs.com.br)
   ↓
3. n8n enfileira no Redis (fila 'celery')
   ↓
4. Worker Celery (systemd) consome e processa
   ↓
5. Persiste em Supabase
```

### Requisição da UI
```
1. Navegador → app.nistiprint.neolabs.com.br/...
   ↓
2. nginx-proxy-manager (SSL termination)
   ↓
3a. /            → Caddy (host:3000)  → arquivos estáticos do React
3b. /api/*       → gunicorn (host:8080) → Flask
   ↓
4. (API) → Supabase / Redis
```

---

## 8. Operações Comuns

### Verificação rápida de saúde
```bash
# API
curl http://127.0.0.1:8080/health

# Frontend
curl -I http://127.0.0.1:3000/

# Redis
docker exec nistiprint-redis redis-cli ping     # PONG

# Worker (via Celery)
sudo -u nistiprint /opt/nistiprint/.venv/bin/celery \
    -A worker_entrypoint -b redis://127.0.0.1:6379/0 inspect ping

# Status systemd
systemctl status nistiprint-api nistiprint-worker nistiprint-beat caddy --no-pager
```

### Reinício de serviços
```bash
# Aplicação
sudo systemctl restart nistiprint-api
sudo systemctl restart nistiprint-worker
sudo systemctl restart nistiprint-beat

# Frontend (Caddy)
sudo systemctl reload caddy

# Containers
docker restart nistiprint-redis nistiprint-n8n nginx-proxy-manager
```

---

## 9. Troubleshooting

| Problema | Verificação |
|---|---|
| API responde 502 / connection refused | `systemctl status nistiprint-api` e `journalctl -u nistiprint-api -n 50` |
| Worker não processa filas | `journalctl -u nistiprint-worker -f`; checar Redis: `docker exec nistiprint-redis redis-cli ping` |
| Webhooks não chegam | Logs n8n: `docker logs --tail 100 nistiprint-n8n` |
| Frontend abre em branco | `journalctl -u caddy -n 30`; conferir `apps/frontend/dist/index.html` |
| SSL expirado | NPM (`:81`) → Certificates → Renew |
| NPM 502 ao acessar domínio | `docker logs --tail 30 nginx-proxy-manager` — verificar se algum upstream aponta para host inexistente |

---

## 10. Backup

| Item | Onde |
|---|---|
| Banco de dados | Supabase (gerenciado externamente) |
| Workflows n8n | volume Docker `nistiprint-infra_n8n_data` |
| Código + composes | Repositório Git (GitHub) |
| `.env` | **Não está no Git** — manter cópia segura offline |

```bash
# Localizar volume do n8n
docker volume inspect nistiprint-infra_n8n_data
```

---

## 11. Variáveis de Ambiente

Lista completa: [variaveis-ambiente.md](./variaveis-ambiente.md).

Arquivo único: `/opt/nistiprint/.env` (compartilhado entre os 3 services).
