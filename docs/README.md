# Nistiprint - Documentacao

Last updated: 2026-06-16

## Fonte de verdade

Para o dominio de integracoes, origem da venda, pedidos canonicos e NF, a fonte
de verdade e:

- [Arquitetura Tecnica](./tecnico/ARQUITETURA.md)
- [Modelo de Dados](./tecnico/MODELO-DADOS.md)
- [Regras de Negocio](./negocio/REGRAS.md)
- [Manual do Usuario](./usuario/MANUAL.md)
- [Spec de Integracoes](./specs/02-domains/integracoes/spec.md)
- [Spec de Pedidos](./specs/02-domains/pedidos/spec.md)
- [API Contracts](./specs/03-contracts/api-contracts.md)
- [Supabase Contracts](./specs/03-contracts/supabase-contracts.md)
- [Glossary](./specs/00-governance/glossary.md)
- [Decision Record 2026-06](./specs/00-governance/2026-06-integracoes-pedidos-canonicos.md)

## Politica de leitura

- `docs/specs/*` e `docs/tecnico/*` definem o contrato alvo
- `docs/usuario/MANUAL.md` traduz o contrato para operacao
- `docs/archive/*` e outros documentos marcados como legado servem apenas como
  contexto historico

## Estrutura principal

```text
docs/
|-- README.md
|-- negocio/
|   `-- REGRAS.md
|-- tecnico/
|   |-- ARQUITETURA.md
|   |-- MODELO-DADOS.md
|   `-- APIs/
|-- usuario/
|   `-- MANUAL.md
|-- specs/
|   |-- 00-governance/
|   |-- 02-domains/
|   `-- 03-contracts/
|-- guias/
|-- operacoes/
`-- archive/
```

## Onde comecar

| Perfil | Documento |
| --- | --- |
| Backend | `tecnico/ARQUITETURA.md` then `specs/03-contracts/supabase-contracts.md` |
| Frontend | `usuario/MANUAL.md` then `specs/03-contracts/api-contracts.md` |
| Produto/Operacao | `usuario/MANUAL.md` then `negocio/REGRAS.md` |
| Revisao de dados | `tecnico/MODELO-DADOS.md` |

## Importante

Documentos antigos que tratam Bling como fonte primaria unica de todos os
pedidos ou tratam tabelas especificas por marketplace como modelo principal
devem ser considerados superados por esta documentacao.
