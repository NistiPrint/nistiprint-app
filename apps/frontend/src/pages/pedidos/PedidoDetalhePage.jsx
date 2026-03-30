import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Loader2 } from 'lucide-react';
import * as pedidoService from '@/services/pedidoService';
import PedidoHeader from '@/components/pedidos/PedidoHeader';
import PedidoResumoCards from '@/components/pedidos/PedidoResumoCards';
import PedidoItensList from '@/components/pedidos/PedidoItensList';
import PedidoIntegracoesCard from '@/components/pedidos/PedidoIntegracoesCard';
import PedidoTimeline from '@/components/pedidos/PedidoTimeline';
import PedidoDemandaCard from '@/components/pedidos/PedidoDemandaCard';

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

  useEffect(() => {
    carregarPedido();
    carregarDemandas();
  }, [id]);

  async function carregarPedido() {
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
  }

  async function carregarDemandas() {
    try {
      const dados = await pedidoService.getPedidoDemandas(parseInt(id));
      setDemandas(dados.demandas || []);
    } catch (err) {
      console.error('Erro ao carregar demandas:', err);
    }
  }

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
            <PedidoTimeline eventos={pedido.timeline} />
          </div>
        </div>
      </div>
    </div>
  );
}
