import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import ProductionService from '@/services/ProductionService';
import { ArrowRight, CheckCircle2, Loader2, Package } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

const normalizeStatus = (value = '') =>
  String(value)
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toUpperCase()
    .replace(/\s+/g, '_');

const sortByPrazo = (a, b) => {
  const dataA = a.data_entrega || '9999-12-31';
  const dataB = b.data_entrega || '9999-12-31';
  if (dataA !== dataB) return dataA.localeCompare(dataB);
  const horaA = a.horario_coleta || '23:59';
  const horaB = b.horario_coleta || '23:59';
  return horaA.localeCompare(horaB);
};

const ExpedicaoDashboardPage = () => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterTrilha, setFilterTrilha] = useState('ALL');

  const fetchData = async () => {
    setLoading(true);
    try {
      const response = await ProductionService.getConsolidadoProducao({ agrupado: false });
      if (response.success) {
        setItems(response.data || []);
      } else {
        toast.error('Erro ao carregar dados da expedição.');
      }
    } catch (error) {
      console.error(error);
      toast.error('Erro de comunicação com o servidor.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const { matches, pending, closing, completed } = useMemo(() => {
    let currentItems = items;
    if (filterTrilha !== 'ALL') {
      currentItems = items.filter(item => item.trilha === filterTrilha);
    }

    const matchesList = [];
    const pendingList = [];
    const closingList = [];
    const completedList = [];

    currentItems.forEach(item => {
      if (!item || typeof item !== 'object') return;
      const status = normalizeStatus(item.status_item);
      const isConcluido = status === 'CONCLUIDO';
      const hasExpedicao = (item.expedicao_capas_retiradas_qtd > 0 || item.expedicao_miolos_retirados_qtd > 0);

      if (item.match_disponivel > 0) {
        matchesList.push(item);
      } else if (isConcluido) {
        completedList.push(item);
      } else if (hasExpedicao) {
        closingList.push(item);
      } else {
        pendingList.push(item);
      }
    });

    matchesList.sort((a, b) => {
      if (a.trilha === 'PRINCIPAL' && b.trilha !== 'PRINCIPAL') return -1;
      if (a.trilha !== 'PRINCIPAL' && b.trilha === 'PRINCIPAL') return 1;
      return sortByPrazo(a, b);
    });
    pendingList.sort(sortByPrazo);
    closingList.sort(sortByPrazo);
    completedList.sort(sortByPrazo);

    return { matches: matchesList, pending: pendingList, closing: closingList, completed: completedList };
  }, [items, filterTrilha]);

  const handleRetirada = async (demandaId, itemId, maxMatch) => {
    if (maxMatch <= 0) return;

    const qty = prompt(`Quantidade a retirar (Máximo: ${maxMatch}):`, maxMatch);
    const quantidade = parseInt(qty);

    if (isNaN(quantidade) || quantidade <= 0) return;
    if (quantidade > maxMatch) {
      toast.error('Quantidade superior ao match disponível.');
      return;
    }

    try {
      const response = await ProductionService.registrarRetiradaExpedicao(demandaId, itemId, quantidade);
      if (response.success) {
        toast.success('Retirada registrada!');
        fetchData();
      } else {
        toast.error(response.message);
      }
    } catch {
      toast.error('Erro ao registrar retirada.');
    }
  };

  if (loading && items.length === 0) {
    return <div className="flex justify-center items-center h-screen"><Loader2 className="animate-spin h-8 w-8" /></div>;
  }

  const renderMatchRow = (item) => (
    <div key={item.item_id} className="border rounded-lg bg-green-50/40 p-4 flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
      <div className="min-w-0">
        <div className="flex items-center gap-2 mb-1 flex-wrap">
          <Badge className="bg-green-600 text-white border-none">PRONTO PARA MONTAGEM</Badge>
          {item.trilha === 'LATERAL' && <Badge variant="outline" className="text-teal-600 border-teal-600">LATERAL</Badge>}
        </div>
        <div className="font-bold text-gray-900">{item.item_nome}</div>
        <div className="text-xs text-gray-600">{item.demanda_nome} | SKU: {item.sku}</div>
      </div>

      <div className="flex items-center gap-6">
        <div className="text-center">
          <div className="text-2xl font-black text-green-700">{item.match_disponivel}</div>
          <div className="text-[10px] uppercase tracking-wide text-gray-500">Unidades</div>
        </div>
        <Button
          size="sm"
          className="bg-green-600 hover:bg-green-700"
          onClick={() => handleRetirada(item.demanda_id, item.item_id, item.match_disponivel)}
        >
          Retirar <ArrowRight className="ml-1 h-4 w-4" />
        </Button>
      </div>
    </div>
  );

  const renderPendingRow = (item) => (
    <div key={item.item_id} className="border rounded-lg p-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2 mb-1 flex-wrap">
          <Badge variant="outline" className="text-gray-600 border-gray-300">Aguardando</Badge>
          {item.trilha === 'LATERAL' && <Badge variant="outline" className="text-teal-600 border-teal-200">LATERAL</Badge>}
        </div>
        <div className="font-semibold text-gray-800">{item.item_nome}</div>
        <div className="text-xs text-gray-500">{item.demanda_nome}</div>
      </div>
      <div className="flex items-center gap-5 text-sm">
        <div className={item.capas_prontas >= item.qtd_total ? 'text-green-700' : 'text-amber-700'}>
          Capas: <span className="font-bold">{item.capas_prontas}/{item.qtd_total}</span>
        </div>
        <div className={item.miolos_prontos >= item.qtd_total ? 'text-green-700' : 'text-amber-700'}>
          Miolos: <span className="font-bold">{item.miolos_prontos}/{item.qtd_total}</span>
        </div>
      </div>
    </div>
  );

  const renderClosingRow = (item) => {
    const expedidas = Math.min(item.expedicao_capas_retiradas_qtd || 0, item.expedicao_miolos_retirados_qtd || 0);
    const progresso = item.qtd_total > 0 ? Math.min(100, (expedidas / item.qtd_total) * 100) : 0;

    return (
      <div key={item.item_id} className="border rounded-lg p-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <Badge className="bg-orange-500 text-white border-none">EM FECHAMENTO</Badge>
            {item.trilha === 'LATERAL' && <Badge variant="outline" className="text-teal-600 border-teal-200">LATERAL</Badge>}
          </div>
          <div className="font-semibold text-gray-800">{item.item_nome}</div>
          <div className="text-xs text-gray-500">{item.demanda_nome}</div>
        </div>
        <div className="w-full md:w-64">
          <div className="text-sm font-semibold text-orange-700 mb-1">{expedidas}/{item.qtd_total} expedidas</div>
          <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
            <div className="h-full bg-orange-500" style={{ width: `${progresso}%` }} />
          </div>
        </div>
      </div>
    );
  };

  const renderCompletedRow = (item) => {
    const expedidas = Math.min(item.expedicao_capas_retiradas_qtd || 0, item.expedicao_miolos_retirados_qtd || 0);
    return (
      <div key={item.item_id} className="border rounded-lg p-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3 bg-green-50/30">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <Badge className="bg-green-600 text-white border-none">CONCLUÍDO</Badge>
            {item.trilha === 'LATERAL' && <Badge variant="outline" className="text-teal-600 border-teal-200">LATERAL</Badge>}
          </div>
          <div className="font-semibold text-gray-800">{item.item_nome}</div>
          <div className="text-xs text-gray-500">{item.demanda_nome}</div>
        </div>
        <div className="text-sm font-semibold text-green-700">{expedidas}/{item.qtd_total} expedidas</div>
      </div>
    );
  };

  const renderSection = ({ iconNode, title, count, emptyText, rows, className = '' }) => (
    <section className={className}>
      <div className="flex items-center gap-2 mb-3">
        {iconNode}
        <h2 className="text-lg font-bold">{title} ({count})</h2>
      </div>
      {rows.length === 0 ? (
        <div className="border-2 border-dashed rounded-lg px-4 py-6 text-sm text-gray-500 text-center">
          {emptyText}
        </div>
      ) : (
        <div className="space-y-3">{rows}</div>
      )}
    </section>
  );

  return (
    <div className="container mx-auto p-4 space-y-8">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Expedição</h1>
          <p className="text-muted-foreground">Sincronização de Capas e Miolos</p>
        </div>
        <div className="flex bg-gray-100 p-1 rounded-lg">
          <button
            onClick={() => setFilterTrilha('ALL')}
            className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${filterTrilha === 'ALL' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-500 hover:text-gray-900'}`}
          >
            Todos
          </button>
          <button
            onClick={() => setFilterTrilha('PRINCIPAL')}
            className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${filterTrilha === 'PRINCIPAL' ? 'bg-white shadow-sm text-blue-600' : 'text-gray-500 hover:text-gray-900'}`}
          >
            Prioridades
          </button>
          <button
            onClick={() => setFilterTrilha('LATERAL')}
            className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${filterTrilha === 'LATERAL' ? 'bg-white shadow-sm text-teal-600' : 'text-gray-500 hover:text-gray-900'}`}
          >
            Laterais
          </button>
        </div>
      </div>

      {renderSection({
        iconNode: <CheckCircle2 className="h-5 w-5 text-green-600" />,
        title: 'Prontos para Montagem',
        count: matches.length,
        emptyText: 'Nenhum match completo no momento. Aguarde a produção.',
        rows: matches.map(renderMatchRow),
      })}

      {renderSection({
        iconNode: <Package className="h-5 w-5 text-orange-600" />,
        title: 'Em Fechamento',
        count: closing.length,
        emptyText: 'Nenhum item em fechamento.',
        rows: closing.map(renderClosingRow),
      })}

      {renderSection({
        iconNode: <CheckCircle2 className="h-5 w-5 text-green-700" />,
        title: 'Concluídos',
        count: completed.length,
        emptyText: 'Nenhum item concluído para este filtro.',
        rows: completed.map(renderCompletedRow),
      })}

      {renderSection({
        iconNode: <Loader2 className="h-5 w-5 text-gray-400" />,
        title: 'Aguardando Peças',
        count: pending.length,
        emptyText: 'Nenhum item aguardando peças.',
        rows: pending.map(renderPendingRow),
      })}
    </div>
  );
};

export default ExpedicaoDashboardPage;
