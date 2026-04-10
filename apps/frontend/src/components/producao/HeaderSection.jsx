import Can from '@/components/auth/Can'
import { Button } from '@/components/ui/button'
import { AlertCircle, Bot, CalendarRange, ClipboardList, Factory, PlusCircle, TruckIcon } from 'lucide-react'
import { Link } from 'react-router-dom'

function HeaderSection({ isCollectedDemandsModalOpen, setIsCollectedDemandsModalOpen, setIsDailyTotalsModalOpen, demandasColetadas, demandasAguardandoColeta }) {
  return (
    <div className='flex justify-between items-center mb-6'>
      <h1 className='text-3xl font-bold'>Demandas de Produção</h1>
      <div className='flex gap-3'>
        <Link to='/producao/demanda/rascunhos'>
          <Button variant='outline' className='gap-2'>
            <Bot className='h-4 w-4' />
            Rascunhos
          </Button>
        </Link>
        <Button
          variant='outline'
          onClick={() => setIsDailyTotalsModalOpen(true)}>
          <Factory className='h-4 w-4 mr-2' /> Produção Diária
        </Button>
        <Button
          variant='outline'
          onClick={() => setIsCollectedDemandsModalOpen(true)}
          disabled={demandasColetadas.length === 0 && demandasAguardandoColeta.length === 0}>
          <TruckIcon className='h-4 w-4 mr-2' />
          Coletas ({demandasColetadas.length}/{demandasAguardandoColeta.length})
        </Button>
        <Link to='/producao/demanda/calendario'>
          <Button variant='outline'>
            <CalendarRange className='h-4 w-4 mr-2' /> Calendário
          </Button>
        </Link>
        <Link to='/producao/demanda/prioridade'>
          <Button variant='outline'>
            <AlertCircle className='h-4 w-4 mr-2' /> Prioridade
          </Button>
        </Link>
        <Can I="criar" a="demanda_producao">
          <Link to='/producao/demanda/nova'>
            <Button>
              <PlusCircle className='h-4 w-4 mr-2' /> Nova Demanda
            </Button>
          </Link>
        </Can>
      </div>
    </div>
  )
}

export default HeaderSection
