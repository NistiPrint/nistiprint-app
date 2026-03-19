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
                "flex items-center gap-2 text-sm font-medium transition-colors hover:text-primary whitespace-nowrap px-2 py-1 rounded-md",
                isActive ? "text-primary bg-muted" : "text-muted-foreground",
                item.disabled && "opacity-50 pointer-events-none"
              )}
            >
              {Icon && <Icon className="h-4 w-4" />}
              {item.name}
              {item.disabled && <span className="text-[10px] bg-orange-100 text-orange-800 px-1 rounded ml-1">breve</span>}
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
                    "flex items-center gap-1 h-auto py-1 px-2 text-sm font-medium transition-colors hover:text-primary",
                    isActive ? "text-primary bg-muted" : "text-muted-foreground"
                  )}
                >
                  {Icon && <Icon className="h-4 w-4 mr-1" />}
                  {item.name}
                  <ChevronDown className="h-3 w-3 opacity-50" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-56">
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
                <DropdownMenuSubContent className="w-48">
                  {renderDropdownItems(item.children)}
                </DropdownMenuSubContent>
              </DropdownMenuPortal>
            </DropdownMenuSub>
          );
        }

        return (
          <DropdownMenuItem key={item.name + index} asChild disabled={item.disabled}>
            <Link to={item.href} className="flex items-center gap-2 w-full cursor-pointer">
              {Icon && <Icon className="h-4 w-4" />}
              <span>{item.name}</span>
              {item.disabled && <span className="ml-auto text-[10px] bg-orange-100 text-orange-800 px-1 rounded">breve</span>}
            </Link>
          </DropdownMenuItem>
        );
      });
  };

  return (
    <header className="sticky top-0 z-50 flex h-14 items-center gap-4 border-b bg-background/95 backdrop-blur px-4 md:px-6 shadow-sm">
      <div className="flex items-center gap-4">
        <Link to="/" className="flex items-center gap-2 font-semibold text-primary mr-4">
          <img src="/logomarca.png" alt="Logo" className="h-10 w-44 object-contain" />
        </Link>
        
        <nav className="hidden md:flex items-center gap-1 lg:gap-2">
          {renderNavItems(navigation)}
        </nav>
      </div>

      {/* Mobile Menu Toggle - Simplified for now */}
      <div className="flex items-center gap-2 md:hidden">
        <Button variant="ghost" size="icon" className="h-8 w-8">
          <Menu className="h-5 w-5" />
        </Button>
      </div>

      <div className="ml-auto flex items-center gap-2 lg:gap-4">
        <NotificationManager />
        
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="relative h-8 w-8 rounded-full">
              <Avatar className="h-8 w-8 border">
                <AvatarImage src={user?.avatar_url} alt={user?.nome} />
                <AvatarFallback className="bg-primary/10 text-primary">
                  {user?.nome ? user.nome.split(' ').map(n => n[0]).join('').toUpperCase() : 'U'}
                </AvatarFallback>
              </Avatar>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent className="w-56" align="end" forceMount>
            <DropdownMenuLabel className="font-normal">
              <div className="flex flex-col space-y-1">
                <p className="text-sm font-medium leading-none">{user?.nome}</p>
                <p className="text-xs leading-none text-muted-foreground">{user?.email}</p>
                <p className="text-[10px] text-muted-foreground uppercase font-bold tracking-wider mt-1">
                  {user?.setor_nome || 'Sem Setor'}
                </p>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link to="/perfil" className="flex items-center w-full cursor-pointer">
                <User className="mr-2 h-4 w-4" />
                <span>Perfil</span>
              </Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={handleLogout} className="text-destructive focus:text-destructive cursor-pointer">
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
