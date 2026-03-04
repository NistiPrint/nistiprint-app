# NistiPrint Frontend - V2 (React + Vite)

Este é o frontend da aplicação NistiPrint, desenvolvido com React e Vite.

## 🚀 Setup e Execução Local

### Pré-requisitos
- Node.js (versão 18 ou superior)
- npm ou yarn

### Instalação de Dependências
```bash
cd nistiprint-frontend
npm install
# ou yarn install
```

### Executar em Modo de Desenvolvimento
```bash
npm run dev
# ou yarn dev
```
A aplicação estará disponível em `http://localhost:5173`.

### Construir para Produção
```bash
npm run build
# ou yarn build
```
Os arquivos estáticos serão gerados na pasta `dist/`.

## ⚙️ Configuração
As variáveis de ambiente são configuradas via `.env` e `.env.production`. Consulte `nistiprint-frontend/.env.example` para as variáveis necessárias.

## 📝 Documentação
- Guia de Componentes: `guia-componentes.md`
- **Para informações detalhadas sobre setup de ambiente e variáveis, consulte:**
  - `docs/development/local_setup.md`
  - `docs/configuration/environment_variables.md`

## 🐳 Docker
Para construir a imagem Docker e executar em ambiente conteinerizado, consulte:
- `nistiprint-frontend/Dockerfile`
- `docs/deployment/overview.md`
- `docs/deployment/infrastructure_setup.md`
