# 📚 Nistiprint - Documentação do Projeto

Bem-vindo à central de conhecimento da plataforma **Nistiprint**. A documentação foi organizada em categorias para facilitar a navegação e a manutenção da maturidade técnica.

## 📂 Estrutura de Diretórios

### [01-Architecture/](./01-architecture/)
Visão macro da plataforma, decisões arquiteturais (ADRs) e modelos de dados.
- `microservices.md`: Visão geral dos microsserviços.
- `n8n.md`: Fluxos de automação e integração externa.

### [02-Features/](./02-features/)
Documentação funcional e planos de funcionalidades específicas.
- `/business_rules/`: Regras de negócio de estoque, produção e logística.
- `/integrations/`: Documentação de webhooks (Shopee, Bling) e marketplace.
- `integration_store.md`: Loja de integrações nativas.
- `order_enrichment.md`: Enriquecimento de pedidos via IA.

### [03-Guides/](./03-guides/)
Tudo o que você precisa para começar a desenvolver e contribuir.
- `setup_local.md`: Guia de configuração do ambiente de desenvolvimento (Docker, Supabase).
- `create_integration_module.md`: Como criar um novo driver de integração.

### [04-Operations/](./04-operations/)
Guia operacional, infraestrutura e resolução de problemas.
- `infrastructure_setup.md`: Provisionamento e deploy (Google Cloud Run).
- `environment_variables.md`: Guia das variáveis de ambiente necessárias.
- `troubleshooting/`: Resolução de problemas comuns e guias de emergência.

### [05-Planning/](./05-planning/)
Fase atual do projeto, assessments e planejamento tático.
- `active_implementation_plan.md`: Plano de execução atual para o CLine/Agente.
- `maturity_assessment_2026.md`: Avaliação detalhada de maturidade (Produção e Estoque).

---

### [Archive/](./archive/)
Histórico de versões (v1, v2, v3) e planos de implementação já concluídos.

---

## 🛠️ Como Contribuir com a Documentação
- Sempre documente novas funcionalidades antes ou durante a implementação.
- Mantenha o arquivo `active_implementation_plan.md` atualizado com o progresso real.
- Utilize o padrão de assessment para avaliar a maturidade de novos módulos.
