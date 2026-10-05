import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { useLayout } from '@/contexts/useLayout';
import { cn } from '@/lib/utils';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import SidebarNav from './SidebarNav';
import { itensDaSecao } from '@/navigation';

function Sidebar({ secao, podeVer }) {
  const { isLeftSidebarOpen, toggleLeftSidebar } = useLayout();
  const location = useLocation();
  if (!secao) return null;

  const items = itensDaSecao(secao).filter(podeVer);
  const isActive = (item) => item.exato
    ? location.pathname === item.href
    : location.pathname === item.href || location.pathname.startsWith(`${item.href}/`);

  return (
    <TooltipProvider delayDuration={200}>
      <aside className={cn(
        'hidden md:flex h-full shrink-0 flex-col border-r bg-card transition-[width] duration-200',
        isLeftSidebarOpen ? 'w-64' : 'w-16'
      )} aria-label="Navegação da seção">
        <ScrollArea className="h-full w-full scrollbar-thin">
          {isLeftSidebarOpen ? (
            <div className="p-3">
              <SidebarNav secao={secao} podeVer={podeVer} />
            </div>
          ) : (
            <nav className="flex flex-col items-center gap-2 p-2 pt-4">
              {items.map((item) => {
                const Icon = item.icon;
                return (
                  <Tooltip key={item.href}>
                    <TooltipTrigger asChild>
                      <Button asChild variant="ghost" size="icon" aria-label={item.name}
                        className={cn('h-11 w-11 rounded-lg', isActive(item) && 'bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground')}>
                        <Link to={item.href}>{Icon && <Icon className="h-5 w-5" />}</Link>
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side="right">{item.name}</TooltipContent>
                  </Tooltip>
                );
              })}
            </nav>
          )}
        </ScrollArea>
        <div className="border-t p-2">
          <Button variant="ghost" size="icon" onClick={toggleLeftSidebar}
            aria-label={isLeftSidebarOpen ? 'Recolher navegação' : 'Expandir navegação'}
            className="h-11 w-11">
            {isLeftSidebarOpen ? <ChevronLeft className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </Button>
        </div>
      </aside>
    </TooltipProvider>
  );
}

export default Sidebar;
