import { DEMANDA_FLOW_OPTIONS } from '@/lib/demandaFlow'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ChevronDown, ChevronUp, Filter, Search, X } from 'lucide-react'
import { useState } from 'react'

const STATUS_OPTIONS = [
  { value: 'all', label: 'Ativas' },
  { value: 'draft', label: 'Rascunhos' },
  { value: 'completed', label: 'Finalizadas' },
  { value: 'pending', label: 'Pendentes' },
]

function FiltersSection({
  searchTerm,
  setSearchTerm,
  statusFilter,
  setStatusFilter,
  channelFilter,
  setChannelFilter,
  modalidadeFilter,
  setModalidadeFilter,
  classificacaoFilter,
  setClassificacaoFilter,
  viewMode,
  setViewMode,
  uniqueChannels,
  clearFilters,
  hasActiveFilters,
  onApplyFilters,
}) {
  const [isExpanded, setIsExpanded] = useState(false)

  return (
    <div className='mb-6 rounded-2xl border bg-white shadow-sm'>
      <div className='border-b p-4'>
        <div className='flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between'>
          <div className='flex flex-col gap-4 lg:flex-row lg:items-center'>
            <div className='flex flex-wrap gap-2'>
              {STATUS_OPTIONS.map((option) => (
                <Button
                  key={option.value}
                  size='sm'
                  variant={statusFilter === option.value ? 'default' : 'outline'}
                  onClick={() => setStatusFilter(option.value)}
                >
                  {option.label}
                </Button>
              ))}
            </div>

            <div className='flex items-center gap-2 rounded-xl bg-slate-50 p-1'>
              <Button size='sm' variant={viewMode === 'done' ? 'default' : 'ghost'} onClick={() => setViewMode('done')}>
                Producao
              </Button>
              <Button size='sm' variant={viewMode === 'todo' ? 'default' : 'ghost'} onClick={() => setViewMode('todo')}>
                Falta produzir
              </Button>
            </div>
          </div>

          <div className='flex flex-col gap-3 sm:flex-row sm:items-center'>
            <div className='relative w-full sm:w-80'>
              <Search className='absolute left-3 top-3 h-4 w-4 text-muted-foreground' />
              <Input
                placeholder='Buscar por nome, numero ou contexto...'
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className='pl-9'
              />
            </div>

            <Collapsible open={isExpanded} onOpenChange={setIsExpanded}>
              <CollapsibleTrigger asChild>
                <Button variant='outline'>
                  <Filter className='mr-2 h-4 w-4' />
                  Filtros avancados
                  {isExpanded ? <ChevronUp className='ml-2 h-4 w-4' /> : <ChevronDown className='ml-2 h-4 w-4' />}
                </Button>
              </CollapsibleTrigger>
            </Collapsible>
          </div>
        </div>
      </div>

      <Collapsible open={isExpanded} onOpenChange={setIsExpanded}>
        <CollapsibleContent>
          <div className='space-y-4 p-4'>
            <div className='grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4'>
              <div>
                <label className='mb-1 block text-sm font-medium text-gray-700'>Fluxo</label>
                <Select value={classificacaoFilter} onValueChange={setClassificacaoFilter}>
                  <SelectTrigger>
                    <SelectValue placeholder='Todos os fluxos' />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='all'>Todos os fluxos</SelectItem>
                    {DEMANDA_FLOW_OPTIONS.map((option) => (
                      <SelectItem key={option.id} value={option.id}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div>
                <label className='mb-1 block text-sm font-medium text-gray-700'>Canal</label>
                <Select value={channelFilter} onValueChange={setChannelFilter}>
                  <SelectTrigger>
                    <SelectValue placeholder='Todos os canais' />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='all'>Todos os canais</SelectItem>
                    {uniqueChannels.map((channel) => (
                      <SelectItem key={channel} value={channel}>
                        {channel}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div>
                <label className='mb-1 block text-sm font-medium text-gray-700'>Modalidade</label>
                <Select value={modalidadeFilter} onValueChange={setModalidadeFilter}>
                  <SelectTrigger>
                    <SelectValue placeholder='Todas as modalidades' />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='all'>Todas as modalidades</SelectItem>
                    <SelectItem value='standard'>Padrao</SelectItem>
                    <SelectItem value='express'>Expressa</SelectItem>
                    <SelectItem value='fulfillment'>Fulfillment</SelectItem>
                    <SelectItem value='retirada'>Retirada</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div>
                <label className='mb-1 block text-sm font-medium text-gray-700'>Situacao detalhada</label>
                <Select value={statusFilter} onValueChange={setStatusFilter}>
                  <SelectTrigger>
                    <SelectValue placeholder='Escolha a situacao' />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='all'>Ativas</SelectItem>
                    <SelectItem value='draft'>Rascunhos</SelectItem>
                    <SelectItem value='pending'>Pendentes</SelectItem>
                    <SelectItem value='production'>Em producao</SelectItem>
                    <SelectItem value='completed'>Finalizadas</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className='flex items-center justify-between border-t pt-4'>
              <div>
                {hasActiveFilters && (
                  <Button variant='ghost' onClick={clearFilters}>
                    <X className='mr-2 h-4 w-4' />
                    Limpar filtros
                  </Button>
                )}
              </div>

              <div className='flex gap-2'>
                <Button variant='outline' onClick={() => setIsExpanded(false)}>
                  Fechar
                </Button>
                <Button onClick={onApplyFilters}>Aplicar filtros</Button>
              </div>
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}

export default FiltersSection