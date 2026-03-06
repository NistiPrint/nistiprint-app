import { Input } from '@/components/ui/input';
import { Search } from 'lucide-react';

function OrderFilters({ searchTerm, onSearchChange, statusFilter, onStatusFilterChange, statusCounts }) {
  const filterOptions = [
    { key: '', label: 'Todos', count: statusCounts.all },
    { key: 'success', label: 'Nome identificado', count: statusCounts.success },
    { key: 'needs_review', label: 'Revisar', count: statusCounts.needs_review },
    { key: 'no_personalization', label: 'Sem nome', count: statusCounts.no_personalization },
  ];

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

        {/* Filtros por Status */}
        <div className="lg:col-span-8">
          <div className="flex flex-wrap gap-2">
            {filterOptions.map((option) => (
              <button
                key={option.key}
                onClick={() => onStatusFilterChange(option.key)}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-all duration-200 ${
                  statusFilter === option.key
                    ? 'bg-blue-600 text-white shadow-md'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200 border border-gray-300'
                }`}
              >
                {option.label} ({option.count})
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Informações adicionais */}
      <div className="mt-3 pt-3 border-t border-gray-100">
        <div className="text-xs text-gray-500 flex flex-wrap gap-4">
          <span>
            <strong className="text-blue-600">{statusCounts.success}</strong> nomes identificados
          </span>
          <span>
            <strong className="text-orange-600">{statusCounts.needs_review}</strong> precisam revisão
          </span>
          <span>
            <strong className="text-red-600">{statusCounts.no_personalization}</strong> sem personalização
          </span>
          <span>
            <strong className="text-gray-600">{statusCounts.all}</strong> total de pedidos
          </span>
        </div>
      </div>
    </div>
  );
}

export default OrderFilters;
