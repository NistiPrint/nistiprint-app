import { Progress } from '@/components/ui/progress'
import { numero } from '@/lib/formatoProducao'

function SummaryCards({ dashboardSummary, totals }) {
  if (!dashboardSummary && !totals) return null

  const previstos = dashboardSummary?.total_itens_previstos_hoje || 0
  const finalizados = dashboardSummary?.total_itens_finalizados_hoje || 0

  return (
    <div className='mb-3 flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg border bg-muted/30 px-3 py-2 text-sm'>
      {dashboardSummary && (
        <>
          <span className='text-muted-foreground'>
            Restantes hoje
            <strong className='ml-1 tabular-nums text-foreground'>{numero(Math.max(0, previstos - finalizados))}</strong>
          </span>
          <span className='text-muted-foreground'>
            Finalizados
            <strong className='ml-1 tabular-nums text-foreground'>{numero(finalizados)}</strong>
          </span>
          <span className='flex items-center gap-2 text-muted-foreground'>
            Previstos
            <strong className='tabular-nums text-foreground'>{numero(previstos)}</strong>
            <Progress value={previstos > 0 ? (finalizados / previstos) * 100 : 0} className='h-1 w-20' />
          </span>
        </>
      )}
      {dashboardSummary && totals && <span className='hidden h-4 w-px bg-border sm:block' />}
      {totals && (
        <>
          <span className='text-muted-foreground'>
            Demandas hoje
            <strong className='ml-1 tabular-nums text-foreground'>{numero(totals.demand_totals?.today)}</strong>
          </span>
          <span className='text-muted-foreground'>
            Próximos dias
            <strong className='ml-1 tabular-nums text-foreground'>{numero(totals.demand_totals?.future)}</strong>
          </span>
        </>
      )}
    </div>
  )
}

export default SummaryCards
