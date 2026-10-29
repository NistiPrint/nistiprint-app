import { getModalidadeLabel } from '@/lib/demandaFlow';
import { formatAppDate } from '@/lib/dateTime';
import { CalendarClock, Package, Store, Truck } from 'lucide-react';

function Chip({ icone: Icone, children, onClick, cor }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-1.5 rounded-full border bg-card px-3 py-1 text-xs font-medium transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      style={cor ? { borderColor: cor } : undefined}
    >
      {Icone && <Icone className="h-3.5 w-3.5 text-muted-foreground" />}
      {children}
    </button>
  );
}

/** Resumo das escolhas do passo 1, sempre visível e clicável para voltar. */
function ResumoDemanda({ canal, modalidade, dataEntrega, horarioColeta, totalItens, onVoltarParaOrigem }) {
  if (!canal) return null;

  return (
    <div className="mb-5 flex flex-wrap items-center gap-2">
      <Chip icone={Store} cor={canal.color} onClick={onVoltarParaOrigem}>
        {canal.nome}
      </Chip>
      <Chip icone={Truck} onClick={onVoltarParaOrigem}>
        {getModalidadeLabel(modalidade)}
      </Chip>
      <Chip icone={CalendarClock} onClick={onVoltarParaOrigem}>
        {formatAppDate(dataEntrega)}
        {horarioColeta ? ` · ${horarioColeta}` : ''}
      </Chip>
      <span className="flex items-center gap-1.5 rounded-full border border-dashed px-3 py-1 text-xs text-muted-foreground">
        <Package className="h-3.5 w-3.5" />
        {totalItens} {totalItens === 1 ? 'item' : 'itens'}
      </span>
    </div>
  );
}

export default ResumoDemanda;
