# Guia de Deploy — Nistiprint

**Última atualização:** 2026-08-11

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
| Ingest confiável (8 papéis) | Processos no host | `systemd: nistiprint-ingest@<papel>` |
| Legado | Processo no host | `systemd: nistiprint-legado` |
| Redis | Container Docker (stack `nistiprint-infra`) | Portainer |
| n8n | Container Docker (stack `nistiprint-infra`) | Portainer |
| nginx-proxy-manager | Container Docker | Portainer |

Os papéis do ingest são instâncias de um mesmo template: `router`, `orders`,
`chat`, `retry`, `lease`, `spool`, `archive` e `monitor`. Cada um é uma unidade
independente (`nistiprint-ingest@orders.service`) — ver
[ingest-reliable-queues.md](./ingest-reliable-queues.md).

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

O script vive no repositório (`deploy.sh` na raiz) e é o mesmo arquivo em
`/opt/nistiprint/deploy.sh`. **Não reproduza o conteúdo dele aqui**: uma cópia
nesta página ficou desatualizada por meses, ainda descrevendo o deploy como o
restart de três serviços, enquanto o servidor já rodava doze.

Etapas, em ordem:

1. `git fetch` + `git reset --hard origin/main`
2. Limpeza de resíduos de `pip` interrompido e checagem de dono do venv
3. `pip install` das três requirements + `-e packages/shared`
4. Verificação de que `nistiprint_shared` carrega de `/opt/nistiprint/packages/shared/`
5. **Restart dos serviços de backend**
6. Build do frontend

O backend reinicia **antes** do frontend de propósito: o build do frontend é a
etapa mais frágil (memória, rede, lockfile) e já impediu correção de backend de
chegar em produção por dias. Falhando agora, o backend já está atualizado e o
frontend continua servindo o build anterior.

> O `git reset --hard` é seguro porque o servidor é apenas runtime — qualquer alteração local é acidental.

### Descoberta dos serviços

O `deploy.sh` **não tem lista fixa de serviços**. Ele descobre em tempo de
execução, unindo `systemctl list-units` (pega as instâncias de template que de
fato rodam) com `list-unit-files` (pega as habilitadas ainda não carregadas), e
descarta o template puro `nistiprint-ingest@.service`, que não é executável.

Isso existe por causa de um incidente: o worker de ingest ficou de fora da lista
fixa antiga e seguiu servindo código velho da memória por dias, enquanto
api/worker/beat reiniciavam e o deploy se declarava bem-sucedido.

O restart é **um serviço por vez**, em laço — e não `systemctl restart a b c`.
Isso não é estilo: o sudoers casa comando por comando (ver seção 4).

---

## 4. Permissões de restart (sudoers)

O usuário `nistiprint` não é sudoer. Ele recebe permissão para **exatamente** os
restarts que o deploy precisa, em `/etc/sudoers.d/nistiprint-deploy`:

```
Cmnd_Alias NISTIPRINT_SERVICES = /bin/systemctl restart nistiprint-api.service, \
    /bin/systemctl restart nistiprint-beat.service, \
    /bin/systemctl restart nistiprint-ingest@archive.service, \
    /bin/systemctl restart nistiprint-ingest@chat.service, \
    /bin/systemctl restart nistiprint-ingest@lease.service, \
    /bin/systemctl restart nistiprint-ingest@monitor.service, \
    /bin/systemctl restart nistiprint-ingest@orders.service, \
    /bin/systemctl restart nistiprint-ingest@retry.service, \
    /bin/systemctl restart nistiprint-ingest@router.service, \
    /bin/systemctl restart nistiprint-ingest@spool.service, \
    /bin/systemctl restart nistiprint-legado.service, \
    /bin/systemctl restart nistiprint-worker.service

nistiprint ALL=(root) NOPASSWD: NISTIPRINT_SERVICES
```

As quebras com `\` acima são só legibilidade — sudoers aceita a mesma lista em
uma linha única, que é como o arquivo está no servidor.

Editar **sempre** com `sudo visudo -f /etc/sudoers.d/nistiprint-deploy`. Um erro
de sintaxe salvo direto quebra o `sudo` do servidor inteiro; o `visudo` valida
antes de gravar.

### As três regras que fazem isso quebrar

**1. O sufixo `.service` é obrigatório.** O sudo casa a linha de comando
literalmente, sem entender systemd. A versão anterior deste arquivo listava
`/bin/systemctl restart nistiprint-api` (sem sufixo), e o `deploy.sh` chama com
`nistiprint-api.service`, porque é assim que o nome sai do `systemctl list-units`.
Strings diferentes, nenhuma correspondência, restart negado.

**2. Um serviço por comando.** Cada entrada autoriza um argumento só. Um
`sudo systemctl restart nistiprint-api.service nistiprint-worker.service` não
casa com nenhuma linha e é negado — por isso o `deploy.sh` reinicia em laço.

**3. Serviço novo exige atualizar este arquivo.** Aqui mora a armadilha: o
`deploy.sh` descobre serviços dinamicamente, então um `nistiprint-*.service` novo
entra no laço sozinho e dá a impressão de que "só funciona". Mas o sudoers é
allowlist fixa — o serviço novo é descoberto e então **negado**. É a mesma classe
de falha que a lista fixa antiga do `deploy.sh` causou, só que deslocada um nível
para baixo.

Ao subir um serviço `nistiprint-*` novo (ou um papel novo de ingest), adicione a
linha correspondente aqui **no mesmo deploy**.

### Alternativa: curinga

Se a manutenção manual incomodar, o sudo aceita curinga no argumento:

```
nistiprint ALL=(root) NOPASSWD: /bin/systemctl restart nistiprint-*.service
```

Isso elimina a regra 3 — serviço novo passa a funcionar sem editar sudoers. O
custo é conceder restart de qualquer unidade `nistiprint-*` futura, inclusive uma
que ninguém revisou. Para um usuário cujo trabalho é justamente reiniciar todos
os serviços da aplicação, a troca é defensável; a lista explícita foi mantida por
ser mais auditável.

### Diagnosticando

```bash
# o que o usuario de deploy pode rodar
sudo -l -U nistiprint

# tentativa negada aparece no log de autenticacao
journalctl -u ssh --grep nistiprint | tail
grep sudo /var/log/auth.log | tail
```

Restart negado costuma aparecer no deploy como
`Sorry, user nistiprint is not allowed to execute '/bin/systemctl restart …'`.
Com `set -euo pipefail`, o `deploy.sh` aborta ali — então o sintoma é deploy que
falha no meio, com o backend já atualizado em disco mas ainda servindo código
velho da memória.

---

## 5. Rollback

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

## 6. Verificação pós-deploy

```bash
# API direta no host
curl http://127.0.0.1:8080/health

# Frontend (Caddy) direto no host
curl -I http://127.0.0.1:3000/

# Status de TODOS os services (inclui as instancias de ingest)
systemctl list-units 'nistiprint-*' --type=service --all --no-pager

# Publicos (via NPM)
curl -I https://app.nistiprint.neolabs.com.br/
curl https://app.nistiprint.neolabs.com.br/api/health
```

O próprio `deploy.sh` imprime `is-active` de cada serviço que reiniciou no fim
da execução — é a checagem mais direta de que nenhum ficou para trás.

### Confirmando que o beat pegou o schedule novo

O beat lê `configuracoes_aplicacao.celery_task_schedules` **no start**. Habilitar
ou alterar uma task periódica pelo banco não reagenda o processo em execução:
sem restart do `nistiprint-beat`, a configuração fica valendo no papel e não na
prática. Depois de mexer em agendamento:

```sql
select task_name, status, max(created_at) as ultima
from task_execution_logs
where created_at > now() - interval '1 hour'
group by 1, 2 order by 3 desc;
```

Task habilitada que não aparece aqui não está rodando.

---

## 7. Atualizando dependências

### Python (api / worker / shared)
1. Edite `requirements.txt` correspondente
2. Commit e push → o `deploy.sh` roda `pip install` automaticamente

### Frontend
1. `npm install <pacote>` localmente
2. **Commit `package.json` e `package-lock.json` juntos** (lock fora de sincronia quebra o `npm ci` no servidor)
3. Push → `deploy.sh` faz o build

---

## 8. Variáveis de ambiente

Mantidas em `/opt/nistiprint/.env` (chmod 600, owner `nistiprint`). Não estão no Git.

Todos os services systemd carregam o mesmo arquivo via `EnvironmentFile=/opt/nistiprint/.env`.

Para alterar uma variável:
```bash
sudo -u nistiprint nano /opt/nistiprint/.env
/opt/nistiprint/deploy.sh          # reinicia todos, sem lista fixa
```

Reiniciar só o que interessa também funciona, mas um serviço por comando — como
usuário `nistiprint`, `systemctl restart a b c` é negado pelo sudoers:
```bash
sudo systemctl restart nistiprint-api.service
sudo systemctl restart nistiprint-worker.service
```

> Cuidado: o parser do systemd **não** aceita aspas em volta dos valores nem `#` no meio da linha. Valores multi-linha (ex: JSON do Firebase) precisam estar em uma única linha com `\n` literais.

Lista completa das variáveis: [variaveis-ambiente.md](./variaveis-ambiente.md).

---

## 9. Comandos úteis

| Tarefa | Comando |
|---|---|
| Deploy manual | `/opt/nistiprint/deploy.sh` |
| Deploy sem frontend | `SKIP_FRONTEND=1 /opt/nistiprint/deploy.sh` |
| Status de todos os services | `systemctl list-units 'nistiprint-*' --type=service --all` |
| Reiniciar tudo | `/opt/nistiprint/deploy.sh` |
| Reiniciar um service | `sudo systemctl restart nistiprint-api.service` |
| Permissões do usuário de deploy | `sudo -l -U nistiprint` |
| Editar o sudoers do deploy | `sudo visudo -f /etc/sudoers.d/nistiprint-deploy` |
| Logs API (live) | `journalctl -u nistiprint-api -f` |
| Logs Worker (live) | `journalctl -u nistiprint-worker -f` |
| Logs de um papel do ingest | `journalctl -u nistiprint-ingest@orders -f` |
| Recarregar Caddy | `sudo systemctl reload caddy` |
| Containers ativos | `docker ps` |

---

## 10. Checklist ao adicionar um service novo

Serviço `nistiprint-*` novo (ou papel novo de ingest) precisa dos três passos —
pular o segundo faz o deploy inteiro abortar:

1. Criar/instalar a unit e habilitar (`systemctl enable --now`)
2. **Adicionar a linha em `/etc/sudoers.d/nistiprint-deploy`** via `visudo -f`
3. Conferir com `sudo -l -U nistiprint` e rodar um `deploy.sh` de validação

O `deploy.sh` acha o serviço sozinho — é justamente por isso que o passo 2 passa
despercebido até o deploy quebrar.

---

## 11. Referências

- [infraestrutura.md](./infraestrutura.md) — detalhamento dos services systemd, Caddy e NPM
- [ingest-reliable-queues.md](./ingest-reliable-queues.md) — papéis do `nistiprint-ingest@`
- [logging.md](./logging.md) — como ler logs (journalctl)
- [variaveis-ambiente.md](./variaveis-ambiente.md) — variáveis usadas pela aplicação
