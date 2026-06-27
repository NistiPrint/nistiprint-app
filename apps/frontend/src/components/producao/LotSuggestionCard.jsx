import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ArrowRight, Clock3, Package2, ShoppingBag, Truck } from 'lucide-react'

export default function LotSuggestionCard({ suggestion, onReview, highlighted = false }) {
  const complemento = suggestion.complemento_demanda

  return (
    <Card className={`border-l-4 ${highlighted ? 'ring-2 ring-primary border-l-primary' : 'border-l-slate-300'}`}>
      <CardContent className='p-5'>
        <div className='flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between'>
          <div className='space-y-3'>
            <div className='flex flex-wrap items-center gap-2'>
              <h3 className='text-lg font-semibold text-slate-900'>
                {suggestion.marketplace_nome}
              </h3>
              <Badge variant='secondary'>{suggestion.modalidade_label}</Badge>
              {complemento && (
                <Badge className='bg-amber-100 text-amber-900 hover:bg-amber-100'>
                  Complemento
                </Badge>
              )}
            </div>

            <div className='grid gap-2 text-sm text-slate-600 sm:grid-cols-2 xl:grid-cols-4'>
              <div className='flex items-center gap-2'>
                <Clock3 className='h-4 w-4 text-slate-400' />
                <span>{suggestion.data_coleta_label}</span>
              </div>
              <div className='flex items-center gap-2'>
                <ShoppingBag className='h-4 w-4 text-slate-400' />
                <span>{suggestion.total_pedidos} pedidos</span>
              </div>
              <div className='flex items-center gap-2'>
                <Package2 className='h-4 w-4 text-slate-400' />
                <span>{suggestion.total_itens} unidades</span>
              </div>
              <div className='flex items-center gap-2'>
                <Truck className='h-4 w-4 text-slate-400' />
                <span>{suggestion.tipo_envio || 'Coleta local'}</span>
              </div>
            </div>

            <div className='flex flex-wrap gap-2 text-xs text-slate-500'>
              <span>Corte {suggestion.horario_corte || '--:--'}</span>
              <span>Coleta {suggestion.horario_coleta || '--:--'}</span>
              {suggestion.ponto_coleta_nome && <span>{suggestion.ponto_coleta_nome}</span>}
            </div>

            {complemento && (
              <div className='rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900'>
                Novos pedidos compativeis com a demanda ativa {complemento.demanda_id || complemento.id}.
              </div>
            )}

            {suggestion.warnings?.length > 0 && (
              <div className='flex flex-wrap gap-2'>
                {suggestion.warnings.slice(0, 3).map((warning) => (
                  <Badge key={warning} variant='outline' className='border-amber-200 bg-amber-50 text-amber-800'>
                    {warning}
                  </Badge>
                ))}
              </div>
            )}
          </div>

          <div className='flex flex-col gap-3 lg:min-w-48'>
            <div className='rounded-2xl bg-slate-50 p-3 text-center'>
              <div className='text-xs uppercase tracking-wide text-slate-500'>SKUs</div>
              <div className='text-2xl font-semibold text-slate-900'>{suggestion.total_skus}</div>
            </div>
            <Button onClick={() => onReview(suggestion)} className='gap-2'>
              Revisar lote
              <ArrowRight className='h-4 w-4' />
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
