import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useLayout } from '@/contexts/LayoutContext';
import { cn } from '@/lib/utils';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

function Sidebar() {
  const { isLeftSidebarOpen, toggleLeftSidebar, leftSidebarContent, leftSidebarMenuItems } = useLayout();
  const navigate = useNavigate();

  // Se não houver conteúdo definido para a sidebar, não renderiza nada
  if (!leftSidebarContent) return null;

  return (
    <TooltipProvider delayDuration={200}>
      <div
        className={cn(
          "hidden border-r bg-gradient-to-b from-muted/30 to-muted/10 md:flex flex-col transition-all duration-300 ease-in-out h-full relative shadow-sm",
          isLeftSidebarOpen ? "w-64" : "w-16"
        )}
      >
        {/* Gradient overlay for modern look */}
        <div className="absolute inset-0 bg-gradient-to-b from-primary/0 via-primary/0 to-primary/5 pointer-events-none" />

        <ScrollArea className="flex-1 h-full w-full overflow-hidden scrollbar-thin">
          <div
            className={cn(
              "p-3 transition-all duration-300 min-h-full",
              !isLeftSidebarOpen && "opacity-0 overflow-hidden"
            )}
          >
            {leftSidebarContent}
          </div>

          {!isLeftSidebarOpen && (
            <div className="absolute inset-0 flex flex-col items-center pt-12 gap-2">
              {leftSidebarMenuItems.map((item, index) => {
                const Icon = item.icon;
                return (
                  <Tooltip key={index}>
                    <TooltipTrigger asChild>
                      <div className="flex flex-col items-center">
                        <Button
                          variant="ghost"
                          size="sm"
                          className={cn(
                            "h-9 w-9 p-0 rounded-lg transition-all duration-200",
                            "hover:bg-primary/10 hover:text-primary"
                          )}
                          onClick={() => {
                            if (item.href) {
                              navigate(item.href);
                            }
                          }}
                        >
                          {Icon && <Icon className="h-4 w-4" />}
                        </Button>
                      </div>
                    </TooltipTrigger>
                    <TooltipContent side="right" className="font-medium">
                      {item.name}
                    </TooltipContent>
                  </Tooltip>
                );
              })}
            </div>
          )}
        </ScrollArea>

        {/* Collapse toggle button - Modern design */}
        <div
          className={cn(
            "absolute -right-3 top-1/2 -translate-y-1/2 z-10 transition-opacity duration-200",
            "opacity-0 hover:opacity-100"
          )}
        >
          <Button
            variant="outline"
            size="icon"
            onClick={toggleLeftSidebar}
            className={cn(
              "h-6 w-6 rounded-full border-2 bg-background shadow-md",
              "hover:bg-primary hover:text-primary-foreground hover:border-primary",
              "transition-all duration-200"
            )}
          >
            {isLeftSidebarOpen ? (
              <ChevronLeft className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
          </Button>
        </div>
      </div>
    </TooltipProvider>
  );
}

export default Sidebar;
