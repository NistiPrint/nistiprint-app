// Import removed - using static URL instead
import { NotificationManager } from '@/components/NotificationManager';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuPortal,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useAuth } from '@/contexts/AuthContext';
import { cn } from '@/lib/utils';
import {
  Boxes,
  ChevronDown,
  Cog,
  Home,
  LayoutDashboard,
  LogOut,
  Menu,
  ScrollText,
  Settings,
  User,
  Users,
  Warehouse,
  Wrench
} from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';

const navigation = [
  {
    name: 'Home',
    href: '/',
    icon: Home,
    type: 'link'
  },
  {
    name: 'Produtos',
    href: '/produtos',
    icon: Boxes,
    type: 'link',
    permission: { a: 'produtos', I: 'ler' }
  },
  {
    name: 'Operação',
    icon: Cog,
    type: 'collapsible',
    children: [
      {
        name: 'Produção',
        href: '/producao',
        type: 'link',
        permission: { a: 'producao', I: 'ler' }
      },
      {
        name: 'Vendas',
        href: '/vendas/personalizadas',
        type: 'link',
        permission: { a: 'vendas', I: 'ler' }
      },
    ]
  },
  {
    name: 'Estoque',
    icon: Warehouse,
    type: 'collapsible',
    permission: { a: 'estoque', I: 'ler' },
    children: [
      { name: 'Dashboard', href: '/estoque', icon: LayoutDashboard, type: 'link' },
      { name: 'Movimentar', href: '/estoque/movimentar', type: 'link' },
      { name: 'Posição', href: '/estoque/posicao', type: 'link' },
      { name: 'Histórico', href: '/estoque/historico', type: 'link' },
      { name: 'Reservas', href: '/estoque/reservas', type: 'link' },
      { name: 'Ajuste', href: '/estoque/ajuste', type: 'link' },
      { name: 'Relatórios', href: '/estoque/relatorios', type: 'link' },
    ]
  },
  {
    name: 'Administração',
    icon: Wrench,
    type: 'collapsible',
    children: [
      {
        name: 'Cadastros',
        href: '/cadastros',
        icon: Boxes,
        type: 'link',
        permission: { a: 'cadastros', I: 'ler' }
      },
      {
        name: 'Controle de Acesso',
        href: '/sistema',
        icon: Users,
        type: 'link',
        adminOnly: true
      },
      {
        name: 'Configurações',
        href: '/configuracoes/producao',
        icon: Settings,
        type: 'link',
        permission: { a: 'configuracoes', I: 'ler' }
      },
      { name: 'Relatórios', href: '/relatorios', icon: ScrollText, type: 'link', permission: { a: 'relatorios', I: 'ler' } },
      { name: 'Utilitários', href: '/ferramentas', icon: Wrench, type: 'link', adminOnly: true },
    ]
  },
];

function Header() {
  const { user, logout, isAdmin, hasPermission } = useAuth();
  const location = useLocation();

  const handleLogout = async () => {
    try {
      await logout();
    } catch (error) {
      console.error('Erro ao fazer logout:', error);
    }
  };

  const checkItemVisibility = (item) => {
    if (item.adminOnly && !isAdmin()) return false;
    if (item.permission && !hasPermission(item.permission.a, item.permission.I)) return false;

    if (item.children) {
      return item.children.some(child => checkItemVisibility(child));
    }
    return true;
  };

  const checkIsActive = (item) => {
    if (item.href && location.pathname === item.href) return true;
    if (item.children) {
      return item.children.some(child => checkIsActive(child));
    }
    return false;
  };

  const renderNavItems = (items) => {
    return items
      .filter(checkItemVisibility)
      .map((item, index) => {
        const Icon = item.icon;
        const isActive = checkIsActive(item);

        if (item.type === 'link') {
          return (
            <Link
              key={item.name + index}
              to={item.href}
              className={cn(
                "flex items-center gap-2 text-sm font-medium transition-all duration-200 hover:text-primary whitespace-nowrap px-3 py-1.5 rounded-lg",
                "hover:bg-muted/50",
                isActive
                  ? "text-primary bg-muted/80 shadow-sm"
                  : "text-muted-foreground",
                item.disabled && "opacity-50 pointer-events-none"
              )}
            >
              {Icon && <Icon className="h-4 w-4" />}
              {item.name}
              {item.disabled && (
                <span className="text-[10px] bg-orange-100 text-orange-800 px-1.5 py-0.5 rounded-full ml-1 font-medium">
                  breve
                </span>
              )}
            </Link>
          );
        }

        if (item.type === 'collapsible' || item.type === 'sub-collapsible') {
          return (
            <DropdownMenu key={item.name + index}>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className={cn(
                    "flex items-center gap-1.5 h-auto py-1.5 px-3 text-sm font-medium transition-all duration-200 hover:bg-muted/50 rounded-lg",
                    isActive
                      ? "text-primary bg-muted/80 shadow-sm"
                      : "text-muted-foreground"
                  )}
                >
                  {Icon && <Icon className="h-4 w-4 mr-0.5" />}
                  {item.name}
                  <ChevronDown
                    className={cn(
                      "h-3.5 w-3.5 opacity-60 transition-transform duration-200",
                      isActive && "rotate-180"
                    )}
                  />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-56 shadow-lg">
                {renderDropdownItems(item.children)}
              </DropdownMenuContent>
            </DropdownMenu>
          );
        }
        return null;
      });
  };

  const renderDropdownItems = (items) => {
    return items
      .filter(checkItemVisibility)
      .map((item, index) => {
        const Icon = item.icon;

        if (item.type === 'sub-collapsible') {
          return (
            <DropdownMenuSub key={item.name + index}>
              <DropdownMenuSubTrigger className="flex items-center gap-2">
                {Icon && <Icon className="h-4 w-4" />}
                <span>{item.name}</span>
              </DropdownMenuSubTrigger>
              <DropdownMenuPortal>
                <DropdownMenuSubContent className="w-48 shadow-lg">
                  {renderDropdownItems(item.children)}
                </DropdownMenuSubContent>
              </DropdownMenuPortal>
            </DropdownMenuSub>
          );
        }

        return (
          <DropdownMenuItem
            key={item.name + index}
            asChild
            disabled={item.disabled}
            className="cursor-pointer"
          >
            <Link to={item.href} className="flex items-center gap-2 w-full">
              {Icon && <Icon className="h-4 w-4" />}
              <span>{item.name}</span>
              {item.disabled && (
                <span className="ml-auto text-[10px] bg-orange-100 text-orange-800 px-1.5 py-0.5 rounded-full font-medium">
                  breve
                </span>
              )}
            </Link>
          </DropdownMenuItem>
        );
      });
  };

  return (
    <header className="sticky top-0 z-50 flex h-16 items-center gap-4 border-b bg-background/80 backdrop-blur-xl px-4 md:px-6 shadow-sm">
      <div className="flex items-center gap-4">
        <Link
          to="/"
          className="flex items-center gap-2 font-semibold text-primary mr-4 transition-opacity hover:opacity-80"
        >
          <img
            src="/logomarca.png"
            alt="Logo"
            className="h-10 w-44 object-contain"
          />
        </Link>

        <nav className="hidden md:flex items-center gap-1 lg:gap-1.5">
          {renderNavItems(navigation)}
        </nav>
      </div>

      {/* Mobile Menu Toggle */}
      <div className="flex items-center gap-2 md:hidden">
        <Button variant="ghost" size="icon" className="h-9 w-9 rounded-lg">
          <Menu className="h-5 w-5" />
        </Button>
      </div>

      <div className="ml-auto flex items-center gap-2 lg:gap-3">
        <NotificationManager />

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              className="relative h-9 w-9 rounded-full transition-all hover:bg-muted/80"
            >
              <Avatar className="h-9 w-9 border shadow-sm">
                <AvatarImage src={user?.avatar_url} alt={user?.nome} />
                <AvatarFallback className="bg-primary/10 text-primary text-sm font-semibold">
                  {user?.nome
                    ? user.nome
                        .split(' ')
                        .map((n) => n[0])
                        .join('')
                        .toUpperCase()
                    : 'U'}
                </AvatarFallback>
              </Avatar>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-56 shadow-lg"
            align="end"
            forceMount
          >
            <DropdownMenuLabel className="font-normal">
              <div className="flex flex-col space-y-1.5">
                <p className="text-sm font-semibold leading-none">
                  {user?.nome}
                </p>
                <p className="text-xs leading-none text-muted-foreground">
                  {user?.email}
                </p>
                <p className="text-[10px] text-muted-foreground uppercase font-bold tracking-wider mt-1.5 bg-muted/50 inline-block px-2 py-0.5 rounded w-fit">
                  {user?.setor_nome || 'Sem Setor'}
                </p>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link
                to="/perfil"
                className="flex items-center w-full cursor-pointer"
              >
                <User className="mr-2 h-4 w-4" />
                <span>Perfil</span>
              </Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={handleLogout}
              className="text-destructive focus:text-destructive cursor-pointer"
            >
              <LogOut className="mr-2 h-4 w-4" />
              <span>Sair</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}

export default Header;
