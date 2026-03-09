# Guia de Deploy Nistiprint (Multigeracional)

## 🚀 Fluxo de Trabalho por Geração

### Geração 1 (Legado - /app)
- **Host**: Google Cloud Run (ou conforme configurado).
- **Manutenção**: Alterar apenas dentro da pasta `/app`.

### Geração 2 (Estável - v2)
- **Pastas**: `nistiprint-core`, `nistiprint-frontend`.
- **Stack Portainer**: `nistiprint-v2-prod`.
- **Build**:
  ```bash
  docker build -t leandrogbreve/nistiprint-core:v1.x.x ./nistiprint-core
  docker build -t leandrogbreve/nistiprint-frontend:v1.x.x ./nistiprint-frontend
  ```

### Geração 3 (Nova Arquitetura - v3)
- **Pastas**: `nistiprint-api`, `nistiprint-worker`, `nistiprint-shared`.
- **Stack Portainer**: `nistiprint-v3-dev`.
- **⚠️ IMPORTANTE**: Build deve ser feito da RAIZ do projeto.
- **Build**:
  ```bash
  docker build -t leandrogbreve/nistiprint-api:v2.x.x -f ./nistiprint-api/Dockerfile .
  docker build -t leandrogbreve/nistiprint-worker:v2.x.x -f ./nistiprint-worker/Dockerfile .
  ```

## 🛠️ Portainer Stacks
1. **nistiprint-ops**: Nginx Proxy Manager, Redis, n8n.
2. **nistiprint-v2-prod**: API (Core) e Frontend estáveis.
3. **nistiprint-v3-dev**: Nova API e Worker em desenvolvimento.

## 📝 Notas de Manutenção
- **Shared**: Sempre que alterar `nistiprint-shared`, re-buildar API e Worker v3.
- **Tags**: Use versionamento semântico (v1.0.1, v2.0.0-beta) para evitar confusão.
- **Re-pull**: No Portainer, sempre marque "Re-pull image" ao atualizar uma stack.
