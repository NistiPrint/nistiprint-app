import { useProducaoSidebar } from '@/lib/hooks/useProducaoSidebar';
import { Outlet } from 'react-router-dom';

function ProducaoPage() {
  // Menu lateral da operacao Industrial. Compartilhado com as telas de
  // despacho, que ficam fora da rota /producao mas pertencem a mesma operacao.
  useProducaoSidebar();

  return (
    <div className="h-full">
      <Outlet />
    </div>
  );
}

export default ProducaoPage;
