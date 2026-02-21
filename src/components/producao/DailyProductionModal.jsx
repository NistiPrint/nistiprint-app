import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'

function DailyProductionModal({ isOpen, onClose, totals, loading }) {
  return (
    <Dialog
      open={isOpen}
      onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Produção Diária por Setor</DialogTitle>
        </DialogHeader>
        <div className='space-y-4 py-4'>
          {totals && (
            <div className='grid grid-cols-1 md:grid-cols-2 gap-4'>
              <Card className='border-l-4 border-l-gray-500'>
                <CardContent className='pt-6'>
                  <div className='text-center'>
                    <div className='text-2xl font-bold text-gray-900'>
                      {totals.sector_totals?.CPD || 0}
                    </div>
                    <div className='text-sm text-gray-600'>CPD (Hoje)</div>
                  </div>
                </CardContent>
              </Card>
              <Card className='border-l-4 border-l-blue-500'>
                <CardContent className='pt-6'>
                  <div className='text-center'>
                    <div className='text-2xl font-bold text-gray-900'>
                      {totals.sector_totals?.Capas || 0}
                    </div>
                    <div className='text-sm text-gray-600'>Capas (Hoje)</div>
                  </div>
                </CardContent>
              </Card>
              <Card className='border-l-4 border-l-green-500'>
                <CardContent className='pt-6'>
                  <div className='text-center'>
                    <div className='text-2xl font-bold text-gray-900'>
                      {totals.sector_totals?.Miolos || 0}
                    </div>
                    <div className='text-sm text-gray-600'>Miolos (Hoje)</div>
                  </div>
                </CardContent>
              </Card>
              <Card className='border-l-4 border-l-purple-500'>
                <CardContent className='pt-6'>
                  <div className='text-center'>
                    <div className='text-2xl font-bold text-gray-900'>
                      {totals.sector_totals?.Expedição || 0}
                    </div>
                    <div className='text-sm text-gray-600'>
                      Expedição (Hoje)
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
          {!totals && !loading && (
            <div className='text-center text-muted-foreground'>
              Nenhum dado de produção diária disponível.
            </div>
          )}
        </div>
        <DialogFooter>
          <Button
            variant='outline'
            onClick={onClose}>
            Fechar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default DailyProductionModal
