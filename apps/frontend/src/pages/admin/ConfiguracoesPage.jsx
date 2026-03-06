import { useLayout } from '@/contexts/LayoutContext';
import { cn } from '@/lib/utils';
import { Activity, Globe, Key, Settings, Share2, ShieldCheck, Waypoints } from 'lucide-react';
import { useEffect } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';

const configuracoesMenu = [
  {
    name: 'Parâmetros Gerais',
    type: 'sub-collapsible',
    children: [
      {
        name: 'Parâmetros de Produção',
        href: '/configuracoes/producao',
        icon: Settings,
        description: 'Configurar parâmetros de produção'
      },
    ]
  },
  {
    name: 'Integrações',
    type: 'sub-collapsible',
    children: [
      {
        name: 'Hub de Integrações',
        href: '/configuracoes/integracoes',
        icon: Share2,
        description: 'Status, Marketplace e Webhooks'
      },
      {
        name: 'Padrões Bling',
        href: '/configuracoes/bling',
        icon: Waypoints,
        description: 'Regras de negócio e mapeamentos'
      },
    ]
  },
];

function ConfiguracoesPage() {
  const location = useLocation();
  const { setLeftSidebarContent, setLeftSidebarMenuItems } = useLayout();

  const renderMenuItems = (items) => {
    return items.map((item, index) => {
      if (item.type === 'sub-collapsible') {
        const isActive = item.children.some(child => location.pathname.startsWith(child.href));
        return (
          <li key={item.name + index}>
            <div className="mb-4">
              <div className={cn(
                "px-3 py-2 text-sm font-medium text-muted-foreground uppercase tracking-wider",
                isActive && "text-primary"
              )}>
                {item.name}
              </div>
              <ul className="grid gap-1 pl-4 py-2 text-sm">
                {renderMenuItems(item.children)}
              </ul>
            </div>
          </li>
        );
      } else {
        const Icon = item.icon;
        const isActive = location.pathname.startsWith(item.href);
        return (
          <li key={item.name}>
            <Link
              to={item.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-all hover:bg-muted",
                isActive && "bg-muted text-primary font-medium"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <div>
                <div className="leading-tight">{item.name}</div>
                <div className="text-[10px] text-muted-foreground leading-tight">{item.description}</div>
              </div>
            </Link>
          </li>
        );
      }
    });
  };

  // Extrair os itens do menu para exibir quando a sidebar estiver recolhida
  const extractMenuItems = (menuItems) => {
    const items = [];
    menuItems.forEach(item => {
      if (item.children) {
        items.push(...extractMenuItems(item.children));
      } else {
        items.push(item);
      }
    });
    return items;
  };

  useEffect(() => {
    const sidebarContent = (
      <div className="flex flex-col gap-4">
        <div className="px-3 py-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/70">
            Configurações
          </h2>
        </div>
        <nav className="space-y-1">
          <ul className="space-y-1">
            {renderMenuItems(configuracoesMenu)}
          </ul>
        </nav>
      </div>
    );

    setLeftSidebarContent(sidebarContent);
    setLeftSidebarMenuItems(extractMenuItems(configuracoesMenu));

    // Só limpa se estiver saindo da seção de configurações
    return () => {
      if (!window.location.pathname.startsWith('/configuracoes') && !window.location.pathname.startsWith('/marketplace')) {
        setLeftSidebarContent(null);
        setLeftSidebarMenuItems([]);
      }
    };
  }, [location.pathname]);

  return (
    <div className="p-6">
      <Outlet />
    </div>
  );
}

export default ConfiguracoesPage;
