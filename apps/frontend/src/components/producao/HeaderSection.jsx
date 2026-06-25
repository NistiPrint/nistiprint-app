import Can from '@/components/auth/Can'
import { Button } from '@/components/ui/button'
import { Bot, CalendarRange, Factory, PlusCircle, TruckIcon } from 'lucide-react'
import { Link } from 'react-router-dom'

function HeaderSection({ setIsCollectedDemandsModalOpen, setIsDailyTotalsModalOpen, demandasColetadas, demandasAguardandoColeta }) {
  return (
    <div className='mb-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between'>
      <div>
        <h1 className='text-3xl font-bold'>Demandas de producao</h1>
        <p className='text-sm text-muted-foreground'>Acompanhe o que entra em producao e deixe a operacao falar so o essencial.</p>
      </div>

      <div className='flex flex-wrap gap-3'>
        <Can I="criar" a="demanda_producao">
          <Link to='/producao/demanda/nova'>
            <Button className='gap-2'>
              <PlusCircle className='h-4 w-4' />
              Nova demanda
            </Button>
          </Link>
        </Can>

        <Link to='/producao/demanda/rascunhos'>
          <Button variant='outline' className='gap-2'>
            <Bot className='h-4 w-4' />
            Rascunhos
          </Button>
        </Link>

        <Button variant='outline' onClick={() => setIsCollectedDemandsModalOpen(true)} disabled={demandasColetadas.length === 0 && demandasAguardandoColeta.length === 0}>
          <TruckIcon className='mr-2 h-4 w-4' />
          Coletas ({demandasColetadas.length}/{demandasAguardandoColeta.length})
        </Button>

        <Button variant='ghost' onClick={() => setIsDailyTotalsModalOpen(true)}>
          <Factory className='mr-2 h-4 w-4' />
          Producao diaria
        </Button>

        <Link to='/producao/demanda/calendario'>
          <Button variant='ghost'>
            <CalendarRange className='mr-2 h-4 w-4' />
            Calendario
          </Button>
        </Link>
      </div>
    </div>
  )
}

export default HeaderSection