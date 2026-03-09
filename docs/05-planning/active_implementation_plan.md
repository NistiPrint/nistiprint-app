# Revisão de Variações e Composições (BOM)

## Contexto e Objetivo Estratégico
O sistema atual apresenta conflitos entre a herança de variações e a gestão de composições (BOM). Variações que herdam o BOM do pai não conseguem customizar componentes de forma intuitiva, e as mudanças feitas via API/UI muitas vezes são ignoradas ou resultam em inconsistências visuais (o usuário adiciona um componente mas continua vendo o do pai). O objetivo é permitir que variações herdem o BOM por padrão, mas possam "desvincular" e customizar sua composição sem perder a referência ao produto pai.

## Arquitetura e Entidades
- **Produtos**: Adição/Correção de suporte aos campos `parent_id`, `herdar_bom_pai`, `herdar_dados_pai` na API de atualização.
- **Ficha Técnica (BOM)**: Manutenção do relacionamento atual, mas com lógica de interface para "Snapshot" (cópia) do pai para o filho no momento da customização.

## Plano de Ação (Para Execução no CLine)

### Backend (API e Services)
- [ ] **Task 1: Corrigir Rota de Edição de Produtos** - Atualizar `apps/api/routes/produtos.py` para incluir `parent_id`, `herdar_bom_pai` e `herdar_dados_pai` no dicionário `dados_atualizacao` da função `api_editar`.
- [ ] **Task 2: Lógica de Cópia de BOM** - Implementar no `BomService` (ou `ProductService`) um método `copy_bom_from_parent(product_id)` que desativa `herdar_bom_pai` e duplica os registros da `ficha_tecnica` do pai para o produto filho.
- [ ] **Task 3: Melhorar `get_bom_components`** - Garantir que o retorno de componentes informe se os dados são herdados ou próprios.

### Frontend (UI/UX)
- [ ] **Task 4: Habilitar BOM para Produtos Pai** - Alterar `ProdutoFormPage.jsx` para permitir a aba BOM mesmo quando `formato === 'com_variacao'`.
- [ ] **Task 5: BOMManager com Consciência de Herança** - No `BOMManager.jsx`, se `herdar_bom_pai` for true, exibir componentes em modo leitura e mostrar botão "Customizar Composição".
- [ ] **Task 6: Implementar Botão "Customizar"** - O botão deve chamar a nova lógica de cópia do BOM e atualizar o estado da tela para modo edição.
- [ ] **Task 7: Ajustar VariationEditModal** - Garantir que o modal de edição de variação salve corretamente os flags de herança e forneça feedback sobre o BOM.

## Observações de Manutenção
- Ao desativar a herança, o produto filho torna-se independente. Mudanças futuras no pai **não** refletirão no filho. Isso deve ser avisado ao usuário.
- A consistência do SKU deve ser mantida para evitar que a customização do BOM quebre integrações externas.
