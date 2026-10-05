import { Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { secaoParaRota } from '@/navigation';
import Header from './Header';
import RightSidebar from './RightSidebar';
import Sidebar from './Sidebar';
import Breadcrumbs from './Breadcrumbs';
import AlertaTurbo from '@/components/despacho/AlertaTurbo';
import AlertasLogisticos from '@/components/despacho/AlertasLogisticos';
import AgentUpdateBanner from './AgentUpdateBanner';

function MainLayout() {
  const location = useLocation();
  const { isAdmin, hasPermission } = useAuth();
  const secao = secaoParaRota(location.pathname);
  const podeVer = (item) => {
    if (item.adminOnly && !isAdmin()) return false;
    if (item.permission && !hasPermission(item.permission.a, item.permission.I)) return false;
    return true;
  };

  return (
    <div className="flex h-dvh min-h-screen flex-col overflow-hidden bg-background">
      {/* Acima do Header de propósito: o prazo do Turbo é de 40 minutos, e o
          alerta precisa alcançar o operador em qualquer tela. */}
      <AlertaTurbo />
      <AlertasLogisticos />
      <AgentUpdateBanner />
      <Header />
      <div className="flex flex-1 overflow-hidden relative">
        <Sidebar secao={secao} podeVer={podeVer} />
        <main id="main-content" className="min-w-0 flex-1 overflow-y-auto px-4 py-5 md:px-6 md:py-6">
          <Breadcrumbs />
          <Outlet />
        </main>
        <RightSidebar />
      </div>
    </div>
  );
}

export default MainLayout;
