import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useLayout } from '@/contexts/LayoutContext';
import { cn } from '@/lib/utils';
import { X, ChevronRight, ChevronLeft, PanelRightClose, PanelRightOpen } from 'lucide-react';

const RightSidebar = () => {
  const { isRightSidebarOpen, toggleRightSidebar, rightSidebarContent } = useLayout();

  // If there is no content, we don't render anything (or render hidden)
  // This effectively hides the sidebar mechanism if the page doesn't use it.
  if (!rightSidebarContent) {
    return null; 
  }

  return (
    <div
      className={cn(
        "border-l bg-background transition-all duration-300 ease-in-out flex flex-col h-screen sticky top-0",
        isRightSidebarOpen ? "w-80" : "w-0 border-l-0"
      )}
    >
        <div className={cn("flex items-center justify-between p-4 border-b h-16", !isRightSidebarOpen && "hidden")}>
            <h3 className="font-semibold text-lg">Detalhes</h3>
            <Button variant="ghost" size="icon" onClick={toggleRightSidebar}>
                <X className="h-4 w-4" />
            </Button>
        </div>
        
        <div className={cn("flex-1 overflow-hidden", !isRightSidebarOpen && "hidden")}>
             <ScrollArea className="h-[calc(100vh-4rem)]">
                <div className="p-4">
                    {rightSidebarContent}
                </div>
             </ScrollArea>
        </div>
    </div>
  );
};

export default RightSidebar;
