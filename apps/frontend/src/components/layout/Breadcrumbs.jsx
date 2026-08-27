import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { ChevronRight, Home } from 'lucide-react';
import { cn } from '@/lib/utils';
import { rotulosDeRota } from '@/navigation';

// Rotulos derivados do registro de navegacao. Antes havia uma lista
// paralela mantida a mao, que ficou desatualizada (mostrava
// "Comercial", "Industrial" e "Logistica" muito depois da renomeacao).
const rotulosDerivados = rotulosDeRota();

// Segmentos que nao aparecem em nenhum menu e precisam de nome proprio.
const rotulosExtras = {
  novo: 'Novo',
  nova: 'Nova',
  editar: 'Editar',
  revisao: 'Revisão',
  rascunhos: 'Rascunhos',
  prioridade: 'Prioridade',
  calendario: 'Calendário',
  dashboard: 'Dashboard',
  permissoes: 'Permissões',
  escopo: 'Escopo',
  perfil: 'Meu Perfil',
  install: 'Instalação',
};

const routeLabels = { ...rotulosExtras, ...rotulosDerivados };

function Breadcrumbs() {
  const location = useLocation();
  const pathnames = location.pathname.split('/').filter((x) => x);

  if (pathnames.length === 0) return null;

  return (
    <nav className="flex items-center space-x-1 text-sm text-muted-foreground mb-4 overflow-x-auto whitespace-nowrap pb-1 scrollbar-none">
      <Link
        to="/"
        className="flex items-center hover:text-primary transition-colors"
      >
        <Home className="h-4 w-4" />
      </Link>

      {pathnames.map((value, index) => {
        const last = index === pathnames.length - 1;
        const to = `/${pathnames.slice(0, index + 1).join('/')}`;
        const label = routeLabels[value] || value;

        // Skip IDs (UUIDs or numeric)
        const isId = /^[0-9a-fA-F-]{8,}$/.test(value) || /^\d+$/.test(value);
        if (isId) return null;

        return (
          <React.Fragment key={to}>
            <ChevronRight className="h-4 w-4 shrink-0" />
            {last ? (
              <span className="font-medium text-foreground truncate max-w-[150px]">
                {label}
              </span>
            ) : (
              <Link
                to={to}
                className="hover:text-primary transition-colors"
              >
                {label}
              </Link>
            )}
          </React.Fragment>
        );
      })}
    </nav>
  );
}

export default Breadcrumbs;
