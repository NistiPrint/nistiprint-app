import { useSecaoSidebar } from '@/lib/hooks/useSecaoSidebar';
import { Outlet } from 'react-router-dom';

// A barra lateral vem do registro unico em src/navigation.js.
function SistemaPage() {
  useSecaoSidebar();

  return (
    <div className="p-6">
      <Outlet />
    </div>
  );
}

export default SistemaPage;
