import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { useRascunhos } from '@/lib/hooks/useRascunhos';
import { cn } from '@/lib/utils';
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  FileSpreadsheet,
  Filter,
  RefreshCw,
  ShoppingBag,
  Zap
} from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import RascunhoCard from '../../components/consolidar/RascunhoCard';
import VerNovosPedidosModal from '../../components/consolidar/VerNovosPedidosModal';

export default function RascunhosListPage() {
  const navigate = useNavigate();
  const {
    rascunhos,
    loading,
    error,
    refresh,
    publicarRascunho,
    editarRascunho,
    deletarRascunho,
    buscarPedidosNovos,
    confirmarPedidosNovos,
    processarPedidos,
  } = useRascunhos();

  const [filtro, setFiltro] = useState('todos');
  const [modalAberto, setModalAberto] = useState(false);
  const [demandaSelecionada, setDemandaSelecionada] = useState(null);

  // Filtrar rascunhos por estado
  const rascunhosFiltrados = rascunhos.filter((r) => {
    const estado =
      r.pedidos_apos_edicao_qtd > 0
        ? 'modificados'
        : r.editado_pelo_usuario
        ? 'editados'
        : 'limpos';

    if (filtro === 'todos') return true;
    return estado === filtro;
  });

  // Contadores
  const contadores = {
    todos: rascunhos.length,
    limpos: rascunhos.filter((r) => !r.editado_pelo_usuario && r.pedidos_apos_edicao_qtd === 0).length,
    editados: rascunhos.filter((r) => r.editado_pelo_usuario && r.pedidos_apos_edicao_qtd === 0).length,
    modificados: rascunhos.filter((r) => r.pedidos_apos_edicao_qtd > 0).length,
  };

  // Handlers
  const handlePublicar = async (id) => {
    if (!window.confirm('Publicar este rascunho como demanda?')) return;
    const sucesso = await publicarRascunho(id);
    if (sucesso) {
      navigate('/producao/demanda');
    }
  };

  const handleEditar = (id) => {
    navigate(`/consolidar/rascunhos/${id}/editar`);
  };

  const handleDeletar = async (id) => {
    const confirmado = await deletarRascunho(id);
    if (confirmado) {
      refresh();
    }
  };

  const handleVerNovos = (id) => {
    setDemandaSelecionada(id);
    setModalAberto(true);
  };

  const handleConfirmarPedidos = async (id) => {
    const sucesso = await confirmarPedidosNovos(id);
    if (sucesso) {
      setModalAberto(false);
      setDemandaSelecionada(null);
      refresh();
    }
    return sucesso;
  };

  const handleForcarConsolidacao = async () => {
    const confirm = window.confirm(
      'Processar pedidos sem demanda dos últimos 3 dias?\n\nEsta ação vai usar a mesma lógica de consolidação automática do webhook.'
    );
    if (!confirm) return;

    try {
      const resultado = await processarPedidos();
      toast.success(
        `${resultado.pedidos_processados} pedidos processados, ${resultado.rascunhos_criados} rascunhos criados!`
      );
    } catch (err) {
      toast.error(err.message || 'Erro ao processar pedidos');
    }
  };

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] gap-4">
        <AlertCircle className="h-12 w-12 text-red-500" />
        <div className="text-center">
          <h2 className="text-lg font-bold text-gray-900">Erro ao carregar rascunhos</h2>
          <p className="text-gray-500">{error}</p>
        </div>
        <Button onClick={refresh}>
          <RefreshCw className="h-4 w-4 mr-2" />
          Tentar Novamente
        </Button>
      </div>
    );
  }

  return (
    <TooltipProvider>
      <div className="container mx-auto py-8 pb-32">
        {/* Header */}
        <div className="flex justify-between items-start mb-8">
          <div>
            <h1 className="text-3xl font-bold tracking-tight mb-2">Rascunhos Automáticos</h1>
            <p className="text-muted-foreground">
              Demandas consolidadas automaticamente a partir de pedidos recebidos
            </p>
          </div>
          <div className="flex gap-2">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="outline"
                  onClick={handleForcarConsolidacao}
                  disabled={loading}
                  className="gap-2"
                >
                  <Zap className={cn("h-4 w-4", loading && "animate-spin")} />
                  Forçar Consolidação
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                Processar pedidos dos últimos 3 dias (mesma lógica do webhook)
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline" size="icon" onClick={refresh} disabled={loading}>
                  <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Atualizar lista</TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline" asChild>
                  <Link to="/consolidar">
                    <FileSpreadsheet className="h-4 w-4 mr-2" />
                    Consolidar Manual
                  </Link>
                </Button>
              </TooltipTrigger>
              <TooltipContent>Ir para consolidação manual</TooltipContent>
            </Tooltip>
          </div>
        </div>

        {/* Cards de Resumo */}
        <div className="grid gap-4 md:grid-cols-4 mb-8">
          <Card>
            <CardHeader className="pb-3">
              <CardDescription>Total</CardDescription>
              <CardTitle className="text-3xl font-bold">{contadores.todos}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-xs text-muted-foreground">
                <ShoppingBag className="h-3 w-3 inline mr-1" />
                Rascunhos ativos
              </div>
            </CardContent>
          </Card>

          <Card className={cn(filtro === 'limpos' && "ring-2 ring-blue-500")}>
            <CardHeader className="pb-3">
              <CardDescription>Limpos</CardDescription>
              <CardTitle className="text-3xl font-bold text-blue-600">{contadores.limpos}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-xs text-muted-foreground">
                <CheckCircle2 className="h-3 w-3 inline mr-1" />
                Sem edição humana
              </div>
            </CardContent>
          </Card>

          <Card className={cn(filtro === 'editados' && "ring-2 ring-yellow-500")}>
            <CardHeader className="pb-3">
              <CardDescription>Editados</CardDescription>
              <CardTitle className="text-3xl font-bold text-yellow-600">{contadores.editados}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-xs text-muted-foreground">
                <Clock className="h-3 w-3 inline mr-1" />
                Editados pelo usuário
              </div>
            </CardContent>
          </Card>

          <Card className={cn(filtro === 'modificados' && "ring-2 ring-red-500")}>
            <CardHeader className="pb-3">
              <CardDescription>Modificados</CardDescription>
              <CardTitle className="text-3xl font-bold text-red-600">{contadores.modificados}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-xs text-muted-foreground">
                <AlertCircle className="h-3 w-3 inline mr-1" />
                Pedidos após edição
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Filtros */}
        <Tabs value={filtro} onValueChange={setFiltro} className="mb-6">
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="todos">
              Todos ({contadores.todos})
            </TabsTrigger>
            <TabsTrigger value="limpos">
              Limpos ({contadores.limpos})
            </TabsTrigger>
            <TabsTrigger value="editados">
              Editados ({contadores.editados})
            </TabsTrigger>
            <TabsTrigger value="modificados">
              Modificados ({contadores.modificados})
            </TabsTrigger>
          </TabsList>
        </Tabs>

        {/* Lista de Rascunhos */}
        {loading ? (
          <div className="text-center py-12">
            <RefreshCw className="h-8 w-8 animate-spin mx-auto mb-4 text-gray-400" />
            <p className="text-gray-500">Carregando rascunhos...</p>
          </div>
        ) : rascunhosFiltrados.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-12">
              <ShoppingBag className="h-16 w-16 text-gray-300 mb-4" />
              <h3 className="text-lg font-semibold text-gray-900 mb-2">
                Nenhum rascunho {filtro !== 'todos' ? filtro : ''}
              </h3>
              <p className="text-gray-500 text-center max-w-md">
                {filtro === 'todos'
                  ? 'Os rascunhos automáticos aparecerão aqui quando pedidos forem recebidos via webhook.'
                  : `Não há rascunhos ${filtro} no momento.`}
              </p>
              {filtro === 'todos' && (
                <Button className="mt-4" asChild>
                  <Link to="/consolidar">
                    <FileSpreadsheet className="h-4 w-4 mr-2" />
                    Consolidar Planilha Manualmente
                  </Link>
                </Button>
              )}
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-4">
            {rascunhosFiltrados.map((rascunho) => (
              <RascunhoCard
                key={rascunho.id}
                rascunho={rascunho}
                onPublicar={handlePublicar}
                onEditar={handleEditar}
                onDeletar={handleDeletar}
                onVerNovos={handleVerNovos}
              />
            ))}
          </div>
        )}

        {/* Modal Ver Novos Pedidos */}
        <VerNovosPedidosModal
          open={modalAberto}
          onOpenChange={setModalAberto}
          demandaId={demandaSelecionada}
          onConfirmar={handleConfirmarPedidos}
          buscarPedidosNovos={buscarPedidosNovos}
        />
      </div>
    </TooltipProvider>
  );
}
