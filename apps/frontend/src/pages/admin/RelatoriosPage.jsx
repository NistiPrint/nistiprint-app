import { useLayout } from '@/contexts/LayoutContext';
import { cn } from '@/lib/utils';
import { Activity, Database, Factory, Monitor, ScrollText, Truck } from 'lucide-react';
import { useEffect } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';

const relatoriosMenu = [
  {
    name: 'Dashboard',
    href: '/relatorios',
    icon: ScrollText,
    description: 'Página inicial de relatórios'
  },
  {
    name: 'Histórico Produção',
    href: '/relatorios/historico-producao',
    icon: Factory,
    description: 'Relatórios de histórico de produção'
  },
  {
    name: 'Histórico Coletas',
    href: '/relatorios/historico-coletas',
    icon: Truck,
    description: 'Histórico de saídas e coletas'
  },
  {
    name: 'Monitoramento',
    href: '/relatorios/monitoramento',
    icon: Activity,
    description: 'Status de processos assíncronos'
  },
  {
    name: 'Auditoria',
    href: '/relatorios/auditoria',
    icon: Monitor,
    description: 'Relatórios de auditoria do sistema'
  },
];

function RelatoriosPage() {
  const location = useLocation();
  const { setLeftSidebarContent, setLeftSidebarMenuItems } = useLayout();

  useEffect(() => {
    const sidebarContent = (
      <div className="flex flex-col gap-4">
        <div className="px-3 py-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/70">
            Relatórios
          </h2>
        </div>
        <nav className="space-y-1">
          <ul className="space-y-1">
            {relatoriosMenu.map((item) => {
              const Icon = item.icon;
              // Special case for dashboard to avoid matching all subroutes incorrectly
              const isActive = item.href === '/relatorios'
                ? location.pathname === '/relatorios'
                : location.pathname.startsWith(item.href);

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
            })}
          </ul>
        </nav>
      </div>
    );

    setLeftSidebarContent(sidebarContent);
    setLeftSidebarMenuItems(relatoriosMenu);

    return () => {
      setLeftSidebarContent(null);
      setLeftSidebarMenuItems([]);
    };
  }, [location.pathname]);

  return (
    <div className="p-6">
      <Outlet />
    </div>
  );
}

export default RelatoriosPage;