import { Card, CardContent } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'

function SummaryCards({ dashboardSummary, totals }) {
  return (
    <div className='flex flex-wrap gap-4 mb-4'>
      {dashboardSummary && (
        <Card className='border-l-4 border-l-green-500 flex-1 min-w-0'>
          <CardContent className='py-5 relative'>
            <div className='absolute top-1 left-2 text-xs text-gray-400'>Produção de itens</div>
            <div className='space-y-3'>
              <div className='flex items-center justify-between'>
                <div className='text-center'>
                  <div className='text-lg font-bold text-gray-900'>
                    {Math.max(
                      0,
                      (dashboardSummary.total_itens_previstos_hoje || 0) -
                        (dashboardSummary.total_itens_finalizados_hoje || 0)
                    )}
                  </div>
                  <div className='text-xs text-gray-600'>Restantes</div>
                </div>
                <div className='text-center'>
                  <div className='text-lg font-bold text-gray-900'>
                    {dashboardSummary.total_itens_finalizados_hoje || 0}
                  </div>
                  <div className='text-xs text-gray-600'>Finalizados</div>
                </div>
                <div className='text-center'>
                  <div className='text-lg font-bold text-gray-900'>
                    {dashboardSummary.total_itens_previstos_hoje || 0}
                  </div>
                  <div className='text-xs text-gray-600'>Previstos</div>
                </div>
              </div>
              <Progress
                value={
                  dashboardSummary.total_itens_previstos_hoje > 0
                    ? ((dashboardSummary.total_itens_finalizados_hoje || 0) /
                        dashboardSummary.total_itens_previstos_hoje) *
                      100
                    : 0
                }
                className='h-2 w-full'
              />
            </div>
          </CardContent>
        </Card>
      )}
      {totals && (
        <Card className='border-l-4 border-l-red-500 flex-1 min-w-0'>
          <CardContent className='py-5 relative'>
            <div className='absolute top-1 left-2 text-xs text-gray-400'>Demandas a entregar</div>
            <div className='text-center'>
              <div className='text-lg font-bold text-gray-900'>
                Hoje: {totals.demand_totals?.today || 0} | Próximos dias: {totals.demand_totals?.future || 0}
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

export default SummaryCards
