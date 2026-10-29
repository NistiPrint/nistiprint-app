// Registro unico de navegacao.
//
// Regra R1 do Plano de Otimizacao: um destino aparece em exatamente um item
// de menu. Regra R2: menus sao dados, nao efeitos colaterais espalhados por
// seis componentes. Antes desta refatoracao, cada hub (Vendas, Producao,
// Cadastros, Sistema, Configuracoes, Relatorios) mantinha a propria copia de
// renderMenuItems e injetava a barra lateral por useEffect, com um cleanup
// que apagava o menu ao navegar para uma rota irma.
//
// Quem consome:
//   - Header.jsx           -> TOP_NAV
//   - MainLayout.jsx       -> SECOES, via secaoParaRota()
//   - Breadcrumbs.jsx      -> rotulosDeRota()
//   - scripts/verificar-rotas.mjs -> coletarHrefs()

import {
  Activity, AlertCircle, BarChart3, Boxes, Building, CalendarClock, ClipboardList, Cog, Database,
  Download,
  Factory,
  Home, Layers, MapPin, Monitor, Package, Printer, Scale, ScrollText,
  Settings, Share2, ShieldCheck, ShoppingCart, Sparkles, Store, Tag, TowerControl,
  Trello, Truck, Users, Warehouse
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Menu superior
// ---------------------------------------------------------------------------
export const TOP_NAV = [
  { name: 'Home', href: '/', icon: Home, type: 'link' },
  {
    name: 'Pedidos',
    icon: ShoppingCart,
    type: 'collapsible',
    children: [
      { name: 'Pedidos', href: '/vendas/pedidos', type: 'link', permission: { a: 'vendas', I: 'ler' } },
      { name: 'Torre de Despacho', href: '/despacho', type: 'link', permission: { a: 'vendas', I: 'ler' } },
      { name: 'Personalizados', href: '/vendas/personalizadas', type: 'link', permission: { a: 'vendas', I: 'ler' } },
    ],
  },
  {
    name: 'Produção',
    icon: Cog,
    type: 'collapsible',
    children: [
      { name: 'Demandas', href: '/producao/demanda', type: 'link', permission: { a: 'demanda_producao', I: 'ler' } },
      { name: 'Miolos', href: '/producao/miolos', type: 'link', permission: { a: 'producao', I: 'ler' } },
      { name: 'Capas', href: '/producao/capas', type: 'link', permission: { a: 'producao', I: 'ler' } },
      { name: 'Expedição', href: '/producao/expedicao', type: 'link', permission: { a: 'producao', I: 'ler' } },
      { name: 'Impressão', href: '/producao/impressao', type: 'link', permission: { a: 'producao', I: 'ler' } },
    ],
  },
  {
    name: 'Estoque',
    icon: Warehouse,
    href: '/estoque',
    type: 'link',
    permission: { a: 'estoque', I: 'ler' },
  },
  {
    name: 'Catálogo',
    icon: Boxes,
    type: 'collapsible',
    children: [
      { name: 'Produtos', href: '/produtos', type: 'link', permission: { a: 'produtos', I: 'ler' } },
      { name: 'Anúncios', href: '/anuncios', type: 'link', permission: { a: 'produtos', I: 'ler' } },
      { name: 'Categorias', href: '/cadastros/categoria', type: 'link', permission: { a: 'cadastros', I: 'ler' }, adminOnly: true },
      { name: 'Tags', href: '/cadastros/tag', type: 'link', permission: { a: 'cadastros', I: 'ler' }, adminOnly: true },
      { name: 'Unidades de Medida', href: '/cadastros/unidade-medida', type: 'link', permission: { a: 'cadastros', I: 'ler' }, adminOnly: true },
      { name: 'Conversões de Unidade', href: '/cadastros/uom-conversions', type: 'link', permission: { a: 'cadastros', I: 'ler' }, adminOnly: true },
    ],
  },
  {
    name: 'Monitoramento',
    icon: ScrollText,
    type: 'collapsible',
    children: [
      {
        name: 'Central de Operações',
        type: 'sub-collapsible',
        children: [
          { name: 'Minha atividade', href: '/monitoramento/operacoes/minha-atividade', type: 'link' },
          { name: 'Visão geral', href: '/monitoramento/operacoes/visao-geral', type: 'link', permission: { a: 'central_operacoes', I: 'ler' } },
          { name: 'Execuções', href: '/monitoramento/operacoes/execucoes', type: 'link', permission: { a: 'central_operacoes', I: 'ler' } },
          { name: 'Filas', href: '/monitoramento/operacoes/filas', type: 'link', permission: { a: 'central_operacoes', I: 'ler' } },
          { name: 'Auditoria', href: '/monitoramento/operacoes/auditoria', type: 'link', permission: { a: 'auditoria', I: 'ler' } },
          { name: 'Agendamentos', href: '/monitoramento/operacoes/agendamentos', type: 'link', adminOnly: true },
          { name: 'Manutenção', href: '/monitoramento/operacoes/manutencao', type: 'link', adminOnly: true },
        ],
      },
      {
        name: 'Relatórios',
        type: 'sub-collapsible',
        children: [
          { name: 'Dashboard', href: '/relatorios', type: 'link', permission: { a: 'relatorios', I: 'ler' } },
          { name: 'Histórico Produção', href: '/relatorios/historico-producao', type: 'link', permission: { a: 'relatorios', I: 'ler' } },
          { name: 'Histórico Coletas', href: '/relatorios/historico-coletas', type: 'link', permission: { a: 'relatorios', I: 'ler' } },
          { name: 'Monitoramento de Estoque', href: '/relatorios/monitoramento-estoque', type: 'link', permission: { a: 'relatorios', I: 'ler' } },
          { name: 'Webhooks', href: '/relatorios/webhooks', type: 'link', adminOnly: true },
          { name: 'Histórico Gerencial', href: '/relatorios/gerencial-historico', type: 'link', adminOnly: true },
          { name: 'Logs de IA', href: '/ai/logs', type: 'link', adminOnly: true, exato: true },
        ],
      },
    ],
  },
  {
    name: 'Gestão',
    icon: BarChart3,
    type: 'collapsible',
    children: [
      { name: 'Visão geral', href: '/gestao/visao-geral', type: 'link', permission: { a: 'gestao', I: 'ler' } },
      { name: 'Vendas e canais', href: '/gestao/vendas', type: 'link', permission: { a: 'gestao', I: 'ler' } },
      { name: 'Produtos e personalização', href: '/gestao/produtos', type: 'link', permission: { a: 'gestao', I: 'ler' } },
      { name: 'Público', href: '/gestao/publico', type: 'link', permission: { a: 'gestao', I: 'ler' } },
      { name: 'Rentabilidade', href: '/gestao/rentabilidade', type: 'link', permission: { a: 'gestao_financeiro', I: 'ler' } },
      { name: 'Planejamento', href: '/gestao/planejamento', type: 'link', permission: { a: 'gestao', I: 'ler' } },
      { name: 'Dados e integrações', href: '/gestao/qualidade', type: 'link', permission: { a: 'gestao', I: 'ler' } },
    ],
  },
  {
    name: 'Configurações',
    icon: Settings,
    type: 'collapsible',
    children: [
      { name: 'Visão geral', href: '/configuracoes', icon: Settings, type: 'link', adminOnly: true },
      {
        name: 'Conexões e canais',
        type: 'sub-collapsible',
        children: [
          { name: 'Contas e integrações', href: '/configuracoes/integracoes', type: 'link', adminOnly: true },
        ],
      },
      {
        name: 'Operação',
        type: 'sub-collapsible',
        children: [
          { name: 'Logística e despacho', href: '/configuracoes/janelas-despacho', type: 'link', adminOnly: true },
          { name: 'Pontos de Coleta', href: '/cadastros/ponto-coleta', type: 'link', adminOnly: true },
          { name: 'Depósitos', href: '/cadastros/deposito', type: 'link', adminOnly: true },
          { name: 'Fornecedores', href: '/cadastros/fornecedor', type: 'link', adminOnly: true },
          { name: 'Parâmetros de Produção', href: '/configuracoes/producao', type: 'link', adminOnly: true },
        ],
      },
      {
        name: 'Pessoas e acesso',
        type: 'sub-collapsible',
        children: [
          { name: 'Usuários', href: '/configuracoes/acessos/usuarios', type: 'link', adminOnly: true },
          { name: 'Setores', href: '/configuracoes/acessos/setores', type: 'link', adminOnly: true },
          { name: 'Acesso pendente', href: '/configuracoes/acessos/usuarios?status=pendente', type: 'link', adminOnly: true },
        ],
      },
      {
        name: 'IA',
        type: 'sub-collapsible',
        children: [
          { name: 'Inteligência artificial', href: '/configuracoes/ia', type: 'link', adminOnly: true },
        ],
      },
      {
        name: 'Sistema e ferramentas',
        type: 'sub-collapsible',
        children: [
          { name: 'Agente local', href: '/configuracoes/agente-local', type: 'link' },
        ],
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// Barras laterais por secao
//
// `prefixos` define a que rotas a secao pertence. A resolucao usa o prefixo
// mais longo que casa, entao /configuracoes vence /config e nao ha ambiguidade
// entre secoes irmas.
// ---------------------------------------------------------------------------
export const SECOES = [
  { id: 'gestao', titulo: 'Gestão', prefixos: ['/gestao'], grupos: [{ itens: [
    { name: 'Visão geral', href: '/gestao/visao-geral', icon: BarChart3, permission: { a: 'gestao', I: 'ler' } },
    { name: 'Vendas e canais', href: '/gestao/vendas', icon: Store, permission: { a: 'gestao', I: 'ler' } },
    { name: 'Produtos e personalização', href: '/gestao/produtos', icon: Boxes, permission: { a: 'gestao', I: 'ler' } },
    { name: 'Público', href: '/gestao/publico', icon: Users, permission: { a: 'gestao', I: 'ler' } },
    { name: 'Rentabilidade', href: '/gestao/rentabilidade', icon: Scale, permission: { a: 'gestao_financeiro', I: 'ler' } },
    { name: 'Planejamento', href: '/gestao/planejamento', icon: CalendarClock, permission: { a: 'gestao', I: 'ler' } },
    { name: 'Dados e integrações', href: '/gestao/qualidade', icon: Database, permission: { a: 'gestao', I: 'ler' } },
  ] }] },
  {
    id: 'agente-local',
    titulo: 'Configurações: Agente local',
    prefixos: ['/configuracoes/agente-local'],
    grupos: [{ itens: [
      { name: 'Baixar agente local', href: '/configuracoes/agente-local', icon: Download, description: 'Instalação do agente de impressão no Windows' },
    ] }],
  },
  {
    // A Torre de Despacho mora aqui, e nao em Producao: ela e o passo em que o
    // operador AGRUPA PEDIDOS. A demanda de producao e o que sai dela, nao o
    // que entra. Enquanto ficou sob Producao, o unico caminho ate o
    // agrupamento passava por um menu que descreve o galpao — e quem trabalha
    // com pedidos nao procurava ali.
    id: 'pedidos',
    titulo: 'Operação: Pedidos',
    prefixos: ['/vendas', '/despacho'],
    grupos: [
      {
        itens: [
          { name: 'Pedidos', href: '/vendas/pedidos', icon: ClipboardList, description: 'Gestão unificada de pedidos' },
          { name: 'Torre de Despacho', href: '/despacho', icon: TowerControl, description: 'Agrupar pedidos e publicar a demanda', exato: true },
          { name: 'Personalizados', href: '/vendas/personalizadas', icon: Users, description: 'Shopee e Mercado Livre em uma única área' },
        ],
      },
    ],
  },
  {
    id: 'producao',
    titulo: 'Operação: Produção',
    prefixos: ['/producao'],
    grupos: [
      {
        itens: [
          // Modo Foco saiu da lateral e virou botao dentro do Painel Geral: e um
          // modo de VER o mesmo trabalho, nao um destino irmao. Como item de
          // menu, competia com o painel de onde o operador acabou de sair.
          { name: 'Painel Geral', href: '/producao', icon: Trello, description: 'Kanban de produção por setor', adminOnly: true, exato: true, disabled: true },
          { name: 'Resumo Diário', href: '/producao/resumo', icon: BarChart3, description: 'Visão geral da produção do dia', adminOnly: true, disabled: true },
          { name: 'Demandas', href: '/producao/demanda', icon: ClipboardList, description: 'Acompanhar as demandas publicadas', permission: { a: 'demanda_producao', I: 'ler' } },
          { name: 'Miolos', href: '/producao/miolos', icon: Layers, description: 'Controle de produção de miolos', permission: { a: 'producao', I: 'ler' } },
          { name: 'Capas', href: '/producao/capas', icon: Layers, description: 'Controle de produção de capas', permission: { a: 'producao', I: 'ler' } },
          { name: 'Expedição', href: '/producao/expedicao', icon: Package, description: 'Sincronia e retirada de itens', permission: { a: 'producao', I: 'ler' } },
          { name: 'Impressão', href: '/producao/impressao', icon: Printer, description: 'Fila de impressão de artes', permission: { a: 'producao', I: 'ler' } },
        ],
      },
    ],
  },
  {
    // U3: o antigo "Cadastros Base" era uma gaveta sem criterio — misturava
    // catalogo (categorias, unidades) com configuracao de canal e de armazem.
    // Aqui fica so o que descreve O QUE a empresa vende.
    id: 'catalogo',
    titulo: 'Catálogo',
    // Prefixos específicos: /cadastros se divide entre Catálogo e
    // Configurações; o prefixo mais longo identifica a seção de cada rota.
    prefixos: [
      '/produtos', '/anuncios',
      '/cadastros/categoria', '/cadastros/tag',
      '/cadastros/unidade-medida', '/cadastros/uom-conversions',
    ],
    grupos: [
      {
        itens: [
          { name: 'Produtos', href: '/produtos', icon: Boxes, description: 'Catálogo de produtos e variações' },
          { name: 'Anúncios', href: '/anuncios', icon: Store, description: 'Publicações dos marketplaces e vínculo com produtos', permission: { a: 'produtos', I: 'ler' } },
          { name: 'Categorias', href: '/cadastros/categoria', icon: Tag, description: 'Classificação de produtos', adminOnly: true },
          { name: 'Tags', href: '/cadastros/tag', icon: Tag, description: 'Marcadores livres', adminOnly: true },
          { name: 'Unidades de Medida', href: '/cadastros/unidade-medida', icon: Scale, description: 'Unidades usadas na ficha técnica', adminOnly: true },
          { name: 'Conversões de Unidade', href: '/cadastros/uom-conversions', icon: Scale, description: 'Equivalência entre unidades', adminOnly: true },
        ],
      },
    ],
  },
  {
    id: 'configuracoes',
    titulo: 'Configurações',
    prefixos: [
      '/configuracoes', '/sistema', '/ferramentas', '/admin',
      '/cadastros/canal-venda', '/cadastros/plataforma',
      '/cadastros/fornecedor', '/cadastros/deposito', '/cadastros/ponto-coleta',
    ],
    grupos: [
      {
        nome: 'Geral',
        description: 'Acesso aos principais ajustes da aplicação.',
        itens: [
          { name: 'Visão geral', href: '/configuracoes', icon: Settings, adminOnly: true, exato: true },
        ],
      },
      {
        nome: 'Conexões e canais',
        description: 'Contas, integrações com marketplaces e canais de venda.',
        itens: [
          { name: 'Contas e integrações', href: '/configuracoes/integracoes', icon: Share2, description: 'Contas conectadas, configurações por conta e apps OAuth', adminOnly: true },
        ],
      },
      {
        nome: 'Operação',
        description: 'Regras de despacho, coleta, estoque e produção.',
        itens: [
          { name: 'Logística e despacho', href: '/configuracoes/janelas-despacho', icon: CalendarClock, description: 'Modalidades, identificadores, horário de corte e coleta', adminOnly: true },
          { name: 'Pontos de Coleta', href: '/cadastros/ponto-coleta', icon: MapPin, description: 'Onde entregar e a hora em que cada ponto fecha', adminOnly: true },
          { name: 'Depósitos', href: '/cadastros/deposito', icon: Building, description: 'Locais de armazenamento', adminOnly: true },
          { name: 'Fornecedores', href: '/cadastros/fornecedor', icon: Truck, description: 'Parceiros de suprimento', adminOnly: true },
          { name: 'Parâmetros de Produção', href: '/configuracoes/producao', icon: Settings, description: 'Categorias de estágio, depósito padrão', adminOnly: true },
        ],
      },
      {
        nome: 'Pessoas e acesso',
        description: 'Usuários, setores e permissões de acesso.',
        itens: [
          { name: 'Usuários', href: '/configuracoes/acessos/usuarios', icon: Users, description: 'Contas e vínculos de setor', adminOnly: true },
          { name: 'Setores', href: '/configuracoes/acessos/setores', icon: Building, description: 'Times e permissões da operação', adminOnly: true },
          { name: 'Acesso pendente', href: '/configuracoes/acessos/usuarios?status=pendente', icon: ShieldCheck, description: 'Regularizar contas sem autenticação', adminOnly: true },
        ],
      },
      {
        nome: 'IA',
        description: 'Modelo, comportamento e ferramentas de IA.',
        itens: [
          { name: 'Inteligência artificial', href: '/configuracoes/ia', icon: Sparkles, description: 'Configuração e operação da IA por conta', adminOnly: true },
        ],
      },
      {
        nome: 'Sistema e ferramentas',
        description: 'Agente local, tarefas automáticas e manutenção.',
        itens: [
          { name: 'Agente local', href: '/configuracoes/agente-local', icon: Download, description: 'Instalação do agente de impressão' },
        ],
      },
    ],
  },
  {
    id: 'monitoramento',
    titulo: 'Monitoramento',
    prefixos: ['/monitoramento/operacoes', '/relatorios', '/ai/logs'],
    grupos: [
      {
        itens: [
          { name: 'Minha atividade', href: '/monitoramento/operacoes/minha-atividade', icon: Activity, description: 'Seus processos e notificações' },
          { name: 'Visão geral', href: '/monitoramento/operacoes/visao-geral', icon: Monitor, description: 'Saúde das filas e dos workers', permission: { a: 'central_operacoes', I: 'ler' } },
          { name: 'Execuções', href: '/monitoramento/operacoes/execucoes', icon: Activity, description: 'Histórico de execução dos processos', permission: { a: 'central_operacoes', I: 'ler' } },
          { name: 'Filas', href: '/monitoramento/operacoes/filas', icon: Database, description: 'Filas de processamento', permission: { a: 'central_operacoes', I: 'ler' } },
          { name: 'Auditoria', href: '/monitoramento/operacoes/auditoria', icon: ScrollText, description: 'Eventos de usuários e do sistema', permission: { a: 'auditoria', I: 'ler' } },
          { name: 'Agendamentos', href: '/monitoramento/operacoes/agendamentos', icon: CalendarClock, description: 'Tarefas periódicas do worker', adminOnly: true },
          { name: 'Manutenção', href: '/monitoramento/operacoes/manutencao', icon: Settings, description: 'Ferramentas administrativas', adminOnly: true },
          { name: 'Dashboard', href: '/relatorios', icon: ScrollText, description: 'Página inicial de relatórios', exato: true },
          { name: 'Histórico Produção', href: '/relatorios/historico-producao', icon: Factory, description: 'Relatórios de histórico de produção', permission: { a: 'relatorios', I: 'ler' } },
          { name: 'Histórico Coletas', href: '/relatorios/historico-coletas', icon: Truck, description: 'Histórico de saídas e coletas', permission: { a: 'relatorios', I: 'ler' } },
          { name: 'Monitoramento de Estoque', href: '/relatorios/monitoramento-estoque', icon: Activity, description: 'Status de processos assíncronos', permission: { a: 'relatorios', I: 'ler' } },
          { name: 'Webhooks', href: '/relatorios/webhooks', icon: Database, description: 'Entregas e reprocessamento de eventos', adminOnly: true },
          { name: 'Histórico Gerencial', href: '/relatorios/gerencial-historico', icon: Factory, description: 'Consolidado gerencial por período', adminOnly: true },
          { name: 'Logs de IA', href: '/ai/logs', icon: Database, description: 'Execuções e erros de IA', adminOnly: true, exato: true },
        ],
      },
    ],
  },
  {
    id: 'estoque',
    titulo: 'Estoque',
    prefixos: ['/estoque'],
    grupos: [{ itens: [
      { name: 'Dashboard', href: '/estoque', icon: Activity, description: 'Resumo do estoque', exato: true, permission: { a: 'estoque', I: 'ler' } },
      { name: 'Divergências', href: '/estoque/divergencias', icon: AlertCircle, description: 'Saldo atual comparado ao último movimento', permission: { a: 'estoque', I: 'ler' } },
      { name: 'Movimentar', href: '/estoque/movimentar', icon: Package, description: 'Registrar movimentações', permission: { a: 'estoque', I: 'ler' } },
      { name: 'Movimentação em Lote', href: '/estoque/movimentacao-lote', icon: Boxes, description: 'Movimentar vários itens', permission: { a: 'estoque', I: 'ler' } },
      { name: 'Posição', href: '/estoque/posicao', icon: Warehouse, description: 'Consultar saldo atual', permission: { a: 'estoque', I: 'ler' } },
      { name: 'Histórico', href: '/estoque/historico', icon: ScrollText, description: 'Consultar movimentações', permission: { a: 'estoque', I: 'ler' } },
      { name: 'Reservas', href: '/estoque/reservas', icon: ClipboardList, description: 'Acompanhar reservas', permission: { a: 'estoque', I: 'ler' } },
      { name: 'Ajuste', href: '/estoque/ajuste', icon: Scale, description: 'Corrigir saldos', permission: { a: 'estoque', I: 'ler' } },
      { name: 'Relatórios', href: '/estoque/relatorios', icon: BarChart3, description: 'Análises de estoque', permission: { a: 'estoque', I: 'ler' } },
    ] }],
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Secao dona da rota, ou null. Vence o prefixo mais longo. */
export function secaoParaRota(pathname) {
  let melhor = null;
  let tamanho = -1;
  for (const secao of SECOES) {
    for (const prefixo of secao.prefixos) {
      const casa = pathname === prefixo || pathname.startsWith(prefixo + '/');
      if (casa && prefixo.length > tamanho) {
        melhor = secao;
        tamanho = prefixo.length;
      }
    }
  }
  return melhor;
}

/** Itens de uma secao achatados, na ordem de exibicao. */
export function itensDaSecao(secao) {
  if (!secao) return [];
  return secao.grupos.flatMap((g) => g.itens);
}

/** Todos os hrefs declarados, sem repeticao. Usado pelo verificador de rotas. */
export function coletarHrefs() {
  const hrefs = new Set();
  const andar = (itens) => {
    for (const item of itens || []) {
      if (item.href) hrefs.add(item.href);
      if (item.children) andar(item.children);
    }
  };
  andar(TOP_NAV);
  for (const secao of SECOES) andar(itensDaSecao(secao));
  return [...hrefs];
}

/**
 * Rotulos por segmento de URL, derivados dos proprios menus. Evita a lista
 * paralela que os breadcrumbs mantinham a mao e que ficou desatualizada.
 */
export function rotulosDeRota() {
  const rotulos = {};
  for (const href of coletarHrefs()) {
    const segmentos = href.split('/').filter(Boolean);
    if (!segmentos.length) continue;
    const ultimo = segmentos[segmentos.length - 1];
    if (rotulos[ultimo]) continue;
    const item =
      SECOES.flatMap(itensDaSecao).find((i) => i.href === href) ||
      (function achar(itens) {
        for (const i of itens || []) {
          if (i.href === href) return i;
          const achado = achar(i.children);
          if (achado) return achado;
        }
        return null;
      })(TOP_NAV);
    if (item) rotulos[ultimo] = item.name;
  }
  return rotulos;
}
