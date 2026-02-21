# Guia de Componentes de Páginas

## Visão Geral

Este guia define os padrões de estrutura e navegação para as páginas do sistema, considerando o layout sem menu no topo, barra lateral principal e barras laterais internas em algumas páginas.

## Layout Geral

- **Barra Lateral Esquerda**: Navegação principal do sistema
- **Área Central**: Conteúdo da página (main)
- **Barra Lateral Direita**: Informações adicionais/contextuais (opcional)
- **Sem Header Topo**: Navegação limitada à barra lateral

## Estrutura de Páginas

### 1. Páginas de Listagem

#### Estrutura
```jsx
<div className="space-y-6">
  <Card>
    <CardHeader>
      <CardTitle className="flex items-center justify-between">
        <span className="flex items-center gap-2">
          <Icon className="h-5 w-5" />
          Título da Página
        </span>
        <Button asChild>
          <Link to="novo">
            <PlusCircle className="mr-2 h-4 w-4" />
            Novo Item
          </Link>
        </Button>
      </CardTitle>
    </CardHeader>
    <CardContent>
      {/* Conteúdo da lista: tabela, grid, etc */}
    </CardContent>
  </Card>
</div>
```

#### Posicionamento de Elementos
- **Título**: Esquerda, com ícone
- **Botão "Novo"**: Direita do título
- **Conteúdo**: Abaixo, dentro de CardContent

### 2. Páginas de Formulário

#### Estrutura
```jsx
<Card className="max-w-xl mx-auto">
  <CardHeader>
    <CardTitle className="flex items-center gap-2">
      <Icon className="h-5 w-5" />
      {isEditing ? 'Editar' : 'Novo'} Item
    </CardTitle>
  </CardHeader>
  <CardContent>
    <Form>
      {/* Campos do formulário */}
      <div className="flex gap-4">
        <Button type="submit" className="flex-1">
          {isEditing ? 'Atualizar' : 'Criar'} Item
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => navigate('..')}
          className="flex-1"
        >
          Cancelar
        </Button>
      </div>
    </Form>
  </CardContent>
</Card>
```

#### Posicionamento de Elementos
- **Título**: Central, com ícone
- **Botões**: Final do formulário, lado a lado
  - **Salvar**: Primário, esquerda
  - **Cancelar**: Outline, direita, navega para '..'

### 3. Páginas com Barra Lateral Interna

#### Estrutura
```jsx
<div className="flex gap-6">
  <div className="flex-1">
    {/* Conteúdo principal */}
  </div>
  <div className="w-80 space-y-4">
    {/* Barra lateral interna com menus específicos */}
  </div>
</div>
```

#### Posicionamento de Elementos
- **Barra Lateral Interna**: Direita, largura fixa (~320px)
- **Conteúdo Principal**: Esquerda, flexível

## Componentes Reutilizáveis

### PageHeader
Localizado em `src/components/ui/PageHeader.jsx`

Uso:
```jsx
import PageHeader from '@/components/ui/PageHeader';
import { Users } from 'lucide-react';

<PageHeader
  title="Usuários"
  icon={Users}
  actions={<Button>Novo Usuário</Button>}
/>
```

### PageActions
Localizado em `src/components/ui/PageActions.jsx`

Uso:
```jsx
import PageActions from '@/components/ui/PageActions';

<PageActions>
  <Button>Salvar</Button>
  <Button variant="outline">Cancelar</Button>
</PageActions>
```

## Navegação

### Botões de Navegação
- **Voltar**: Sempre usar `navigate('..')` para manter hierarquia
- **Novo**: Link para sub-rota "novo"
- **Editar**: Link para sub-rota "{id}/editar"

### Hierarquia de Rotas
```
/admin/usuarios -> Lista
/admin/usuarios/novo -> Novo
/admin/usuarios/{id}/editar -> Editar
```

## Ícones Consistentes

- **Listas**: Users, Factory, etc.
- **Novo**: PlusCircle
- **Editar**: Edit
- **Deletar**: Trash2

## Responsividade

- **Mobile**: Stack vertical, botões full-width
- **Desktop**: Botões lado a lado, layout horizontal

## Exceções

Páginas complexas (ex: produção) podem usar componentes específicos como HeaderSection, FiltersSection, etc., mas devem seguir os princípios gerais de posicionamento.
