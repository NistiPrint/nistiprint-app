import { cn } from '@/lib/utils';
import { Link, useLocation } from 'react-router-dom';
import { itensDaSecao } from '@/navigation';

// Renderiza a barra lateral de uma secao do registro de navegacao.
// Substitui as seis copias de renderMenuItems que existiam nos hubs.
export default function SidebarNav({ secao, podeVer }) {
  const location = useLocation();
  if (!secao) return null;

  const estaAtivo = (item) =>
    item.exato
      ? location.pathname === item.href
      : location.pathname === item.href || location.pathname.startsWith(item.href + '/');

  const renderItem = (item) => {
    const Icon = item.icon;
    const ativo = estaAtivo(item);
    return (
      <li key={item.href}>
        <Link
          to={item.href}
          className={cn(
            'flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-all hover:bg-muted',
            ativo && 'bg-muted text-primary font-medium'
          )}
        >
          {Icon && <Icon className="h-4 w-4 shrink-0" />}
          <div className="min-w-0">
            <div className="leading-tight truncate">{item.name}</div>
            {item.description && (
              <div className="text-[10px] text-muted-foreground leading-tight truncate">
                {item.description}
              </div>
            )}
          </div>
        </Link>
      </li>
    );
  };

  const grupos = secao.grupos
    .map((g) => ({ ...g, itens: g.itens.filter(podeVer) }))
    .filter((g) => g.itens.length > 0);

  if (!grupos.length) return null;

  return (
    <div className="flex flex-col gap-4">
      <div className="px-3 py-2">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/70">
          {secao.titulo}
        </h2>
      </div>
      <nav className="space-y-1">
        {grupos.map((grupo, i) => (
          <div key={grupo.nome || i} className={grupo.nome ? 'mb-4' : undefined}>
            {grupo.nome && (
              <div className="px-3 py-2 text-sm font-medium text-muted-foreground uppercase tracking-wider">
                {grupo.nome}
              </div>
            )}
            <ul className={cn('space-y-1', grupo.nome && 'pl-4 py-2')}>
              {grupo.itens.map(renderItem)}
            </ul>
          </div>
        ))}
      </nav>
    </div>
  );
}

export { itensDaSecao };
