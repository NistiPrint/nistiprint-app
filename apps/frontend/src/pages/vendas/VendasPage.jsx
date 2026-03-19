import { useLayout } from '@/contexts/LayoutContext';
import { cn } from '@/lib/utils';
import { ShoppingBag, Users, FileText, Brain, Globe, PackageCheck } from 'lucide-react';
import { useEffect } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';

const vendasMenu = [
  {
    name: 'Personalizadas',
    href: '/vendas/personalizadas',
    icon: Users,
    description: 'Vendas de produtos personalizados'
  },
  {
    name: 'Identificação IA',
    href: '/vendas/identificacao-ia',
    icon: Brain,
    description: 'Extração automática de nomes via IA'
  },
  {
    name: 'Marketplaces',
    href: '/vendas/marketplaces',
    icon: Globe,
    description: 'Pedidos de diferentes plataformas'
  },
  {
    name: 'Pedidos Unificados',
    href: '/vendas/unified-orders',
    icon: PackageCheck,
    description: 'Gestão centralizada de pedidos'
  },
  {
    name: 'Consolidar',
    href: '/consolidar',
    icon: FileText,
    description: 'Consolidação de pedidos para produção'
  }
];

function VendasPage() {
  const location = useLocation();
  const { setLeftSidebarContent, setLeftSidebarMenuItems, setIsLeftSidebarOpen } = useLayout();

  useEffect(() => {
    // Reset sidebar to open state when entering sales section
    setIsLeftSidebarOpen(true);

    const sidebarContent = (
      <div className="flex flex-col gap-4">
        <div className="px-3 py-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/70">
            Operação: Vendas
          </h2>
        </div>
        <nav className="space-y-1">
          <ul className="space-y-1">
            {vendasMenu.map((item) => {
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
            })}
          </ul>
        </nav>
      </div>
    );

    setLeftSidebarContent(sidebarContent);
    setLeftSidebarMenuItems(vendasMenu);

    return () => {
      if (!window.location.pathname.startsWith('/vendas') && !window.location.pathname.startsWith('/consolidar')) {
        setLeftSidebarContent(null);
        setLeftSidebarMenuItems([]);
      }
    };
  }, [location.pathname, setLeftSidebarContent, setLeftSidebarMenuItems]);

  return (
    <div className="h-full">
      <Outlet />
    </div>
  );
}

export default VendasPage;
