import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { useLayout } from '@/contexts/LayoutContext';
import { secaoParaRota, itensDaSecao } from '@/navigation';
import SidebarNav from '@/components/layout/SidebarNav';

// Resolve a barra lateral a partir da rota atual, usando o registro unico
// de navegacao.
//
// Por que existe: antes, cada hub injetava a propria barra e a limpava no
// cleanup. Ao navegar de /vendas para /despacho — rotas irmas em hubs
// diferentes — o cleanup do hub que saia apagava o menu que o hub que
// entrava acabara de montar, e o usuario perdia a navegacao inteira.
// Aqui a limpeza so acontece quando a rota de destino nao pertence a
// nenhuma secao; se pertence, quem entra assume.
export function useSecaoSidebar() {
  const location = useLocation();
  const { user, isAdmin, hasPermission } = useAuth();
  const { setLeftSidebarContent, setLeftSidebarMenuItems, setIsLeftSidebarOpen } = useLayout();

  useEffect(() => {
    const secao = secaoParaRota(location.pathname);
    if (!secao) return;

    const podeVer = (item) => {
      if (item.adminOnly && !isAdmin?.()) return false;
      if (item.permission && !hasPermission?.(item.permission.a, item.permission.I)) return false;
      return true;
    };

    setIsLeftSidebarOpen(true);
    setLeftSidebarContent(<SidebarNav secao={secao} podeVer={podeVer} />);
    setLeftSidebarMenuItems(itensDaSecao(secao).filter(podeVer));

    return () => {
      // Usa a rota vigente no momento da limpeza, nao a capturada no efeito.
      if (!secaoParaRota(window.location.pathname)) {
        setLeftSidebarContent(null);
        setLeftSidebarMenuItems([]);
      }
    };
  }, [location.pathname, user, setLeftSidebarContent, setLeftSidebarMenuItems, setIsLeftSidebarOpen]);
}

export default useSecaoSidebar;
