import { useLayout } from '@/contexts/LayoutContext';
import { cn } from '@/lib/utils';
import {
  BarChart3,
  ClipboardList,
  Layers,
  Package,
  Printer,
  Trello,
  Zap
} from 'lucide-react';
import { useEffect } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';

const producaoMenu = [
  {
    name: 'Modo Foco (KDS)',
    href: '/producao/foco',
    icon: Zap,
    description: 'Tela operacional para setores'
  },
  {
    name: 'Painel Geral',
    href: '/producao',
    icon: Trello,
    description: 'Kanban de produção por setor'
  },
  {
    name: 'Resumo Diário',
    href: '/producao/resumo',
    icon: BarChart3,
    description: 'Visão geral da produção do dia'
  },
  {
    name: 'Demandas',
    href: '/producao/demanda',
    icon: ClipboardList,
    description: 'Gerenciar ordens e demandas'
  },
  {
    name: 'Miolos',
    href: '/producao/miolos',
    icon: Layers,
    description: 'Controle de produção de miolos'
  },
  {
    name: 'Capas',
    href: '/producao/capas',
    icon: Layers,
    description: 'Controle de produção de capas'
  },
  {
    name: 'Expedição',
    href: '/producao/expedicao',
    icon: Package,
    description: 'Sincronia e retirada de itens'
  },
  {
    name: 'Impressão',
    href: '/producao/impressao',
    icon: Printer,
    description: 'Fila de impressão de artes'
  }
];

function ProducaoPage() {
  const location = useLocation();
  const { setLeftSidebarContent, setLeftSidebarMenuItems, setIsLeftSidebarOpen } = useLayout();

  useEffect(() => {
    // Reset sidebar to open state when entering production section
    // Specific sub-pages (like DemandaListPage) can then decide to close it
    setIsLeftSidebarOpen(true);

    const sidebarContent = (
      <div className="flex flex-col gap-4">
        <div className="px-3 py-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/70">
            Operação: Produção
          </h2>
        </div>
        <nav className="space-y-1">
          <ul className="space-y-1">
            {producaoMenu.map((item) => {
              const Icon = item.icon;
              const isActive = item.href === '/producao'
                ? location.pathname === '/producao'
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
    setLeftSidebarMenuItems(producaoMenu);

    return () => {
      if (!window.location.pathname.startsWith('/producao')) {
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

export default ProducaoPage;