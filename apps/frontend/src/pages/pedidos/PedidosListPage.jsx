import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  CheckCircle2,
  Upload
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import FiltrosPedidos from '@/components/pedidos/FiltrosPedidos';
import GerarDemandaModal from '@/components/pedidos/GerarDemandaModal';
import ImportModal from '@/components/pedidos/ImportModal';
import TabelaPedidos from '@/components/pedidos/TabelaPedidos';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

function PedidosListPage() {
  const navigate = useNavigate();

  // Estados principais
  const [pedidos, setPedidos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [estatisticas, setEstatisticas] = useState(null);

  // Estados de filtro
  const [filtros, setFiltros] = useState({
    search: '',
    status_id: null,
    canal_venda_id: null,
    has_demanda: null, // true, false, null
    is_flex: null,     // true, false, null - Filtro para pedidos Flex
    delivery_start: '',
    delivery_end: '',
  });

  // Estados de paginação
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(50);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);

  // Estados de seleção
  const [pedidosSelecionados, setPedidosSelecionados] = useState([]);

  // Estados de canais próximos (para highlight na tabela)
  const [canaisProximosIds, setCanaisProximosIds] = useState([]);

  // Estados de modais
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [gerarDemandaModalOpen, setGerarDemandaModalOpen] = useState(false);
  const [resultadosModalOpen, setResultadosModalOpen] = useState(false);

  // Estado de importação
  const [importando, setImportando] = useState(false);
  
  // Estados para resultados da consolidação
  const [resultadosConsolidacao, setResultadosConsolidacao] = useState(null);
  const [demandName, setDemandName] = useState('');

  // Carregar estatísticas com retry
  const carregarEstatisticas = async () => {
    try {
      const maxRetries = 3;
      let lastError = null;
      
      for (let attempt = 1; attempt <= maxRetries; attempt++) {
        try {
          // Normalizar URL (remover barra dupla se existir)
          const url = '/api/v2/pedidos/estatisticas?dias=30'.replace(/\/+/g, '/');
          const response = await fetch(url);
          const data = await response.json();
          if (data.success) {
            setEstatisticas(data.data);
            return;
          }
        } catch (error) {
          lastError = error;
          if (attempt < maxRetries) {
            await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
          }
        }
      }
      
      if (lastError) {
        console.error('Erro ao carregar estatísticas após retries:', lastError);
      }
    } catch (error) {
      console.error('Erro ao carregar estatísticas:', error);
    }
  };

  // Carregar canais próximos (para highlight e contexto)
  const carregarCanaisProximos = async () => {
    try {
      const response = await fetch('/api/v2/pedidos/canais-proximos-coleta');
      const data = await response.json();
      if (data.success) {
        const ids = (data.data.canais_proximos || []).map(c => c.id);
        setCanaisProximosIds(ids);
      }
    } catch (error) {
      console.error('Erro ao carregar canais próximos:', error);
    }
  };

  // Carregar pedidos
  const carregarPedidos = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: page.toString(),
        limit: limit.toString(),
        sort: 'numero_pedido',
        order: 'desc',
      });

      // Adicionar apenas filtros não-nulos
      Object.entries(filtros).forEach(([key, value]) => {
        if (value !== null && value !== '') {
          params.append(key, value);
        }
      });

      const response = await fetch(`/api/v2/order/list-advanced?${params}`);
      const data = await response.json();

      if (data.success) {
        // API retorna: {success: true, data: {orders: [...], total: 985}}
        const responseData = data.data || {};
        const ordersData = responseData.orders || responseData.pedidos || [];
        const total = responseData.total || 0;
        
        // Mapear campos do backend para o formato esperado pelo frontend
        const pedidosMapeados = ordersData.map(order => ({
          id: order.id,
          numero_pedido: order.numero_pedido || order.numeroPedido || order.id,
          codigo_pedido_externo: order.codigo_pedido_externo || order.codigoPedidoExterno,
          data_venda: order.data_venda || order.dataVenda || order.created_at,
          cliente_nome: order.cliente_nome || order.clienteNome,
          cliente_documento: order.cliente_documento || order.clienteDocumento,
          canal_venda_nome: order.canal_venda_nome || order.canalVendaNome || order.canal?.nome,
          situacao_pedido_id: order.situacao_pedido_id || order.situacaoPedidoId,
          total_pedido: order.total_pedido || order.totalPedido || order.total,
          tem_demanda: order.tem_demanda || order.temDemanda || order.has_demanda || false,
          // NOVOS CAMPOS - Pedidos Flex
          is_flex: order.is_flex || false,
          data_limite_envio: order.data_limite_envio,
          enviar_ate_formatado: order.enviar_ate_formatado,
          // Status com cores dinâmicas
          status: order.status || {
            id: order.situacao_pedido_id,
            nome: order.situacao_nome,
            cor: order.situacao_cor,
          },
        }));
        
        setPedidos(pedidosMapeados);
        setTotal(total);
        // Calcular total de páginas
        setTotalPages(Math.ceil(total / limit));
      } else {
        toast.error(data.message || 'Erro ao carregar pedidos');
        setPedidos([]);
        setTotal(0);
        setTotalPages(0);
      }
    } catch (error) {
      console.error('Erro ao carregar pedidos:', error);
      toast.error('Erro ao carregar pedidos');
      setPedidos([]);
      setTotal(0);
      setTotalPages(0);
    } finally {
      setLoading(false);
    }
  };

  // Efeito: carregar dados iniciais
  useEffect(() => {
    carregarEstatisticas();
    carregarCanaisProximos();
  }, []);

  // Efeito: recarregar pedidos quando filtros mudam
  useEffect(() => {
    carregarPedidos();
  }, [page, limit, filtros]);

  // Handlers de filtro
  const handleFiltroChange = (novoFiltro) => {
    setFiltros(prev => ({ ...prev, ...novoFiltro }));
    setPage(1); // Resetar paginação
  };

  const handleLimparFiltros = () => {
    setFiltros({
      search: '',
      status_id: null,
      canal_venda_id: null,
      has_demanda: null,
      is_flex: null,
      delivery_start: '',
      delivery_end: '',
    });
    setPage(1);
  };

  // Handlers de seleção
  const handleSelecionarPedido = (pedidoId) => {
    setPedidosSelecionados(prev =>
      prev.includes(pedidoId)
        ? prev.filter(id => id !== pedidoId)
        : [...prev, pedidoId]
    );
  };

  const handleSelecionarTodos = () => {
    if (pedidosSelecionados.length === pedidos.length) {
      setPedidosSelecionados([]);
    } else {
      setPedidosSelecionados(pedidos.map(p => p.id));
    }
  };

  // Handlers de importação
  const handleImportarBling = async (config) => {
    setImportando(true);
    try {
      const response = await fetch('/api/v2/pedidos/importar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...config,
          config_id: config.config_id === 'all' ? null : config.config_id,
          async: false, // Síncrono para mostrar resultado na tela
        }),
      });

      const data = await response.json();
      
      if (data.success) {
        const stats = data.data.result;
        if (stats && stats.totals) {
          const { orders_synced, errors, orders_listed } = stats.totals;
          toast.success(
            `Importação concluída: ${orders_synced} pedidos sincronizados de ${orders_listed} encontrados. ${errors > 0 ? `(${errors} erros)` : ''}`
          );
        } else {
          toast.success(data.data.message || 'Importação concluída!');
        }
        
        setImportModalOpen(false);
        carregarPedidos();
        carregarEstatisticas();
      } else {
        toast.error(data.message || 'Erro ao importar pedidos');
      }
    } catch (error) {
      console.error('Erro ao importar:', error);
      toast.error('Erro ao importar pedidos');
    } finally {
      setImportando(false);
    }
  };

  const handleUploadPlanilha = async (file, options) => {
    setImportando(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('channel', options.canal);
      
      if (options.startDate) formData.append('start_date', options.startDate);
      // Usar end_datetime igual à ConsolidarPage
      if (options.endDate) formData.append('end_datetime', options.endDate);
      formData.append('print_orders', options.printOrders ? 'true' : 'false');
      formData.append('is_flex', options.isFlex ? 'true' : 'false');

      const response = await fetch('/api/v2/pedidos/upload-planilha', {
        method: 'POST',
        body: formData,
      });

      const data = await response.json();

      if (response.ok && data) {
        setImportModalOpen(false);
        // Processamento SÍNCRONO: resultados já estão disponíveis
        // O endpoint retorna os dados diretamente (igual /consolidar)
        const processedResult = processarResultData(data);
        setResultadosConsolidacao(processedResult);
        setDemandName(`Demanda - ${new Date().toLocaleDateString('pt-BR')}`);
        setResultadosModalOpen(true);
        toast.success('Planilha processada com sucesso!');
      } else {
        toast.error(data.message || data.error || 'Erro ao processar planilha');
      }
    } catch (error) {
      console.error('Erro ao upload:', error);
      toast.error('Erro ao processar planilha');
    } finally {
      setImportando(false);
    }
  };

  const processarResultData = (result) => {
    const processed = {};
    for (const [platform, platformData] of Object.entries(result)) {
      const capasMiolosData = platformData.capas_miolos_data?.map(item => ({
        ...item,
        pedidos_origem: item.pedidos_origem || (item.order_refs?.map(ref => ({
          codigo_pedido_externo: ref,
          numero_pedido: null
        })) || [])
      })) || [];

      processed[platform] = {
        ...platformData,
        capas_miolos_data: capasMiolosData
      };
    }
    return processed;
  };

  // Handlers de demanda
  const handleGerarDemanda = async (dadosDemanda) => {
    try {
      const response = await fetch('/api/v2/pedidos/gerar-demanda-consolidada', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pedido_ids: pedidosSelecionados,
          ...dadosDemanda,
        }),
      });

      const data = await response.json();
      
      if (data.success) {
        toast.success(data.data.message || 'Demanda consolidada criada!');
        setGerarDemandaModalOpen(false);
        setPedidosSelecionados([]);
        // Recarregar para atualizar indicadores de demanda
        carregarPedidos();
        carregarEstatisticas();
        
        // Redirecionar para a demanda criada (usar demanda_id numérico)
        if (data.data.demanda_id) {
          setTimeout(() => {
            navigate(`/producao/demanda/${data.data.demanda_id}/dashboard`);
          }, 1000);
        }
      } else {
        toast.error(data.message || 'Erro ao gerar demanda');
      }
    } catch (error) {
      console.error('Erro ao gerar demanda:', error);
      toast.error('Erro ao gerar demanda');
    }
  };

  return (
    <div className="flex flex-col w-full max-w-7xl mx-auto pb-20">
      {/* Header */}
      <div className="flex justify-between items-center mb-8 bg-white p-4 rounded-lg border shadow-sm">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Pedidos</h1>
          <p className="text-muted-foreground">
            Gerencie pedidos e gere demandas de produção
          </p>
        </div>
        
        <div className="flex gap-3">
          {estatisticas && (
            <Card className="p-3 min-w-[200px]">
              <div className="flex justify-between items-center">
                <div className="text-sm">
                  <div className="text-muted-foreground">Sem Demanda</div>
                  <div className="text-2xl font-bold text-red-600">
                    {estatisticas.pedidos_sem_demanda}
                  </div>
                </div>
                <div className="text-sm">
                  <div className="text-muted-foreground">Com Demanda</div>
                  <div className="text-2xl font-bold text-green-600">
                    {estatisticas.pedidos_com_demanda}
                  </div>
                </div>
              </div>
            </Card>
          )}
          
          <Button
            variant="default"
            onClick={() => setImportModalOpen(true)}
            className="gap-2"
          >
            <Upload className="h-4 w-4" />
            Importar
          </Button>
        </div>
      </div>

      {/* Filtros */}
      <FiltrosPedidos
        filtros={filtros}
        onFiltroChange={handleFiltroChange}
        onLimparFiltros={handleLimparFiltros}
      />

      {/* Ações em lote */}
      {pedidosSelecionados.length > 0 && (
        <Card className="mb-4 bg-primary/5 border-primary/20">
          <CardContent className="py-3 flex justify-between items-center">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-primary" />
              <span className="font-medium">
                {pedidosSelecionados.length} pedido(s) selecionado(s)
              </span>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPedidosSelecionados([])}
              >
                Limpar seleção
              </Button>
              <Button
                size="sm"
                onClick={() => setGerarDemandaModalOpen(true)}
                className="bg-green-600 hover:bg-green-700"
              >
                📊 Gerar Demanda ({pedidosSelecionados.length})
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Tabela de Pedidos */}
      <TooltipProvider>
        <TabelaPedidos
          pedidos={pedidos}
          loading={loading}
          pedidosSelecionados={pedidosSelecionados}
          onSelecionarPedido={handleSelecionarPedido}
          onSelecionarTodos={handleSelecionarTodos}
          page={page}
          limit={limit}
          total={total}
          onPageChange={setPage}
          onLimitChange={setLimit}
          canaisProximosIds={canaisProximosIds}
        />
      </TooltipProvider>

      {/* Modais */}
      <ImportModal
        open={importModalOpen}
        onOpenChange={setImportModalOpen}
        onImportarBling={handleImportarBling}
        onUploadPlanilha={handleUploadPlanilha}
        importando={importando}
      />

      <GerarDemandaModal
        open={gerarDemandaModalOpen}
        onOpenChange={setGerarDemandaModalOpen}
        onGerarDemanda={handleGerarDemanda}
        quantidadePedidos={pedidosSelecionados.length}
      />

      {/* NOVO: Modal de Resultados da Consolidação (igual à ConsolidarReviewPage) */}
      {resultadosModalOpen && (
        <ResultadosConsolidacaoModal
          open={resultadosModalOpen}
          onOpenChange={setResultadosModalOpen}
          resultados={resultadosConsolidacao}
          demandName={demandName}
          onGerarDemanda={async (dadosDemanda) => {
            try {
              const response = await fetch('/api/v2/demanda_producao/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  ...dadosDemanda,
                  itens: Object.values(resultadosConsolidacao)[0]?.capas_miolos_data?.map(item => ({
                    sku: item.sku,
                    descricao: item.descricao,
                    quantidade: item.quantidade,
                    pedidos_origem: item.pedidos_origem
                  })) || []
                })
              });

              if (response.ok) {
                toast.success('Demanda criada com sucesso!');
                setResultadosModalOpen(false);
                carregarPedidos();
                carregarEstatisticas();
              } else {
                const error = await response.json();
                throw new Error(error.message);
              }
            } catch (error) {
              toast.error(error.message || 'Erro ao criar demanda');
            }
          }}
        />
      )}
    </div>
  );
}

export default PedidosListPage;

// NOVO: Componente Modal de Resultados (inline para evitar importação complexa)
function ResultadosConsolidacaoModal({ open, onOpenChange, resultados, demandName, onGerarDemanda }) {
  const [nome, setNome] = useState(demandName);
  const [dataEntrega, setDataEntrega] = useState(new Date().toISOString().split('T')[0]);
  const [horarioColeta, setHorarioColeta] = useState('');
  const [observacoes, setObservacoes] = useState('');
  const [canalSelecionado, setCanalSelecionado] = useState('');
  const [canais, setCanais] = useState([]);
  const [criando, setCriando] = useState(false);

  // Carregar canais ao abrir modal
  useEffect(() => {
    if (open) {
      fetch('/api/v2/cadastros/canal-venda?active_only=true')
        .then(res => res.json())
        .then(data => {
          if (data.canais) {
            setCanais(data.canais);
            if (data.canais.length > 0) {
              setCanalSelecionado(String(data.canais[0].id));
            }
          }
        });
    }
  }, [open]);

  // Extrair dados da primeira plataforma
  const plataformaData = Object.values(resultados || {})[0];
  const capasMiolos = plataformaData?.capas_miolos_data || [];
  const totalCapas = plataformaData?.total_capas || 0;
  const totalMiolos = plataformaData?.total_miolos || 0;
  const totalPedidos = plataformaData?.total_pedidos_plataforma || 0;

  const handleGerar = async () => {
    if (!nome || !dataEntrega || !canalSelecionado) {
      toast.error('Preencha nome, canal de venda e data de entrega');
      return;
    }

    setCriando(true);
    try {
      await onGerarDemanda({
        nome,
        canal_venda_id: parseInt(canalSelecionado),
        data_entrega: dataEntrega,
        horario_coleta: horarioColeta || null,
        observacoes
      });
    } finally {
      setCriando(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-background rounded-lg max-w-4xl w-full max-h-[90vh] overflow-y-auto">
        <div className="p-6 border-b">
          <h2 className="text-2xl font-bold">Revisão da Consolidação</h2>
          <p className="text-muted-foreground">Revise os pedidos e itens antes de criar a demanda</p>
        </div>

        <div className="p-6 space-y-6">
          {/* Resumo */}
          <div className="grid grid-cols-3 gap-4">
            <Card>
              <CardContent className="pt-6">
                <div className="text-2xl font-bold">{totalPedidos}</div>
                <p className="text-xs text-muted-foreground">pedidos processados</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="text-2xl font-bold">{totalCapas}</div>
                <p className="text-xs text-muted-foreground">capas</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="text-2xl font-bold">{totalMiolos}</div>
                <p className="text-xs text-muted-foreground">miolos</p>
              </CardContent>
            </Card>
          </div>

          {/* Itens consolidados */}
          <Card>
            <CardHeader>
              <CardTitle>Itens para Produção ({capasMiolos.length})</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>SKU</TableHead>
                    <TableHead>Descrição</TableHead>
                    <TableHead className="text-right">Qtd</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {capasMiolos.map((item, idx) => (
                    <TableRow key={idx}>
                      <TableCell className="font-mono text-sm">{item.sku || '-'}</TableCell>
                      <TableCell className="text-sm">{item.descricao}</TableCell>
                      <TableCell className="text-right font-bold">{item.quantidade}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {/* Formulário */}
          <Card>
            <CardHeader>
              <CardTitle>Dados da Demanda</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="nome-demanda">Nome da Demanda *</Label>
                <Input
                  id="nome-demanda"
                  value={nome}
                  onChange={(e) => setNome(e.target.value)}
                  placeholder="Ex: Demanda Shopee - Março/2026"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="canal-venda">Canal de Venda *</Label>
                <Select value={canalSelecionado} onValueChange={setCanalSelecionado}>
                  <SelectTrigger>
                    <SelectValue placeholder="Selecione o canal" />
                  </SelectTrigger>
                  <SelectContent>
                    {canais.map((canal) => (
                      <SelectItem key={canal.id} value={String(canal.id)}>
                        {canal.nome}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="data-entrega">Data de Entrega *</Label>
                <Input
                  id="data-entrega"
                  type="date"
                  value={dataEntrega}
                  onChange={(e) => setDataEntrega(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="horario-coleta">Horário de Coleta</Label>
                <Input
                  id="horario-coleta"
                  type="time"
                  value={horarioColeta}
                  onChange={(e) => setHorarioColeta(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="obs">Observações</Label>
                <Textarea
                  id="obs"
                  value={observacoes}
                  onChange={(e) => setObservacoes(e.target.value)}
                  placeholder="Observações adicionais..."
                  rows={3}
                />
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="p-6 border-t flex gap-2 justify-end">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button
            onClick={handleGerar}
            disabled={criando || !nome || !dataEntrega}
            className="bg-green-600 hover:bg-green-700"
          >
            {criando ? 'Criando...' : 'Confirmar e Criar Demanda'}
          </Button>
        </div>
      </div>
    </div>
  );
}
