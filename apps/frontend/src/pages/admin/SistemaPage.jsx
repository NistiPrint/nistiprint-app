import { Button } from '@/components/ui/button';
import { useLayout } from '@/contexts/LayoutContext';
import { cn } from '@/lib/utils';
import { Building, ShieldCheck, Monitor, Users } from 'lucide-react';
import { useEffect } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';

const sistemaMenu = [
  {
    name: 'Usuários & Times',
    type: 'sub-collapsible',
    children: [
      {
        name: 'Usuários',
        href: '/sistema/usuarios',
        icon: Users,
        description: 'Gerenciar usuários do sistema'
      },
      {
        name: 'Setores',
        href: '/sistema/setores',
        icon: Building,
        description: 'Gerenciar setores da organização'
      },
    ]
  },
  {
    name: 'Permissões Específicas',
    type: 'sub-collapsible',
    children: [
      {
        name: 'Permissões de Demanda',
        href: '/configuracoes/demanda-permissions',
        icon: ShieldCheck,
        description: 'Gerenciar acessos ao dashboard'
      },
    ]
  },
  {
    name: 'Segurança & Logs',
    type: 'sub-collapsible',
    children: [
      {
        name: 'Auditoria',
        href: '/relatorios/auditoria',
        icon: Monitor,
        description: 'Relatórios de auditoria do sistema'
      },
    ]
  },
];

function SistemaPage() {
  const location = useLocation();
  const { setLeftSidebarContent, setLeftSidebarMenuItems, setIsLeftSidebarOpen } = useLayout();

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
    setIsLeftSidebarOpen(true);
    
    const sidebarContent = (
      <div className="flex flex-col gap-4">
        <div className="px-3 py-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/70">
            Controle de Acesso
          </h2>
        </div>
        <nav className="space-y-1">
          <ul className="space-y-1">
            {renderMenuItems(sistemaMenu)}
          </ul>
        </nav>
      </div>
    );

    setLeftSidebarContent(sidebarContent);
    setLeftSidebarMenuItems(extractMenuItems(sistemaMenu));

    return () => {
      if (!location.pathname.startsWith('/sistema')) {
        setLeftSidebarContent(null);
        setLeftSidebarMenuItems([]);
      }
    };
  }, [location.pathname, setLeftSidebarContent, setLeftSidebarMenuItems, setIsLeftSidebarOpen]);

  return (
    <div className="p-6">
      <Outlet />
    </div>
  );
}

export default SistemaPage;