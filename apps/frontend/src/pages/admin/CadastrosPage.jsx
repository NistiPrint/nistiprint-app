import { useLayout } from '@/contexts/LayoutContext';
import { cn } from '@/lib/utils';
import { Building, MapPin, Scale, Share2, Store, Tag, Truck } from 'lucide-react';
import { useEffect } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';

const cadastrosMenu = [
  {
    name: 'Produtos & Materiais',
    type: 'sub-collapsible',
    children: [
      {
        name: 'Categorias',
        href: '/cadastros/categoria',
        icon: Tag,
        description: 'Gerenciar categorias de produtos'
      },
      {
        name: 'Tags',
        href: '/cadastros/tag',
        icon: Tag,
        description: 'Gerenciar tags para classificação'
      },
      {
        name: 'Unidades de Medida',
        href: '/cadastros/unidade-medida',
        icon: Scale,
        description: 'Gerenciar unidades de medida'
      },
      {
        name: 'Conversões de Unidade',
        href: '/cadastros/uom-conversions',
        icon: Scale,
        description: 'Gerenciar conversões entre unidades'
      },
    ]
  },
  {
    name: 'Comercial',
    type: 'sub-collapsible',
    children: [
      {
        name: 'Canais de Venda',
        href: '/cadastros/canal-venda',
        icon: Store,
        description: 'Gerenciar canais de venda'
      },
      {
        name: 'Plataformas',
        href: '/cadastros/plataforma',
        icon: Share2,
        description: 'Gerenciar plataformas de integração'
      },
    ]
  },
  {
    name: 'Logística & Parceiros',
    type: 'sub-collapsible',
    children: [
      {
        name: 'Fornecedores',
        href: '/cadastros/fornecedor',
        icon: Truck,
        description: 'Gerenciar fornecedores'
      },
      {
        name: 'Depósitos',
        href: '/cadastros/deposito',
        icon: Building,
        description: 'Gerenciar depósitos e locais de armazenamento'
      },
      {
        name: 'Pontos de Coleta',
        href: '/cadastros/ponto-coleta',
        icon: MapPin,
        description: 'Gerenciar pontos de coleta e despacho'
      },
    ]
  },
];

function CadastrosPage() {
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
        const isDisabled = item.disabled;

        return (
          <li key={item.name}>
            <Link
              to={isDisabled ? "#" : item.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-all hover:bg-muted",
                isActive && "bg-muted text-primary font-medium",
                isDisabled && "opacity-50 cursor-not-allowed hover:bg-transparent"
              )}
              onClick={(e) => isDisabled && e.preventDefault()}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <div>
                <div className="leading-tight flex items-center gap-2">
                  {item.name}
                  {isDisabled && <span className="text-[8px] bg-orange-100 text-orange-800 px-1 rounded uppercase">breve</span>}
                </div>
                <div className="text-[10px] text-muted-foreground leading-tight">{item.description}</div>
              </div>
            </Link>
          </li>
        );
      }
    });
  };

  useEffect(() => {
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

    const sidebarContent = (
      <div className="flex flex-col gap-4">
        <div className="px-3 py-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/70">
            Cadastros
          </h2>
        </div>
        <nav className="space-y-1">
          <ul className="space-y-1">
            {renderMenuItems(cadastrosMenu)}
          </ul>
        </nav>
      </div>
    );

    setLeftSidebarContent(sidebarContent);
    setLeftSidebarMenuItems(extractMenuItems(cadastrosMenu));

    return () => {
      if (!window.location.pathname.startsWith('/cadastros')) {
        setLeftSidebarContent(null);
        setLeftSidebarMenuItems([]);
      }
    };
  }, [location.pathname]); // Re-renderiza para atualizar o estado de 'isActive'

  return (
    <div className="p-6">
      <Outlet />
    </div>
  );
}

export default CadastrosPage;
