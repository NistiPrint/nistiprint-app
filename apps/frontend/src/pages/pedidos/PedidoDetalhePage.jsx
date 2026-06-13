import PedidoDemandaCard from '@/components/pedidos/PedidoDemandaCard';
import PedidoHeader from '@/components/pedidos/PedidoHeader';
import PedidoLogsModal from '@/components/pedidos/PedidoLogsModal';
import PedidoIntegracoesCard from '@/components/pedidos/PedidoIntegracoesCard';
import PedidoItensList from '@/components/pedidos/PedidoItensList';
import PedidoPlatformFieldsCard from '@/components/pedidos/PedidoPlatformFieldsCard';
import PedidoTimeline from '@/components/pedidos/PedidoTimeline';
import PedidoResumoCards from '@/components/pedidos/PedidoResumoCards';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import * as pedidoService from '@/services/pedidoService';
import { formatAppDateTime } from '@/lib/dateTime';
import {
  CalendarClock,
  Clock3,
  Loader2,
  Package,
  Truck,
  Warehouse
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';

function formatValue(value) {
  return value ? formatAppDateTime(value) : 'Não informado';
}

function InfoLine({ label, value, mono = false }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border/60 py-3 last:border-b-0">
      <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className={`max-w-[70%] text-right text-sm ${mono ? 'font-mono' : 'font-medium'}`}>
        {value || 'Não informado'}
      </span>
    </div>
  );
}

function DateCard({ icon: Icon, label, value, hint, tone = 'text-muted-foreground' }) {
  return (
    <Card className="h-full">
      <CardContent className="pt-6">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-2">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
            <p className="text-lg font-semibold">{value || 'Não informado'}</p>
            {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
          </div>
          <div className={`rounded-full bg-muted p-2 ${tone}`}>
            <Icon className="h-4 w-4" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function OperacaoCard({ pedido }) {
  const logistica = pedido.logistica || {};
  const timestamps = useMemo(() => {
    const snapshot = pedido.snapshot?.logistics || {};
    return {
      compra: pedido.data_compra_marketplace || snapshot.purchase_at,
      pagamento: pedido.data_pagamento_marketplace || snapshot.payment_at,
      coleta: pedido.data_coleta || snapshot.collection_at,
      envio: pedido.data_envio_marketplace || snapshot.marketplace_shipped_at,
      limite: pedido.data_limite_envio || snapshot.deadline || snapshot.ship_by_date || snapshot.expected_date,
    };
  }, [pedido]);

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-lg">
          <CalendarClock className="h-5 w-5" />
          Linha do tempo operacional
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        <InfoLine label="Compra" value={formatValue(timestamps.compra)} mono />
        <InfoLine label="Pagamento" value={formatValue(timestamps.pagamento)} mono />
        <InfoLine label="Coleta" value={formatValue(timestamps.coleta)} mono />
        <InfoLine label="Envio" value={formatValue(timestamps.envio)} mono />
        <InfoLine label="Limite de envio" value={formatValue(timestamps.limite)} mono />
        <div className="pt-3 flex flex-wrap gap-2">
          {logistica?.is_flex && <Badge className="bg-amber-500 text-white">FLEX</Badge>}
          {logistica?.servico_logistico && <Badge variant="outline">{logistica.servico_logistico}</Badge>}
          {pedido.is_personalizado && <Badge variant="outline">Personalizado</Badge>}
        </div>
      </CardContent>
    </Card>
  );
}

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
    navigate('/vendas/pedidos', { replace: true });
  }

  function handlePrint() {
    toast.info('Funcionalidade de impressão em desenvolvimento');
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
          <Loader2 className="mx-auto h-12 w-12 animate-spin text-primary" />
          <p className="text-muted-foreground">Carregando pedido...</p>
        </div>
      </div>
    );
  }

  if (error || !pedido) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="max-w-md space-y-4 text-center">
          <h2 className="text-2xl font-bold">Pedido não encontrado</h2>
          <p className="text-muted-foreground">{error || 'Não foi possível carregar os detalhes do pedido.'}</p>
          <div className="flex justify-center gap-2">
            <button onClick={() => navigate('/vendas/pedidos')} className="rounded-md bg-primary px-4 py-2 text-primary-foreground hover:bg-primary/90">
              Voltar para lista
            </button>
            <button onClick={carregarPedido} className="rounded-md border px-4 py-2 hover:bg-muted">
              Tentar novamente
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="container mx-auto max-w-7xl px-4 py-8">
        <PedidoHeader
          pedido={pedido}
          onBack={handleBack}
          onPrint={handlePrint}
          onShare={handleShare}
          onOpenLogs={handleOpenLogs}
          onReprocess={handleReprocess}
          isReprocessing={isReprocessing}
        />

        <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <DateCard
            icon={Package}
            label="Compra"
            value={formatValue(pedido.data_compra_marketplace || pedido.datas?.venda)}
            hint="Data/hora de criação do pedido"
          />
          <DateCard
            icon={Clock3}
            label="Pagamento"
            value={formatValue(pedido.data_pagamento_marketplace)}
            hint="Usada para validar a hora de corte"
          />
          <DateCard
            icon={Warehouse}
            label="Coleta"
            value={formatValue(pedido.data_coleta)}
            hint="Coleta pela transportadora ou ponto"
          />
          <DateCard
            icon={Truck}
            label="Envio"
            value={formatValue(pedido.data_envio_marketplace)}
            hint="Bipagem no marketplace"
          />
        </div>

        <PedidoResumoCards pedido={pedido} />

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.4fr_0.9fr]">
          <div className="space-y-6">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-lg">Itens do pedido</CardTitle>
              </CardHeader>
              <CardContent>
                <PedidoItensList itens={pedido.itens} />
              </CardContent>
            </Card>

            <PedidoTimeline
              eventos={pedido.timeline}
              pedidoId={pedido.id}
              codigoPedidoExterno={pedido.codigo_pedido_externo}
              onReprocess={carregarPedido}
            />
          </div>

          <div className="space-y-6">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-lg">Resumo operacional</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1">
                <InfoLine label="Pedido interno" value={`#${pedido.numero_pedido}`} mono />
                <InfoLine label="Pedido externo" value={pedido.codigo_pedido_externo} mono />
                <InfoLine label="Cliente" value={pedido.cliente?.nome} />
                <InfoLine label="Documento" value={pedido.cliente?.documento} mono />
                <InfoLine label="Canal" value={pedido.logistica?.canal_venda?.nome} />
                <InfoLine label="Status" value={pedido.statusFormatado?.nome} />
                <InfoLine label="Data da venda" value={formatValue(pedido.datas?.venda)} mono />
                <InfoLine label="Limite de envio" value={formatValue(pedido.data_limite_envio)} mono />
              </CardContent>
            </Card>

            <OperacaoCard pedido={pedido} />

            <PedidoDemandaCard
              pedidoId={pedido.id}
              demandas={demandas}
              onRefresh={carregarDemandas}
            />

            <PedidoIntegracoesCard integracoes={pedido.integracoes} />
            <PedidoPlatformFieldsCard pedido={pedido} />
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
