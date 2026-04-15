# Nistiprint — Documentação

**Última atualização:** 2026-04-13

---

## 📄 Documentos Principais

| Documento | Descrição |
|-----------|-----------|
| [Regras de Negócio](./negocio/REGRAS.md) | Princípios, ciclos, validações, cálculos e dependências |
| [Arquitetura Técnica](./tecnico/ARQUITETURA.md) | Componentes, fluxos, serviços, endpoints, workers |
| [Modelo de Dados](./tecnico/MODELO-DADOS.md) | ER completo, tabelas, colunas, funções SQL, triggers, RLS |
| [Manual do Usuário](./usuario/MANUAL.md) | Fluxos, interface, operações, atalhos, FAQ |

---

## 📁 Estrutura

```
docs/
├── README.md                     ← Este arquivo
│
├── negocio/
│   └── REGRAS.md                 Regras de negócio consolidadas
│
├── tecnico/
│   ├── ARQUITETURA.md            Arquitetura técnica
│   ├── MODELO-DADOS.md           Modelo ER do banco
│   └── APIs/
│       ├── bling.md              Referência API Bling V3
│       └── shopee.md             Referência API Shopee V2
│
├── usuario/
│   └── MANUAL.md                 Manual do usuário
│
├── guias/
│   ├── setup-local.md            Setup de desenvolvimento
│   ├── git-workflow.md           Workflow Git
│   └── criar-integracao.md       Como criar novo módulo de integração
│
├── operacoes/
│   ├── deploy.md                 Guia de deploy (visão geral + comandos)
│   ├── deploy-gcp.md             Deploy unificado no GCP
│   ├── infraestrutura.md         Setup detalhado de infraestrutura
│   ├── variaveis-ambiente.md     Variáveis de ambiente
│   └── logging.md                Logging com rotação
│
├── estoque/
│   ├── arquitetura.md            Event Sourcing para estoque
│   ├── motor-estoque.md          Especificação do Motor de Gerenciamento
│   ├── ux.md                     UX do monitoramento
│   └── validacao.md              Guia de validação e debug
│
├── executivo/                    Documentos para stakeholders (CTO/PM)
│   ├── README.md                 Índice executivo
│   ├── analise-executiva.md      Análise executiva
│   ├── sumario-executivo.md      Sumário em português
│   ├── plano-implementacao.md    Plano de implementação
│   ├── plano-correcao-otimizacao.md Plano técnico
│   ├── diagrama-fluxos.md        Diagramas visuais
│   ├── quick-reference.md        Cheat sheet
│   └── indice-documentacao.md    Mapa por perfil
│
└── archive/                      Documentos históricos (consultar se necessário)
    ├── analise-aderencia.md
    ├── analise-permissoes.md
    ├── tarefas-assincronas.md
    ├── integration-store.md
    ├── order-enrichment.md
    ├── business-rules-overview.md
    ├── microservices.md
    ├── n8n.md
    ├── relatorio-final-implementacao.md
    ├── active-implementation-plan.md
    ├── maturity-assessment-2026.md
    ├── processar-fila-eventos-bling.md
    ├── tasks.md
    ├── php-to-n8n.md
    └── v2-to-v3.md
```

---

## 🎯 Por Perfil

| Perfil | Comece por |
|--------|-----------|
| Dev novo | `tecnico/ARQUITETURA.md` → `guias/setup-local.md` |
| Dev backend | `tecnico/MODELO-DADOS.md` → `tecnico/ARQUITETURA.md` |
| Dev frontend | `usuario/MANUAL.md` → `guias/criar-integracao.md` |
| Negócio / Suporte | `usuario/MANUAL.md` → `negocio/REGRAS.md` |
| DevOps | `operacoes/deploy.md` → `operacoes/variaveis-ambiente.md` |
| CTO / PM | `executivo/README.md` |
