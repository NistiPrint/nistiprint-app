import { Check } from 'lucide-react';

/**
 * Trilha de passos do formulário. Passos já visitados (ou todos, na edição)
 * voltam com um clique.
 */
function TrilhaPassos({ passos, atual, maiorVisitado, onSelecionar, liberarTodos = false }) {
  return (
    <nav aria-label="Passos da demanda" className="mb-2">
      <ol className="relative flex items-start justify-between">
        <div className="absolute left-0 top-4 -z-10 h-0.5 w-full bg-muted" />
        {passos.map((passo, indice) => {
          const concluido = atual > passo.id;
          const ativo = atual === passo.id;
          const liberado = liberarTodos || passo.id <= maiorVisitado;

          return (
            <li key={passo.id} className="flex flex-col items-center gap-2 bg-background px-3">
              <button
                type="button"
                onClick={() => liberado && onSelecionar(passo.id)}
                disabled={!liberado}
                aria-current={ativo ? 'step' : undefined}
                className={`flex h-8 w-8 items-center justify-center rounded-full border-2 text-sm font-bold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed ${
                  ativo || concluido
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'border-muted bg-background text-muted-foreground'
                }`}
              >
                {concluido ? <Check className="h-4 w-4" /> : indice + 1}
              </button>
              <span className={`text-xs font-medium sm:text-sm ${ativo ? 'text-primary' : 'text-muted-foreground'}`}>
                {passo.label}
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export default TrilhaPassos;
