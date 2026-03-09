
# Manual de Implementação: Infraestrutura Full-Stack e Automação

Este documento detalha a configuração completa do servidor, focando na orquestração visual, segurança de borda e recepção de webhooks via n8n.

## 1. Topologia de Rede e Volumes

Para garantir o isolamento, trabalhamos com duas redes:

* **`gateway_net`** : Comunicação entre o Proxy (NPM) e os serviços expostos (Portainer, n8n, Frontend).
* **`app-internal`** : Comunicação privada entre API, Redis e Workers.

### Preparação do Host

Execute no terminal da VPS para preparar o ambiente:

```
docker network create gateway_net
docker volume create portainer_data
docker volume create npm_data
docker volume create npm_letsencrypt

```

## 2. Camada de Gestão: Portainer

O Portainer gerencia o ciclo de vida dos containers via Docker Socket.

```
docker run -d --name portainer --restart=always \
    --network gateway_net \
    -p 9000:9000 -p 9443:9443 \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v portainer_data:/data \
    portainer/portainer-ce:latest

```

* **Acesso Inicial:** `https://IP_DO_SERVIDOR:9443`
* **Configuração:** Selecione "Local Environment" (Socket).

## 3. Camada de Borda: Nginx Proxy Manager (NPM)

Centraliza o tráfego 80/443 e automatiza certificados SSL via Let's Encrypt.

```
docker run -d --name nginx-proxy-manager --restart=always \
    --network gateway_net \
    -p 80:80 -p 443:443 -p 81:81 \
    -v npm_data:/data \
    -v npm_letsencrypt:/etc/letsencrypt \
    jc21/nginx-proxy-manager:latest

```

* **Acesso:** `http://IP_DO_SERVIDOR:81`
* **Login Padrão:** `admin@example.com` / `changeme`

## 4. Camada de Automação: n8n

O n8n atua como o receptor de webhooks e produtor para a fila Redis.

### Stack: `n8n-stack`

```
version: '3.8'
services:
  n8n:
    image: n8nio/n8n:latest
    container_name: n8n
    restart: always
    networks:
      - gateway_net
      - app-internal
    environment:
      - N8N_PORT=5678
      - N8N_PROTOCOL=https
      - N8N_HOST=automacao.nistiprint.neolabs.com.br
      - WEBHOOK_URL=[https://automacao.nistiprint.neolabs.com.br/](https://automacao.nistiprint.neolabs.com.br/)
      - GENERIC_TIMEZONE=America/Sao_Paulo
    volumes:
      - data:/home/node/.local/share/n8n

networks:
  gateway_net:
    external: true
  app-internal:
    driver: bridge

volumes:
  data:

```

## 5. Camada de Aplicação e Fila (Redis)

Esta stack contém a lógica de negócio e o processamento assíncrono.

### Stack: `app-core`

```
version: '3.8'
services:
  redis:
    image: redis:alpine
    restart: always
    networks:
      - app-internal

  backend:
    image: seu-registry/flask-api:latest
    environment:
      - REDIS_URL=redis://redis:6379/0
    networks:
      - app-internal

  worker:
    image: seu-registry/flask-api:latest
    command: celery -A tasks worker --loglevel=info
    depends_on:
      - redis
    networks:
      - app-internal

  frontend:
    image: seu-registry/react-app:latest
    networks:
      - gateway_net

networks:
  gateway_net:
    external: true
  app-internal:
    driver: bridge

```

## 6. Configuração de Proxy Hosts (NPM)

Configure cada serviço no painel do Nginx Proxy Manager:

| **Domínio**                      | **Host Destino** | **Porta** | **SSL**    |
| --------------------------------------- | ---------------------- | --------------- | ---------------- |
| `gestao.nistiprint.neolabs.com.br`    | `portainer`          | 9000            | Let's Encrypt    |
| `automacao.nistiprint.neolabs.com.br` | `n8n`                | 5678            | SSL + Websockets |
| `api.nistiprint.neolabs.com.br`       | `backend`            | 5000            | Let's Encrypt    |
| `app.nistiprint.neolabs.com.br`       | `frontend`           | 80              | Let's Encrypt    |

## 7. Fluxo n8n -> Redis (Integração Celery)

Para que o n8n envie os dados corretamente para o seu Worker:

1. **Nó Webhook** : Recebe o POST externo.
2. **Nó Redis** :

* **Host** : `redis` (resolução via rede interna).
* **Operation** : `Push to List`.
* **List Name** : `celery`.
* **Value** : `{{ JSON.stringify($json.body) }}` (O Celery exige que o payload da tarefa seja uma string JSON válida).

## 8. Manutenção e Backup

* **Backup:** O volume `data` da stack n8n é crítico (contém `database.sqlite`).
* **Monitoração:** Use o Portainer para verificar a saúde do `celery_worker`. Se os webhooks pararem de ser processados, verifique se o nó Redis no n8n está conseguindo conectar ao container `redis`.
