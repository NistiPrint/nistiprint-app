import { Input } from '@/components/ui/input';
import { Search } from 'lucide-react';

/**
 * OrderFilters — busca + filtros de status IA para pedidos personalizados.
 *
 * Filtros de IA (funcionam em conjunto com a aba ativa):
 *   - Revisar (NEEDS_REVIEW)
 *   - Sem nome (NO_PERSONALIZATION_FOUND)
 *   - Com Chat / Sem Chat
 */
function OrderFilters({ searchTerm, onSearchChange, statusFilter, onStatusFilterChange, statusCounts }) {
  const filterOptions = [
    { key: '', label: 'Todos', count: statusCounts?.all ?? 0 },
    { key: 'needs_review', label: 'Revisar', count: statusCounts?.needs_review ?? 0 },
    { key: 'no_personalization', label: 'Sem nome', count: statusCounts?.no_personalization ?? 0 },
    { key: 'with_chat', label: 'Com Chat', count: statusCounts?.with_chat ?? 0 },
    { key: 'without_chat', label: 'Sem Chat', count: statusCounts?.without_chat ?? 0 },
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

        {/* Filtros por Status IA + Chat */}
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
    </div>
  );
}

export default OrderFilters;
