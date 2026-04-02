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
    description: 'Tela operacional para setores',
    color: 'text-amber-600',
    bgColor: 'bg-amber-50'
  },
  {
    name: 'Painel Geral',
    href: '/producao',
    icon: Trello,
    description: 'Kanban de produção por setor',
    color: 'text-blue-600',
    bgColor: 'bg-blue-50'
  },
  {
    name: 'Resumo Diário',
    href: '/producao/resumo',
    icon: BarChart3,
    description: 'Visão geral da produção do dia',
    color: 'text-purple-600',
    bgColor: 'bg-purple-50'
  },
  {
    name: 'Demandas',
    href: '/producao/demanda',
    icon: ClipboardList,
    description: 'Gerenciar ordens e demandas',
    color: 'text-green-600',
    bgColor: 'bg-green-50'
  },
  {
    name: 'Miolos',
    href: '/producao/miolos',
    icon: Layers,
    description: 'Controle de produção de miolos',
    color: 'text-orange-600',
    bgColor: 'bg-orange-50'
  },
  {
    name: 'Capas',
    href: '/producao/capas',
    icon: Layers,
    description: 'Controle de produção de capas',
    color: 'text-pink-600',
    bgColor: 'bg-pink-50'
  },
  {
    name: 'Expedição',
    href: '/producao/expedicao',
    icon: Package,
    description: 'Sincronia e retirada de itens',
    color: 'text-indigo-600',
    bgColor: 'bg-indigo-50'
  },
  {
    name: 'Impressão',
    href: '/producao/impressao',
    icon: Printer,
    description: 'Fila de impressão de artes',
    color: 'text-cyan-600',
    bgColor: 'bg-cyan-50'
  }
];

function ProducaoPage() {
  const location = useLocation();
  const { setLeftSidebarContent, setLeftSidebarMenuItems, setIsLeftSidebarOpen } = useLayout();

  useEffect(() => {
    // Reset sidebar to open state when entering production section
    setIsLeftSidebarOpen(true);

    const sidebarContent = (
      <div className="flex flex-col gap-4">
        <div className="px-3 py-3 border-b border-muted">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
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
                      "group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-all duration-200",
                      "hover:bg-muted hover:shadow-sm",
                      isActive
                        ? "bg-muted text-primary font-medium shadow-sm border border-muted-foreground/10"
                        : "text-muted-foreground"
                    )}
                  >
                    <div
                      className={cn(
                        "w-8 h-8 rounded-lg flex items-center justify-center transition-transform group-hover:scale-110",
                        isActive ? item.bgColor : "bg-muted/50",
                        "group-hover:" + item.bgColor
                      )}
                    >
                      <Icon className={cn("h-4 w-4 shrink-0", isActive ? item.color : "text-muted-foreground")} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="leading-tight font-medium truncate">{item.name}</div>
                      <div className="text-[10px] text-muted-foreground leading-tight truncate">{item.description}</div>
                    </div>
                    {isActive && (
                      <div className="w-1.5 h-1.5 rounded-full bg-primary shrink-0" />
                    )}
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
      // Only clear if we're actually leaving the producao section
      if (!location.pathname.startsWith('/producao')) {
        setLeftSidebarContent(null);
        setLeftSidebarMenuItems([]);
      }
    };
  }, [location.pathname, setLeftSidebarContent, setLeftSidebarMenuItems, setIsLeftSidebarOpen]);

  return (
    <div className="h-full">
      <Outlet />
    </div>
  );
}

export default ProducaoPage;
