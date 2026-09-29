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
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';
import { useAuth } from '@/contexts/AuthContext';
import { cn } from '@/lib/utils';
import {
  ChevronDown,
  LogOut,
  Menu,
  User,
} from 'lucide-react';
import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { secaoParaRota, TOP_NAV } from '@/navigation';
import SidebarNav from './SidebarNav';

// O menu vive em src/navigation.js (registro unico de navegacao).
const navigation = TOP_NAV;

function MobileNavTree({ items, isVisible, isActive, onNavigate, depth = 0 }) {
  return (
    <ul className={cn('space-y-1', depth > 0 && 'ml-3 border-l pl-3')}>
      {items.filter(isVisible).map((item) => {
        const Icon = item.icon;
        if (item.type === 'link') {
          return (
            <li key={item.href || item.name}>
              <Link to={item.href} onClick={onNavigate}
                className={cn('flex min-h-11 items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium',
                  isActive(item) ? 'bg-primary/10 text-primary' : 'text-foreground hover:bg-muted')}>
                {Icon && <Icon className="h-4 w-4 shrink-0" />}
                <span>{item.name}</span>
              </Link>
            </li>
          );
        }
        return (
          <li key={item.href || item.name}>
            <details open={isActive(item)}>
              <summary className="flex min-h-11 cursor-pointer list-none items-center gap-3 rounded-lg px-3 py-2 text-sm font-semibold text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {Icon && <Icon className="h-4 w-4 shrink-0" />}
                <span>{item.name}</span>
                <ChevronDown className="ml-auto h-4 w-4 text-muted-foreground" />
              </summary>
              <MobileNavTree items={item.children || []} isVisible={isVisible} isActive={isActive} onNavigate={onNavigate} depth={depth + 1} />
            </details>
          </li>
        );
      })}
    </ul>
  );
}

function Header() {
  const { user, logout, isAdmin, hasPermission } = useAuth();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const secao = secaoParaRota(location.pathname);
  const topNavBySection = {
    pedidos: 'Pedidos',
    producao: 'Produção',
    estoque: 'Estoque',
    catalogo: 'Catálogo',
    monitoramento: 'Monitoramento',
    configuracoes: 'Configurações',
  };
  const mobileNavigation = secao
    ? navigation.filter((item) => item.name !== topNavBySection[secao.id])
    : navigation;

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
    if (item.href && (location.pathname === item.href || location.pathname.startsWith(`${item.href}/`))) return true;
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
      <div className="flex min-w-0 items-center gap-2 md:gap-4">
        <Link
          to="/"
          className="mr-1 flex items-center gap-2 font-semibold text-primary transition-opacity hover:opacity-80 md:mr-4"
        >
          <img
            src="/logomarca.png"
            alt="Logo"
            className="h-9 w-28 object-contain sm:w-36 md:h-10 md:w-44"
          />
        </Link>

        <nav className="hidden md:flex items-center gap-1 lg:gap-1.5">
          {renderNavItems(navigation)}
        </nav>
      </div>

      {/* Mobile Menu */}
      <div className="flex items-center gap-2 md:hidden">
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Abrir menu" className="h-11 w-11 rounded-lg">
              <Menu className="h-5 w-5" />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-[320px] overflow-y-auto sm:w-[360px]">
            <SheetHeader>
              <SheetTitle className="text-left">Nisti Print</SheetTitle>
            </SheetHeader>
            <div className="mt-6 space-y-5">
              {secao && (
                <div>
                  <h3 className="mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Nesta seção</h3>
                  <SidebarNav secao={secao} podeVer={(item) => checkItemVisibility(item)} onNavigate={() => setMobileOpen(false)} />
                </div>
              )}
              {secao && <h3 className="border-t pt-4 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Outras áreas</h3>}
              <MobileNavTree items={mobileNavigation} isVisible={checkItemVisibility} isActive={checkIsActive} onNavigate={() => setMobileOpen(false)} />
            </div>
          </SheetContent>
        </Sheet>
      </div>

      <div className="ml-auto flex items-center gap-2 lg:gap-3">
        <NotificationManager />

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              className="relative h-11 w-11 rounded-full transition-all hover:bg-muted/80"
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
