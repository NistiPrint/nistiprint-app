const BASE = 'transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-55';

/** Cartão clicável de uma opção: um clique seleciona, sem abrir menu. */
export function OpcaoBotao({
  ativo = false,
  onClick,
  titulo,
  descricao,
  icone: Icone,
  corBorda,
  children,
  className = '',
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={ativo}
      className={`${BASE} flex min-h-11 w-full items-start gap-3 rounded-lg border p-3 text-left ${
        ativo ? 'border-primary bg-primary/5 ring-1 ring-primary' : 'border-border bg-card hover:bg-muted'
      } ${className}`}
      style={corBorda ? { borderLeftColor: corBorda, borderLeftWidth: '4px' } : undefined}
    >
      {Icone && (
        <span
          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
            ativo ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'
          }`}
        >
          <Icone className="h-4 w-4" />
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold">{titulo}</span>
        {descricao && <span className="mt-0.5 block text-xs leading-4 text-muted-foreground">{descricao}</span>}
        {children}
      </span>
    </button>
  );
}

/** Pílula compacta, para escolhas de uma linha (modalidade, data, horário). */
export function PilulaBotao({ ativo = false, onClick, children, title, className = '' }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={ativo}
      title={title}
      className={`${BASE} rounded-full border px-3 py-1.5 text-xs font-semibold ${
        ativo ? 'border-primary bg-primary text-primary-foreground' : 'border-border text-muted-foreground hover:border-primary/40 hover:bg-muted'
      } ${className}`}
    >
      {children}
    </button>
  );
}

export default OpcaoBotao;
