import { useSecaoSidebar } from '@/lib/hooks/useSecaoSidebar';
import { Outlet } from 'react-router-dom';

// A barra lateral vem do registro unico em src/navigation.js.
function ProducaoPage() {
  useSecaoSidebar();

  return (
    <div className="h-full">
      <Outlet />
    </div>
  );
}

export default ProducaoPage;
