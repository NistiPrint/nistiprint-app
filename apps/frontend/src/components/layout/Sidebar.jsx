import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
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
    <div className={cn(
        "hidden border-r bg-muted/40 md:flex flex-col transition-all duration-300 ease-in-out h-full p-0 m-0 relative",
        isLeftSidebarOpen ? "w-64" : "w-16"
      )}>

      <ScrollArea className="flex-1 h-full w-full overflow-hidden">
        <div className={cn(
          "p-3 transition-all duration-300 min-h-full",
          !isLeftSidebarOpen && "opacity-0 overflow-hidden"
        )}>
          {leftSidebarContent}
        </div>

        {!isLeftSidebarOpen && (
           <div className="absolute inset-0 flex flex-col items-center pt-12 gap-2">
             {leftSidebarMenuItems.map((item, index) => {
               const Icon = item.icon;
               return (
                 <div
                   key={index}
                   className="flex flex-col items-center"
                   title={item.name}
                 >
                   <Button
                     variant="ghost"
                     size="sm"
                     className="h-8 w-8 p-0 rounded-full"
                     onClick={() => {
                       if (item.href) {
                         navigate(item.href);
                       }
                     }}
                   >
                     {Icon && <Icon className="h-4 w-4" />}
                   </Button>
                 </div>
               );
             })}
           </div>
        )}
      </ScrollArea>

      {/* Collapse toggle button */}
      <div className="absolute -right-3 top-1/2 -translate-y-1/2 z-10">
        <Button
          variant="ghost"
          size="sm"
          onClick={toggleLeftSidebar}
          className="h-6 w-6 rounded-full border bg-background p-0 shadow-md hover:bg-muted"
        >
          {isLeftSidebarOpen ? <ChevronLeft className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        </Button>
      </div>
    </div>
  );
}

export default Sidebar;