# 🛠️ Fluxo de Trabalho Git (Monorepo)

Este documento define o padrão de ramificação (branching) e colaboração para o projeto Nistiprint.

## 1. Estratégia de Branches

Utilizamos o **GitHub Flow** adaptado para Monorepo. O foco é a entrega de funcionalidades completas, independentemente de quais apps (`api`, `frontend`, `worker`) sejam afetados.

### ❌ O que NÃO fazer
- Criar branches por aplicação (ex: `branch-api`, `branch-frontend`).
- Commits genéricos (ex: `update`, `fix`).

### ✅ O que fazer
- Criar branches baseadas na **funcionalidade** ou **problema**.
- Usar prefixos semânticos.

---

## 2. Padrão de Nomenclatura

| Prefixo | Descrição | Exemplo |
| :--- | :--- | :--- |
| `feat/` | Nova funcionalidade ou melhoria | `feat/rastreabilidade-lotes` |
| `fix/` | Correção de erro/bug | `fix/calculo-uom-resma` |
| `docs/` | Apenas documentação | `docs/update-architecture` |
| `infra/` | Docker, CI/CD, Scripts de infra | `infra/setup-github-actions` |
| `refactor/` | Mudança de estrutura sem mudar lógica | `refactor/unit-of-work` |

---

## 3. Commits Semânticos (Scope)

Como estamos em um monorepo, utilize o escopo no commit para indicar qual parte do sistema foi afetada:

- `feat(api): implementa novo endpoint de auditoria`
- `fix(web): corrige alinhamento no dashboard de produção`
- `feat(shared): adiciona helper de data no pacote nistiprint-shared`
- `infra(docker): adiciona healthcheck no worker`

---

## 4. Ciclo de Vida de uma Task

1. **Sincronize:** Garanta que sua `main` local está atualizada.
2. **Crie a Branch:** `git checkout -b feat/minha-feature`.
3. **Desenvolva:** Faça mudanças em qualquer pasta (`apps/` ou `packages/`).
4. **Valide:** Execute os testes/lint específicos do que você alterou.
5. **Merge:** Pull Request para `main` (ou merge direto se for o único dev).
