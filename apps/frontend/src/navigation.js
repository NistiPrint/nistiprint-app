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
//   - useSecaoSidebar.js   -> SECOES, via secaoParaRota()
//   - Breadcrumbs.jsx      -> rotulosDeRota()
//   - scripts/verificar-rotas.mjs -> coletarHrefs()

import {
  Activity, BarChart3, Boxes, Building, CalendarClock, ClipboardList, Cog, Database, Factory,
  HardDrive, Home, Layers, MapPin, Monitor, Package, Printer, Scale, ScrollText,
  Settings, Share2, ShieldCheck, ShoppingCart, Sparkles, Store, Tag, TowerControl,
  Trello, Truck, Users, Warehouse, Waypoints, Wrench,
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
      { name: 'Consolidar', href: '/consolidar', type: 'link', permission: { a: 'vendas', I: 'ler' } },
    ],
  },
  {
    name: 'Produção',
    icon: Cog,
    type: 'collapsible',
    children: [
      { name: 'Produção', href: '/producao', type: 'link', permission: { a: 'producao', I: 'ler' } },
      { name: 'Fila de Impressão', href: '/producao/impressao', type: 'link', permission: { a: 'producao', I: 'ler' } },
      { name: 'Expedição', href: '/producao/expedicao', type: 'link', permission: { a: 'producao', I: 'ler' } },
    ],
  },
  {
    name: 'Estoque',
    icon: Warehouse,
    type: 'collapsible',
    permission: { a: 'estoque', I: 'ler' },
    children: [
      { name: 'Dashboard', href: '/estoque', icon: Activity, type: 'link' },
      { name: 'Movimentar', href: '/estoque/movimentar', type: 'link' },
      { name: 'Movimentação em Lote', href: '/estoque/movimentacao-lote', type: 'link' },
      { name: 'Posição', href: '/estoque/posicao', type: 'link' },
      { name: 'Histórico', href: '/estoque/historico', type: 'link' },
      { name: 'Reservas', href: '/estoque/reservas', type: 'link' },
      { name: 'Ajuste', href: '/estoque/ajuste', type: 'link' },
      { name: 'Relatórios', href: '/estoque/relatorios', type: 'link' },
    ],
  },
  {
    name: 'Catálogo',
    icon: Boxes,
    type: 'collapsible',
    children: [
      { name: 'Produtos', href: '/produtos', type: 'link', permission: { a: 'produtos', I: 'ler' } },
      { name: 'Categorias', href: '/cadastros/categoria', type: 'link', permission: { a: 'cadastros', I: 'ler' } },
      { name: 'Unidades de Medida', href: '/cadastros/unidade-medida', type: 'link', permission: { a: 'cadastros', I: 'ler' } },
    ],
  },
  {
    name: 'Monitoramento',
    icon: ScrollText,
    type: 'collapsible',
    children: [
      { name: 'Índice de Relatórios', href: '/relatorios', type: 'link', permission: { a: 'relatorios', I: 'ler' } },
      { name: 'Auditoria', href: '/relatorios/auditoria', type: 'link', adminOnly: true },
      { name: 'Histórico Gerencial', href: '/relatorios/gerencial-historico', type: 'link', adminOnly: true },
      { name: 'Webhooks', href: '/relatorios/webhooks', type: 'link', adminOnly: true },
      { name: 'Logs de IA', href: '/ai/logs', type: 'link', adminOnly: true },
    ],
  },
  {
    name: 'Configurações',
    icon: Settings,
    type: 'collapsible',
    children: [
      { name: 'Acesso e Permissões', href: '/sistema', icon: Users, type: 'link', adminOnly: true },
      { name: 'Parâmetros de Produção', href: '/configuracoes/producao', icon: Settings, type: 'link', permission: { a: 'configuracoes', I: 'ler' } },
      {
        name: 'Utilitários',
        icon: Wrench,
        type: 'sub-collapsible',
        adminOnly: true,
        children: [
          { name: 'Central de Tarefas', href: '/admin/utilitarios/tasks', icon: HardDrive, type: 'link', adminOnly: true },
          { name: 'Ferramentas', href: '/ferramentas', icon: Wrench, type: 'link', adminOnly: true },
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
  {
    // A Torre de Despacho mora aqui, e nao em Producao: ela e o passo em que o
    // operador AGRUPA PEDIDOS. A demanda de producao e o que sai dela, nao o
    // que entra. Enquanto ficou sob Producao, o unico caminho ate o
    // agrupamento passava por um menu que descreve o galpao — e quem trabalha
    // com pedidos nao procurava ali.
    id: 'pedidos',
    titulo: 'Operação: Pedidos',
    prefixos: ['/vendas', '/despacho', '/consolidar'],
    grupos: [
      {
        itens: [
          { name: 'Pedidos', href: '/vendas/pedidos', icon: ClipboardList, description: 'Gestão unificada de pedidos' },
          { name: 'Torre de Despacho', href: '/despacho', icon: TowerControl, description: 'Agrupar pedidos e publicar a demanda', exato: true },
          { name: 'Personalizados', href: '/vendas/personalizadas', icon: Users, description: 'Vendas de produtos personalizados' },
          { name: 'Consolidar', href: '/consolidar', icon: Layers, description: 'Conferir uma planilha do marketplace contra a base' },
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
          { name: 'Painel Geral', href: '/producao', icon: Trello, description: 'Kanban de produção por setor', adminOnly: true, exato: true },
          { name: 'Resumo Diário', href: '/producao/resumo', icon: BarChart3, description: 'Visão geral da produção do dia', adminOnly: true },
          { name: 'Demandas', href: '/producao/demanda', icon: ClipboardList, description: 'Acompanhar as demandas publicadas' },
          { name: 'Miolos', href: '/producao/miolos', icon: Layers, description: 'Controle de produção de miolos' },
          { name: 'Capas', href: '/producao/capas', icon: Layers, description: 'Controle de produção de capas' },
          { name: 'Expedição', href: '/producao/expedicao', icon: Package, description: 'Sincronia e retirada de itens' },
          { name: 'Impressão', href: '/producao/impressao', icon: Printer, description: 'Fila de impressão de artes' },
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
    // Prefixos especificos de proposito: /cadastros se divide entre Catalogo e
    // Configuracoes, e secaoParaRota resolve pelo prefixo mais longo.
    // /produtos fica de fora porque ProdutoFormPage monta a propria lateral.
    prefixos: [
      '/cadastros/categoria', '/cadastros/tag',
      '/cadastros/unidade-medida', '/cadastros/uom-conversions',
    ],
    grupos: [
      {
        itens: [
          { name: 'Produtos', href: '/produtos', icon: Boxes, description: 'Catálogo de produtos e variações' },
          { name: 'Categorias', href: '/cadastros/categoria', icon: Tag, description: 'Classificação de produtos' },
          { name: 'Tags', href: '/cadastros/tag', icon: Tag, description: 'Marcadores livres' },
          { name: 'Unidades de Medida', href: '/cadastros/unidade-medida', icon: Scale, description: 'Unidades usadas na ficha técnica' },
          { name: 'Conversões de Unidade', href: '/cadastros/uom-conversions', icon: Scale, description: 'Equivalência entre unidades' },
        ],
      },
    ],
  },
  {
    // U3: Configuracoes absorve Sistema e a parte de Cadastros Base que era
    // configuracao, em sete blocos. Nenhuma rota mudou — so o agrupamento.
    id: 'configuracoes',
    titulo: 'Configurações',
    prefixos: [
      '/configuracoes', '/sistema', '/ferramentas', '/admin',
      '/cadastros/canal-venda', '/cadastros/plataforma',
      '/cadastros/fornecedor', '/cadastros/deposito', '/cadastros/ponto-coleta',
    ],
    grupos: [
      {
        nome: 'Conexões',
        itens: [
          { name: 'Hub de Integrações', href: '/configuracoes/integracoes', icon: Share2, description: 'Contas conectadas, marketplaces e apps OAuth' },
          { name: 'Roteamento de Contas', href: '/configuracoes/roteamento', icon: Waypoints, description: 'Qual conta ERP atende cada marketplace' },
        ],
      },
      {
        nome: 'Logística e Despacho',
        itens: [
          // O horário de corte é a regra que decide qual pedido entra em qual
          // lote — cadastro de rotina do galpão. Ficava numa aba dentro do hub
          // de integrações, onde ninguém procuraria por ele.
          { name: 'Janelas de Despacho', href: '/configuracoes/janelas-despacho', icon: CalendarClock, description: 'Horário de corte, coleta e canais de cada lote' },
          { name: 'Pontos de Coleta', href: '/cadastros/ponto-coleta', icon: MapPin, description: 'Onde entregar e a hora em que cada ponto fecha' },
          { name: 'Canais de Venda', href: '/cadastros/canal-venda', icon: Store, description: 'Derivado das integrações instaladas' },
          { name: 'Plataformas', href: '/cadastros/plataforma', icon: Share2, description: 'Marketplaces disponíveis' },
        ],
      },
      {
        nome: 'Armazém',
        itens: [
          { name: 'Depósitos', href: '/cadastros/deposito', icon: Building, description: 'Locais de armazenamento' },
          { name: 'Fornecedores', href: '/cadastros/fornecedor', icon: Truck, description: 'Parceiros de suprimento' },
        ],
      },
      {
        nome: 'Produção',
        itens: [
          { name: 'Parâmetros de Produção', href: '/configuracoes/producao', icon: Settings, description: 'Categorias de estágio, depósito padrão' },
          { name: 'Permissões de Demanda', href: '/configuracoes/demanda-permissions', icon: ShieldCheck, description: 'Quem acessa o dashboard' },
        ],
      },
      {
        nome: 'Inteligência Artificial',
        itens: [
          { name: 'Configuração da IA', href: '/configuracoes/ia', icon: Sparkles, description: 'Modelo, prompts e parâmetros' },
          { name: 'Ferramentas de IA', href: '/ferramentas/ia', icon: Sparkles, description: 'Execução e testes assistidos' },
        ],
      },
      {
        nome: 'ERP',
        itens: [
          { name: 'Padrões Bling', href: '/configuracoes/bling', icon: Waypoints, description: 'Regras de negócio e mapeamentos' },
        ],
      },
      {
        nome: 'Acesso',
        itens: [
          { name: 'Usuários', href: '/sistema/usuarios', icon: Users, description: 'Contas e vínculos de setor' },
          { name: 'Setores', href: '/sistema/setores', icon: Building, description: 'Times da operação' },
        ],
      },
      {
        nome: 'Utilitários',
        itens: [
          { name: 'Central de Tarefas', href: '/admin/utilitarios/tasks', icon: HardDrive, description: 'Agendamentos e execuções' },
          { name: 'Ferramentas', href: '/ferramentas', icon: Wrench, description: 'Manutenção e reprocessamento' },
        ],
      },
    ],
  },
  {
    id: 'monitoramento',
    titulo: 'Monitoramento',
    prefixos: ['/relatorios'],
    grupos: [
      {
        itens: [
          { name: 'Dashboard', href: '/relatorios', icon: ScrollText, description: 'Página inicial de relatórios', exato: true },
          { name: 'Histórico Produção', href: '/relatorios/historico-producao', icon: Factory, description: 'Relatórios de histórico de produção' },
          { name: 'Histórico Coletas', href: '/relatorios/historico-coletas', icon: Truck, description: 'Histórico de saídas e coletas' },
          { name: 'Monitoramento de Estoque', href: '/relatorios/monitoramento-estoque', icon: Activity, description: 'Status de processos assíncronos' },
          { name: 'Webhooks', href: '/relatorios/webhooks', icon: Database, description: 'Entregas e reprocessamento de eventos' },
          { name: 'Auditoria', href: '/relatorios/auditoria', icon: Monitor, description: 'Relatórios de auditoria do sistema' },
          { name: 'Histórico Gerencial', href: '/relatorios/gerencial-historico', icon: Factory, description: 'Consolidado gerencial por período' },
        ],
      },
    ],
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
