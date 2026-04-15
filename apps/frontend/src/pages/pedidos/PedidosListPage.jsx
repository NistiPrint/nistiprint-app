import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  CheckCircle2,
  ClipboardList
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import FiltrosPedidos from '@/components/pedidos/FiltrosPedidos';
import GerarDemandaModal from '@/components/pedidos/GerarDemandaModal';
import TabelaPedidos from '@/components/pedidos/TabelaPedidos';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import { TooltipProvider } from '@/components/ui/tooltip';

function PedidosListPage() {
  const navigate = useNavigate();

  // Estados principais
  const [pedidos, setPedidos] = useState([]);
  const [loading, setLoading] = useState(true);

  // Estados de filtro
  const [filtros, setFiltros] = useState({
    search: '',
    status_id: null,
    canal_venda_id: null,
    has_demanda: null, // true, false, null
    is_flex: null,     // true, false, null - Filtro para pedidos Flex
    is_personalizado: null, // true, false, null - Filtro para pedidos personalizados
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

  // Estados de canais próximos (para highlight e contexto)
  const [canaisProximosIds, setCanaisProximosIds] = useState([]);
  const [channels, setChannels] = useState([]);
  const [canalInfo, setCanalInfo] = useState({ id: null, nome: null, horario_coleta: null });

  // Estados de modais
  const [gerarDemandaModalOpen, setGerarDemandaModalOpen] = useState(false);
  const [resultadosModalOpen, setResultadosModalOpen] = useState(false);
  const [alterarSituacaoModalOpen, setAlterarSituacaoModalOpen] = useState(false);
  const [statusOpcoes, setStatusOpcoes] = useState([]);

  // Carregar canais de venda
  const carregarCanais = async () => {
    try {
      const response = await fetch('/api/v2/cadastros/canal-venda?active_only=true');
      const data = await response.json();
      if (data.canais) setChannels(data.canais);
    } catch (error) {
      console.error('Erro ao carregar canais:', error);
    }
  };

  // Estados para resultados da consolidação
  const [resultadosConsolidacao, setResultadosConsolidacao] = useState(null);
  const [demandName, setDemandName] = useState('');


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

  // Carregar opções de status
  const carregarStatusOpcoes = async () => {
    try {
      const response = await fetch('/api/v2/pedidos/status-opcoes');
      const data = await response.json();
      if (data.success) {
        setStatusOpcoes(data.data.status || []);
      }
    } catch (error) {
      console.error('Erro ao carregar status:', error);
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
          demanda_id: order.demanda_id || order.demandaId || null,  // ID da demanda (se houver)
          demanda_numero: order.demanda_numero || null,  // Número da demanda (se houver)
          demanda_status: order.demanda_status || null,  // Status da demanda (se houver)
          total_demandas: order.total_demandas || 0,  // Total de demandas vinculadas
          demandas: order.demandas || [],  // Array de demandas associadas (para rascunhos)
          // NOVOS CAMPOS - Pedidos Flex
          is_flex: order.is_flex || false,
          is_personalizado: order.is_personalizado || false,
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
    carregarCanaisProximos();
    carregarStatusOpcoes();
    carregarCanais();
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
      is_personalizado: null,
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

  // Validar canais dos pedidos selecionados antes de abrir modal
  const handleOpenGerarDemandaModal = () => {
    if (pedidosSelecionados.length === 0) {
      toast.error('Selecione pelo menos um pedido');
      return;
    }

    // Buscar pedidos selecionados
    const pedidosSelecionadosData = pedidos.filter(p => pedidosSelecionados.includes(p.id));
    
    // Verificar se todos os pedidos são do mesmo canal
    const canaisUnicos = new Set();
    pedidosSelecionadosData.forEach(pedido => {
      if (pedido.canal_venda_id) {
        canaisUnicos.add(pedido.canal_venda_id);
      } else if (pedido.canal_venda_nome) {
        // Fallback: usar nome se ID não estiver disponível
        const canal = channels.find(c => c.nome === pedido.canal_venda_nome);
        if (canal) canaisUnicos.add(canal.id);
      }
    });

    if (canaisUnicos.size === 0) {
      toast.error('Os pedidos selecionados não possuem canal de venda definido');
      return;
    }

    if (canaisUnicos.size > 1) {
      toast.error('Selecione pedidos de apenas um canal de venda para gerar demanda');
      return;
    }

    // Todos os pedidos são do mesmo canal
    const canalId = Array.from(canaisUnicos)[0];
    const canal = channels.find(c => c.id === canalId);
    
    if (!canal) {
      toast.error('Canal de venda não encontrado');
      return;
    }

    setCanalInfo({
      id: canal.id,
      nome: canal.nome,
      horario_coleta: canal.horario_coleta || ''
    });
    setGerarDemandaModalOpen(true);
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

  // Handler para alterar situação em massa
  const handleAlterarSituacao = async (situacaoId, observacoes) => {
    try {
      const response = await fetch('/api/v2/pedidos/bulk-update-status', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pedido_ids: pedidosSelecionados,
          situacao_pedido_id: situacaoId,
          observacoes,
        }),
      });

      const data = await response.json();
      
      if (data.success) {
        toast.success(data.message || 'Situação alterada com sucesso!');
        setAlterarSituacaoModalOpen(false);
        setPedidosSelecionados([]);
        carregarPedidos();
      } else {
        toast.error(data.message || 'Erro ao alterar situação');
      }
    } catch (error) {
      console.error('Erro ao alterar situação:', error);
      toast.error('Erro ao alterar situação');
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
          <Button
            variant="outline"
            onClick={() => navigate('/producao/demanda/rascunhos')}
            className="gap-2"
          >
            <ClipboardList className="h-4 w-4" />
            ver rascunhos
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
                variant="outline"
                size="sm"
                onClick={() => setAlterarSituacaoModalOpen(true)}
              >
                Alterar Situação
              </Button>
              <Button
                size="sm"
                onClick={handleOpenGerarDemandaModal}
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


      <GerarDemandaModal
        open={gerarDemandaModalOpen}
        onOpenChange={setGerarDemandaModalOpen}
        onGerarDemanda={handleGerarDemanda}
        quantidadePedidos={pedidosSelecionados.length}
        canalVendaId={canalInfo.id}
        canalVendaNome={canalInfo.nome}
        horarioColetaInicial={canalInfo.horario_coleta}
      />

      <AlterarSituacaoModal
        open={alterarSituacaoModalOpen}
        onOpenChange={setAlterarSituacaoModalOpen}
        statusOpcoes={statusOpcoes}
        onAlterar={handleAlterarSituacao}
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

// Componente Modal de Alteração de Situação em Massa
function AlterarSituacaoModal({ open, onOpenChange, statusOpcoes, onAlterar, quantidadePedidos }) {
  const [situacaoSelecionada, setSituacaoSelecionada] = useState('');
  const [observacoes, setObservacoes] = useState('');
  const [alterando, setAlterando] = useState(false);

  const handleAlterar = async () => {
    if (!situacaoSelecionada) {
      toast.error('Selecione uma situação');
      return;
    }

    setAlterando(true);
    try {
      await onAlterar(parseInt(situacaoSelecionada), observacoes);
      setSituacaoSelecionada('');
      setObservacoes('');
    } finally {
      setAlterando(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-background rounded-lg max-w-md w-full">
        <div className="p-6 border-b">
          <h2 className="text-2xl font-bold">Alterar Situação em Massa</h2>
          <p className="text-muted-foreground">
            {quantidadePedidos} pedido(s) selecionado(s)
          </p>
        </div>

        <div className="p-6 space-y-4">
          <div className="space-y-2">
            <Label htmlFor="situacao">Nova Situação *</Label>
            <Select value={situacaoSelecionada} onValueChange={setSituacaoSelecionada}>
              <SelectTrigger id="situacao">
                <SelectValue placeholder="Selecione a situação" />
              </SelectTrigger>
              <SelectContent>
                {statusOpcoes.map((status) => (
                  <SelectItem key={status.id} value={String(status.id)}>
                    <div className="flex items-center gap-2">
                      <div
                        className="w-3 h-3 rounded-full"
                        style={{ backgroundColor: status.cor_status }}
                      />
                      {status.nome}
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="obs">Observações</Label>
            <Textarea
              id="obs"
              value={observacoes}
              onChange={(e) => setObservacoes(e.target.value)}
              placeholder="Observações sobre a alteração..."
              rows={3}
            />
          </div>
        </div>

        <div className="p-6 border-t flex gap-2 justify-end">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button
            onClick={handleAlterar}
            disabled={alterando || !situacaoSelecionada}
          >
            {alterando ? 'Alterando...' : 'Confirmar Alteração'}
          </Button>
        </div>
      </div>
    </div>
  );
}
