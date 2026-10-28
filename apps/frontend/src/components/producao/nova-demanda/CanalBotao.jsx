import CanalIcon from '@/components/producao/CanalIcon';
import { resolverIconeCanal } from '@/lib/canalIcons';
import { normalizarHora } from '@/lib/novaDemanda';

/** Botão de canal: um clique escolhe a origem da demanda. */
function CanalBotao({ canal, ativo = false, onClick, moduleIcons }) {
  const horario = normalizarHora(canal.horario_coleta);
  const cor = canal.color || '#007bff';
  const temIcone = Boolean(resolverIconeCanal(canal.nome, canal.slug || canal.plataforma, moduleIcons));

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={ativo}
      className={`flex min-h-11 w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
        ativo ? 'border-primary bg-primary/5 ring-1 ring-primary' : 'border-border bg-card hover:bg-muted'
      }`}
      style={{ borderLeftColor: cor, borderLeftWidth: '4px' }}
    >
      <span className="flex h-7 w-7 shrink-0 items-center justify-center">
        {temIcone ? (
          <CanalIcon
            canalNome={canal.nome}
            marketplaceSlug={canal.slug || canal.plataforma}
            moduleIcons={moduleIcons}
            comTooltip={false}
            className="h-6 w-6 object-contain"
          />
        ) : (
          <span className="h-3 w-3 rounded-full" style={{ backgroundColor: cor }} />
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold">{canal.nome}</span>
        <span className="mt-0.5 block text-xs text-muted-foreground">
          {horario ? `Coleta ${horario}` : 'Sem horário padrão'}
        </span>
      </span>
      <span className="flex shrink-0 flex-col items-end gap-1">
        {canal.flex && (
          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold uppercase text-amber-800">Flex</span>
        )}
        {canal.fulfillment && (
          <span className="rounded bg-violet-100 px-1.5 py-0.5 text-[10px] font-bold uppercase text-violet-800">Full</span>
        )}
      </span>
    </button>
  );
}

export default CanalBotao;
