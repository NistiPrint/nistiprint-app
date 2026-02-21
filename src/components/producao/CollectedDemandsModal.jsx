import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import api from '@/services/api'
import { format } from 'date-fns'
import { CheckCircle, Eye, History, Truck } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

function CollectedDemandsModal({ isOpen, onClose, demandasColetadas, demandasAguardandoColeta, handleCollectDemand }) {
  const [coletasHistory, setColetasHistory] = useState([])
  const [selectedDemandaId, setSelectedDemandaId] = useState(null)
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)

  const handleViewHistory = async (demandaId) => {
    if (selectedDemandaId === demandaId) {
      setSelectedDemandaId(null)
      setColetasHistory([])
      return
    }

    setIsLoadingHistory(true)
    setSelectedDemandaId(demandaId)
    try {
      const response = await api.get(`/v2/demanda_producao/${demandaId}/coletas`)
      setColetasHistory(response.data.coletas)
    } catch (error) {
      console.error("Erro ao buscar histórico de coletas:", error)
      setColetasHistory([])
    } finally {
      setIsLoadingHistory(false)
    }
  }

  return (
    <Dialog
      open={isOpen}
      onOpenChange={onClose}>
      <DialogContent className='max-w-6xl max-h-[80vh] overflow-y-auto'>
        <DialogHeader>
          <DialogTitle>
            Coletas ({demandasColetadas.length}/{demandasAguardandoColeta.length})
          </DialogTitle>
        </DialogHeader>
        <div className='space-y-6 py-4'>
          {/* Aguardando Coleta */}
          <div>
            <h4 className='text-lg font-semibold mb-3'>Aguardando Coleta</h4>
            {demandasAguardandoColeta.length === 0 ? (
              <div className='text-center text-muted-foreground py-4'>
                <CheckCircle className='mx-auto h-8 w-8 text-muted-foreground/50 mb-2' />
                <p>Nenhuma demanda aguardando coleta.</p>
              </div>
            ) : (
              <div className='space-y-2'>
                {demandasAguardandoColeta.map(demanda => (
                  <Card key={demanda.id} className='shadow-sm'>
                    <CardContent className='py-4'>
                      <div className='flex items-center justify-between'>
                        <div className='flex-1'>
                          <h3 className='text-lg font-semibold text-gray-900'>
                            {demanda.nome}
                          </h3>
                          <div className='flex items-center gap-4 mt-1 text-sm text-gray-600'>
                            {demanda.canal_venda_plataforma && (
                              <span className='flex items-center gap-1'>
                                <span
                                  className='w-3 h-3 rounded-full'
                                  style={{
                                    backgroundColor: demanda.canal_venda_color,
                                  }}></span>
                                {demanda.canal_venda_plataforma}
                              </span>
                            )}
                            <span>
                              {demanda.total_itens ||
                                demanda.total_quantidade ||
                                0}{' '}
                              itens
                            </span>
                            <span>Finalizada</span>
                          </div>
                        </div>
                        <div className='flex gap-2'>
                          <Button
                            variant='outline'
                            size='sm'
                            onClick={() => handleCollectDemand(demanda.id)}
                          >
                            <Truck className='h-3 w-3 mr-1' /> Marcar como Coletado
                          </Button>
                          <Link to={`/producao/demanda/${demanda.id}/dashboard`}>
                            <Button variant='outline' size='sm'>
                              <Eye className='h-3 w-3 mr-1' /> Ver Detalhes
                            </Button>
                          </Link>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </div>

          {/* Coletadas */}
          <div>
            <h4 className='text-lg font-semibold mb-3'>Coletadas</h4>
            {demandasColetadas.length === 0 ? (
              <div className='text-center text-muted-foreground py-4'>
                <CheckCircle className='mx-auto h-8 w-8 text-muted-foreground/50 mb-2' />
                <p>Nenhuma demanda coletada encontrada.</p>
              </div>
            ) : (
              <div className='space-y-2'>
                {demandasColetadas.map(demanda => (
                  <div key={demanda.id}>
                    <Card className='shadow-sm'>
                      <CardContent className='py-4'>
                        <div className='flex items-center justify-between'>
                          <div className='flex-1'>
                            <h3 className='text-lg font-semibold text-gray-900'>
                              {demanda.nome}
                            </h3>
                            <div className='flex items-center gap-4 mt-1 text-sm text-gray-600'>
                              {demanda.canal_venda_plataforma && (
                                <span className='flex items-center gap-1'>
                                  <span
                                    className='w-3 h-3 rounded-full'
                                    style={{
                                      backgroundColor: demanda.canal_venda_color,
                                    }}></span>
                                  {demanda.canal_venda_plataforma}
                                </span>
                              )}
                              <span>
                                {demanda.total_itens ||
                                  demanda.total_quantidade ||
                                  0}{' '}
                                itens
                              </span>
                              <span>
                                Coletado {demanda.quantidade_coletada_total} de {demanda.total_itens}
                              </span>
                            </div>
                          </div>
                          <div className='flex gap-2'>
                            <Button
                              variant='outline'
                              size='sm'
                              onClick={() => handleViewHistory(demanda.id)}
                            >
                              <History className='h-3 w-3 mr-1' /> Ver Histórico
                            </Button>
                            <Link to={`/producao/demanda/${demanda.id}/dashboard`}>
                              <Button variant='outline' size='sm'>
                                <Eye className='h-3 w-3 mr-1' /> Ver Detalhes
                              </Button>
                            </Link>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                    {selectedDemandaId === demanda.id && (
                      <div className="border-t p-4">
                        <h5 className="font-semibold mb-2">Histórico de Coletas</h5>
                        {isLoadingHistory ? <p>Carregando...</p> : (
                          coletasHistory.length > 0 ? (
                            <ul className="space-y-2">
                              {coletasHistory.map(coleta => (
                                <li key={coleta.id} className="text-sm p-2 bg-gray-50 rounded">
                                  - {coleta.quantidade} unidades coletadas em {format(new Date(coleta.created_at), 'dd/MM/yyyy HH:mm')}
                                </li>
                              ))}
                            </ul>
                          ) : <p className="text-sm text-muted-foreground">Nenhum registro de coleta encontrado.</p>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
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

export default CollectedDemandsModal
