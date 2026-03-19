import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ChevronDown, ChevronUp, Filter, Search, X } from 'lucide-react'
import { useState } from 'react'

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
  onApplyFilters
}) {
  const [isExpanded, setIsExpanded] = useState(false)

  return (
    <div className='bg-white rounded-lg border shadow-sm mb-6'>
      {/* Barra Superior - Sempre Visível */}
      <div className='p-4 border-b'>
        <div className='flex items-center justify-between'>
          <div className='flex items-center gap-4'>
            {/* Toggle de Visualização */}
            <div className='flex items-center gap-2'>
              <span className='text-sm font-medium text-gray-700'>Visualização:</span>
              <div className='flex gap-1'>
                <Button
                  size="sm"
                  variant={viewMode === 'done' ? 'default' : 'outline'}
                  onClick={() => setViewMode('done')}
                >
                  Produção
                </Button>
                <Button
                  size="sm"
                  variant={viewMode === 'todo' ? 'default' : 'outline'}
                  onClick={() => setViewMode('todo')}
                >
                  Falta Produzir
                </Button>
              </div>
            </div>

            {/* Busca Rápida */}
            <div className='relative w-80'>
              <Search className='absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground' />
              <Input
                placeholder='Buscar demanda por nome...'
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
                className='pl-9'
              />
            </div>
          </div>

          {/* Botão de Expandir/Recolher */}
          <Collapsible open={isExpanded} onOpenChange={setIsExpanded}>
            <CollapsibleTrigger asChild>
              <Button variant="outline" size="sm">
                <Filter className="h-4 w-4 mr-2" />
                Filtros Avançados
                {isExpanded ? <ChevronUp className="h-4 w-4 ml-2" /> : <ChevronDown className="h-4 w-4 ml-2" />}
              </Button>
            </CollapsibleTrigger>
          </Collapsible>
        </div>
      </div>

      {/* Filtros Expandidos */}
      <Collapsible open={isExpanded} onOpenChange={setIsExpanded}>
        <CollapsibleContent>
          <div className='p-4 space-y-4'>
            <div className='grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4'>
              {/* Status */}
              <div>
                <label className='block text-sm font-medium text-gray-700 mb-1'>Status da Demanda</label>
                <Select value={statusFilter} onValueChange={setStatusFilter}>
                  <SelectTrigger>
                    <SelectValue placeholder='Todos os Status' />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='all'>Todos os Status</SelectItem>
                    <SelectItem value='draft'>Rascunho</SelectItem>
                    <SelectItem value='pending'>Pendente</SelectItem>
                    <SelectItem value='production'>Em Produção</SelectItem>
                    <SelectItem value='completed'>Finalizado</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Canal de Venda */}
              <div>
                <label className='block text-sm font-medium text-gray-700 mb-1'>Canal de Venda</label>
                <Select value={channelFilter} onValueChange={setChannelFilter}>
                  <SelectTrigger>
                    <SelectValue placeholder='Todos os Canais' />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='all'>Todos os Canais</SelectItem>
                    {uniqueChannels.map(channel => (
                      <SelectItem key={channel} value={channel}>
                        {channel}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Modalidade Logística */}
              <div>
                <label className='block text-sm font-medium text-gray-700 mb-1'>Modalidade Logística</label>
                <Select value={modalidadeFilter} onValueChange={setModalidadeFilter}>
                  <SelectTrigger>
                    <SelectValue placeholder='Todos os Tipos' />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='all'>Todos os Tipos</SelectItem>
                    <SelectItem value='standard'>Padrão</SelectItem>
                    <SelectItem value='express'>Expressa (Flex)</SelectItem>
                    <SelectItem value='fulfillment'>Fulfillment</SelectItem>
                    <SelectItem value='retirada'>Retirada</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Classificação do Cliente */}
              <div>
                <label className='block text-sm font-medium text-gray-700 mb-1'>Classificação do Cliente</label>
                <Select value={classificacaoFilter} onValueChange={setClassificacaoFilter}>
                  <SelectTrigger>
                    <SelectValue placeholder='Todos os Tipos' />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='all'>Todos os Tipos</SelectItem>
                    <SelectItem value='b2c'>B2C (Consumidor Final)</SelectItem>
                    <SelectItem value='b2b'>B2B (Venda Corporativa)</SelectItem>
                    <SelectItem value='interno'>Interno (Estoque/Amostra)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Botões de Ação */}
            <div className='flex items-center justify-between pt-4 border-t'>
              <div className='flex gap-2'>
                {hasActiveFilters && (
                  <Button variant='ghost' onClick={clearFilters} className='px-3'>
                    <X className='h-4 w-4 mr-2' />
                    Limpar Filtros
                  </Button>
                )}
              </div>
              <div className='flex gap-2'>
                <Button variant='outline' onClick={() => setIsExpanded(false)}>
                  Cancelar
                </Button>
                <Button onClick={onApplyFilters}>
                  Aplicar Filtros
                </Button>
              </div>
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}

export default FiltersSection
