# Logging Persistente - Nistiprint

## Visão Geral

Todos os containers Docker agora possuem **logging persistente com rotação automática**, garantindo que os logs sejam mantidos por até **7 dias** sem consumir espaço excessivo em disco.

---

## Configuração

### Driver de Logging

Todos os serviços utilizam o driver `local` do Docker com as seguintes configurações:

| Parâmetro | Valor | Descrição |
|-----------|-------|-----------|
| `driver` | `local` | Driver nativo do Docker com rotação |
| `max-size` | `10m` | Tamanho máximo por arquivo: 10MB |
| `max-file` | `10` | Máximo de 10 arquivos por container |
| `compress` | `true` | Compressão automática de logs antigos |

### Capacidade de Armazenamento

```
Por container:
  - 10 arquivos × 10MB = 100MB máximo
  - Com compressão: ~20-30MB real (taxa ~70%)

Produção (2 containers):
  - Máximo: ~200MB
  - Com compressão: ~40-60MB

Local (5 containers):
  - Máximo: ~500MB
  - Com compressão: ~100-150MB
```

### Retenção Estimada

Com a configuração atual, os logs são retidos por **7-14 dias** dependendo do volume de logs gerados por cada serviço.

---

## Serviços Configurados

### Produção (`docker-compose.yml`)

- ✅ `frontend` - React/Vite
- ✅ `api` - Flask API

### Desenvolvimento (`docker-compose.local.yml`)

- ✅ `redis` - Cache e filas
- ✅ `api` - Flask API
- ✅ `worker` - Celery Worker
- ✅ `celery-beat` - Celery Beat (scheduler)
- ✅ `frontend` - React/Vite

---

## Utilização

### Comandos Docker Nativos

```bash
# Ver logs de um serviço
docker logs <container_name>

# Logs em tempo real
docker logs -f <container_name>

# Últimas 100 linhas
docker logs --tail 100 <container_name>

# Logs com timestamp
docker logs -t <container_name>

# Filtrar por data (últimas 24h)
docker logs --since 24h <container_name>

# Buscar termo específico
docker logs <container_name> 2>&1 | grep "ERROR"
```

### Scripts de Gerenciamento

#### Linux/Mac

```bash
# Status de todos os containers
./scripts/logs.sh status

# Tamanho dos logs
./scripts/logs.sh size

# Monitorar em tempo real
./scripts/logs.sh follow api

# Últimas 200 linhas
./scripts/logs.sh tail api 200

# Buscar termo
./scripts/logs.sh search api "error"

# Exportar logs
./scripts/logs.sh export api
```

#### Windows

```cmd
REM Status de todos os containers
scripts\logs.bat status

REM Tamanho dos logs
scripts\logs.bat size

REM Monitorar em tempo real
scripts\logs.bat follow api

REM Últimas 200 linhas
scripts\logs.bat tail api 200

REM Buscar termo
scripts\logs.bat search api error

REM Exportar logs
scripts\logs.bat export api
```

---

## Onde os Logs são Armazenados

### Linux

```
/var/lib/docker/containers/<container_id>/
  └── <container_id>-json.log
      <container_id>-json.log.1.gz
      <container_id>-json.log.2.gz
      ...
```

### Windows (Docker Desktop)

```
\\wsl$\docker-desktop-data\data\docker\containers\<container_id>\
  └── <container_id>-json.log
      <container_id>-json.log.1.gz
      ...
```

### macOS (Docker Desktop)

```
~/Library/Containers/com.docker.docker/Data/vms/0/data/
  └── Docker.raw (imagem completa)
```

---

## Rotação de Logs

### Como Funciona

```
1. Container gera logs → arquivo principal
2. Arquivo atinge 10MB → rotaciona
3. Arquivo antigo comprimido (.gz)
4. Após 10 arquivos → mais antigo é deletado
```

### Diagrama de Rotação

```
┌─────────────────────────────────────────────────┐
│  Container gera logs (stdout/stderr)            │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│  json.log (arquivo atual - max 10MB)           │
└───────────────────┬─────────────────────────────┘
                    │ (atingiu 10MB)
                    ▼
┌─────────────────────────────────────────────────┐
│  json.log.1 (comprimido)                        │
│  json.log.2 (comprimido)                        │
│  ...                                            │
│  json.log.10 (comprimido - será deletado)       │
└─────────────────────────────────────────────────┘
```

---

## Monitoramento

### Verificar Espaço Usado

```bash
# Espaço total usado por logs
docker system df -v | grep "log"

# Limpar logs não usados
docker system prune -f
```

### Alertas Recomendados

Monitore o diretório de logs do Docker:

```bash
# Verificar tamanho total
du -sh /var/lib/docker/containers/

# Listar maiores arquivos
du -ah /var/lib/docker/containers/ | sort -rh | head -20
```

---

## Troubleshooting

### Logs não aparecem

```bash
# Verificar se container está rodando
docker ps | grep <service>

# Reiniciar container
docker-compose restart <service>

# Verificar configuração
docker inspect <container> | grep -A 10 LogConfig
```

### Logs consumindo muito espaço

```bash
# Limpar logs de todos os containers
docker logs <container> > /dev/null 2>&1

# Ou usar script
./scripts/logs.sh clean
```

### Container específico com muitos logs

```bash
# Verificar tamanho
docker inspect --format='{{.LogPath}}' <container> | xargs du -sh

# Truncar logs (sem parar container)
truncate -s 0 $(docker inspect --format='{{.LogPath}}' <container>)
```

### Windows - Acesso aos Logs

```powershell
# Acessar via WSL2
wsl -d docker-desktop

# Navegar até diretório de logs
cd /var/lib/docker/containers

# Listar containers
ls -la
```

---

## Boas Práticas

### 1. Não aumente `max-file` desnecessariamente

O valor atual (10) já garante ~7 dias de retenção. Aumentar pode causar:
- Consumo excessivo de disco
- Performance degradada

### 2. Monitore o espaço em disco

```bash
# Verificar disco
df -h /var/lib/docker

# Alerta se > 80%
```

### 3. Exporte logs importantes

Para auditoria ou debugging:

```bash
# Exportar com timestamp
./scripts/logs.sh export api
```

### 4. Use logging centralizado (produção)

Para ambientes de produção, considere:
- **ELK Stack** (Elasticsearch, Logstash, Kibana)
- **Grafana Loki**
- **Cloud Logging** (GCP, AWS, Azure)

---

## Integração com GCP Cloud Run

No Cloud Run, os logs são gerenciados automaticamente pelo **Google Cloud Logging**:

```bash
# Ver logs no Cloud Run
gcloud run services logs read nistiprint-app --region southamerica-east1

# Logs em tempo real
gcloud run services logs tail nistiprint-app --region southamerica-east1

# Filtrar por severidade
gcloud run services logs read nistiprint-app \
    --region southamerica-east1 \
    --filter "severity>=ERROR"
```

### Retenção no Cloud Logging

| Tipo | Retenção |
|------|----------|
| Standard | 30 dias (grátis) |
| Long-term | Configurável (pago) |

---

## Próximos Passos

### Curto Prazo

- ✅ Configurar rotação de logs
- ✅ Criar scripts de gerenciamento
- ✅ Documentar procedimentos

### Médio Prazo

- [ ] Implementar health checks com logging
- [ ] Configurar alertas de erros críticos
- [ ] Centralizar logs (ELK/Loki)

### Longo Prazo

- [ ] Dashboard de monitoramento
- [ ] Análise automatizada de padrões
- [ ] Integração com PagerDuty/Sentry

---

## Referências

- [Docker Logging Documentation](https://docs.docker.com/config/containers/logging/)
- [Local Logging Driver](https://docs.docker.com/config/containers/logging/local/)
- [Cloud Run Logging](https://cloud.google.com/run/docs/logging)
