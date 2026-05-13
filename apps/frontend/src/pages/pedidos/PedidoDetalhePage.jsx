import PedidoDemandaCard from '@/components/pedidos/PedidoDemandaCard';
import PedidoHeader from '@/components/pedidos/PedidoHeader';
import PedidoLogsModal from '@/components/pedidos/PedidoLogsModal';
import PedidoIntegracoesCard from '@/components/pedidos/PedidoIntegracoesCard';
import PedidoItensList from '@/components/pedidos/PedidoItensList';
import PedidoResumoCards from '@/components/pedidos/PedidoResumoCards';
import PedidoTimeline from '@/components/pedidos/PedidoTimeline';
import * as pedidoService from '@/services/pedidoService';
import { Loader2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';

/**
 * Página de Detalhe do Pedido
 * Rota: /pedidos/:id
 */
export default function PedidoDetalhePage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [pedido, setPedido] = useState(null);
  const [demandas, setDemandas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isLogsOpen, setIsLogsOpen] = useState(false);
  const [isReprocessing, setIsReprocessing] = useState(false);

  const carregarPedido = useCallback(async () => {
    setLoading(true);
    setError(null);
    
    try {
      const dados = await pedidoService.getPedidoDetalhe(parseInt(id));
      if (dados) {
        setPedido(pedidoService.formatarPedido(dados));
      } else {
        setError('Pedido não encontrado');
        toast.error('Pedido não encontrado');
      }
    } catch (err) {
      console.error('Erro ao carregar pedido:', err);
      setError(err.message || 'Erro ao carregar pedido');
      toast.error('Erro ao carregar detalhes do pedido');
    } finally {
      setLoading(false);
    }
  }, [id]);

  const carregarDemandas = useCallback(async () => {
    try {
      const dados = await pedidoService.getPedidoDemandas(parseInt(id));
      setDemandas(dados?.demandas || []);
    } catch (err) {
      console.error('Erro ao carregar demandas:', err);
      setDemandas([]);
    }
  }, [id]);

  useEffect(() => {
    carregarPedido();
    carregarDemandas();
  }, [carregarPedido, carregarDemandas]);

  function handleBack() {
    console.log('Voltando para lista de pedidos...');
    navigate('/pedidos', { replace: true });
  }

  function handlePrint() {
    toast.info('Funcionalidade de impressão em desenvolvimento');
    // Futuro: gerar PDF ou abrir janela de impressão
  }

  function handleShare() {
    toast.info('Funcionalidade de compartilhamento em desenvolvimento');
  }

  function handleOpenLogs() {
    setIsLogsOpen(true);
  }

  async function handleReprocess() {
    if (!pedido?.id) return;

    setIsReprocessing(true);
    try {
      const result = await pedidoService.reprocessarPedido(pedido.id);
      if (result.success) {
        toast.success(result.message || 'Pedido reprocessado com sucesso');
        await carregarPedido();
        await carregarDemandas();
      } else {
        toast.error(result.error || result.message || 'Erro ao reprocessar pedido');
      }
    } catch (err) {
      toast.error(err.message || 'Erro ao reprocessar pedido');
    } finally {
      setIsReprocessing(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-center space-y-4">
          <Loader2 className="w-12 h-12 animate-spin text-primary mx-auto" />
          <p className="text-muted-foreground">Carregando pedido...</p>
        </div>
      </div>
    );
  }

  if (error || !pedido) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-center space-y-4 max-w-md">
          <h2 className="text-2xl font-bold">Pedido não encontrado</h2>
          <p className="text-muted-foreground">
            {error || 'Não foi possível carregar os detalhes do pedido.'}
          </p>
          <div className="flex gap-2 justify-center">
            <button
              onClick={() => navigate('/pedidos')}
              className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
            >
              Voltar para Lista
            </button>
            <button
              onClick={carregarPedido}
              className="px-4 py-2 border rounded-md hover:bg-muted"
            >
              Tentar Novamente
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="container mx-auto py-8 px-4 max-w-7xl">
        {/* Cabeçalho */}
        <PedidoHeader 
          pedido={pedido}
          onBack={handleBack}
          onPrint={handlePrint}
          onShare={handleShare}
          onOpenLogs={handleOpenLogs}
          onReprocess={handleReprocess}
          isReprocessing={isReprocessing}
        />

        {/* Cards de Resumo */}
        <PedidoResumoCards pedido={pedido} />

        {/* Grid Principal */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Coluna Principal (2/3) */}
          <div className="lg:col-span-2 space-y-6">
            {/* Itens do Pedido */}
            <PedidoItensList itens={pedido.itens} />
          </div>

          {/* Coluna Lateral (1/3) */}
          <div className="space-y-6">
            {/* Demanda Vinculada */}
            <PedidoDemandaCard 
              pedidoId={pedido.id} 
              demandas={demandas}
              onRefresh={carregarDemandas}
            />
            
            {/* Integrações */}
            <PedidoIntegracoesCard integracoes={pedido.integracoes} />
            
            {/* Timeline */}
            <PedidoTimeline
              eventos={pedido.timeline}
              pedidoId={pedido.id}
              codigoPedidoExterno={pedido.codigo_pedido_externo}
              onReprocess={carregarPedido}
            />
          </div>
        </div>
      </div>

      <PedidoLogsModal
        open={isLogsOpen}
        onOpenChange={setIsLogsOpen}
        pedidoId={pedido?.id}
        pedido={pedido}
      />
    </div>
  );
}
