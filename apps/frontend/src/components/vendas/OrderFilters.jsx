import { Input } from '@/components/ui/input';
import { Search } from 'lucide-react';

/**
 * OrderFilters — busca + filtros simplificados para pedidos personalizados.
 *
 * Os grupos IA e Chat aceitam uma opcao por vez e podem ser combinados.
 * A pagina controla o comportamento de limpar a opcao ativa.
 */
function OrderFilters({
  searchTerm,
  onSearchChange,
  aiFilter,
  onAiFilterChange,
  chatFilter,
  onChatFilterChange,
  statusCounts,
}) {
  const aiFilterOptions = [
    { key: 'pendente_ia', label: 'Pendente IA', count: statusCounts?.pendente_ia ?? 0 },
    { key: 'nome_identificado', label: 'Nome Identificado', count: statusCounts?.nome_identificado ?? 0 },
    { key: 'sem_nome', label: 'Sem Nome', count: statusCounts?.sem_nome ?? 0 },
  ];

  const chatFilterOptions = [
    { key: 'com_chat', label: 'Com', count: statusCounts?.com_chat ?? 0 },
    { key: 'sem_chat', label: 'Sem', count: statusCounts?.sem_chat ?? 0 },
  ];

  const renderFilterButton = (option, activeFilter, onFilterChange) => (
    <button
      key={option.key}
      type="button"
      aria-pressed={activeFilter === option.key}
      onClick={() => onFilterChange(option.key)}
      className={`rounded-md border px-3 py-2 text-sm font-medium transition-all duration-200 ${
        activeFilter === option.key
          ? 'border-blue-600 bg-blue-600 text-white shadow-sm'
          : 'border-gray-300 bg-gray-100 text-gray-700 hover:bg-gray-200'
      }`}
    >
      {option.label} ({option.count})
    </button>
  );

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 mb-6 shadow-sm">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Campo de Busca */}
        <div className="lg:col-span-4">
          <div className="relative">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <Search className="h-4 w-4 text-gray-400" />
            </div>
            <Input
              type="text"
              placeholder="Buscar ID Pedido ou Cliente..."
              value={searchTerm}
              onChange={(e) => onSearchChange(e.target.value)}
              className="pl-10 h-10 border-gray-300 focus:border-blue-500 focus:ring-blue-500"
            />
          </div>
        </div>

        {/* Filtros independentes e combinaveis */}
        <div className="lg:col-span-8">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
            <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Status da IA">
              <span className="text-sm font-semibold text-gray-700">IA:</span>
              {aiFilterOptions.map(option => renderFilterButton(option, aiFilter, onAiFilterChange))}
            </div>

            <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Disponibilidade do chat">
              <span className="text-sm font-semibold text-gray-700">Chat:</span>
              {chatFilterOptions.map(option => renderFilterButton(option, chatFilter, onChatFilterChange))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default OrderFilters;
