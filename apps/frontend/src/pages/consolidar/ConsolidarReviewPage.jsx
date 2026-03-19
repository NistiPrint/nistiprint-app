import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { 
  ArrowLeft, 
  Package, 
  Users, 
  Calendar, 
  Clock, 
  CheckCircle2,
  AlertCircle,
  Loader2
} from 'lucide-react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

/**
 * Página de Revisão Pré-Demanda
 * Exibe resumo da consolidação antes de criar demanda
 */
export default function ConsolidarReviewPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  
  // Dados da consolidação
  const [pedidos, setPedidos] = useState([]);
  const [itensConsolidados, setItensConsolidados] = useState([]);
  const [canais, setCanais] = useState([]);
  
  // Dados da demanda
  const [demandaNome, setDemandaNome] = useState('');
  const [demandaData, setDemandaData] = useState('');
  const [demandaHorario, setDemandaHorario] = useState('');
  const [demandaObs, setDemandaObs] = useState('');
  const [canalSelecionado, setCanalSelecionado] = useState('');

  useEffect(() => {
    const pedidoIds = searchParams.get('pedidos');
    if (!pedidoIds) {
      toast.error('Nenhum pedido selecionado');
      navigate('/consolidar');
      return;
    }
    
    carregarCanais();
    carregarResumo(pedidoIds);
  }, []);

  async function carregarCanais() {
    try {
      const response = await fetch('/api/v2/cadastros/canal-venda?active_only=true');
      const data = await response.json();
      if (data.canais) {
        setCanais(data.canais);
        if (data.canais.length > 0) {
          setCanalSelecionado(String(data.canais[0].id));
        }
      }
    } catch (error) {
      console.error('Erro ao carregar canais:', error);
    }
  }

  async function carregarResumo(pedidoIdsStr) {
    setLoading(true);
    try {
      const pedidoIds = pedidoIdsStr.split(',').map(id => parseInt(id.trim()));
      
      // Buscar detalhes dos pedidos
      const response = await fetch('/api/v2/consolidar-base/analisar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pedido_ids: pedidoIds })
      });
      
      const data = await response.json();
      
      if (data.success) {
        // Extrair pedidos únicos
        const pedidosUnicos = [];
        const itensMap = new Map();
        
        // Determinar a fonte de dados (compatibilidade com lista ou objeto)
        const listaItens = data.data.itens_consolidados || 
                          (data.data.consolidado ? Object.values(data.data.consolidado) : []);
        
        // Processar itens consolidados
        listaItens.forEach(item => {
          // Normalizar chave para o mapa (garantir unicidade visual)
          const key = `${item.sku}-${item.descricao_original || item.descricao}`;
          
          itensMap.set(key, {
            sku: item.sku,
            descricao: item.descricao_original || item.descricao, // Fallback para descricao se original não existir
            quantidade: item.quantidade,
            pedidos: item.pedidos || []
          });
          
          // Adicionar pedidos únicos
          if (item.pedidos) {
            item.pedidos.forEach(p => {
              if (!pedidosUnicos.find(ped => ped.pedido_id === p.pedido_id)) {
                pedidosUnicos.push(p);
              }
            });
          }
        });
        
        setPedidos(pedidosUnicos);
        setItensConsolidados(Array.from(itensMap.values()));
        
        // Gerar nome automático da demanda
        const dataHoje = new Date().toISOString().split('T')[0];
        setDemandaNome(`Demanda Automática - ${dataHoje} (${pedidosUnicos.length} pedidos)`);
        setDemandaData(dataHoje);
      } else {
        toast.error(data.message || 'Erro ao carregar resumo');
        navigate('/consolidar');
      }
    } catch (error) {
      console.error('Erro ao carregar resumo:', error);
      toast.error('Erro de conexão');
      navigate('/consolidar');
    } finally {
      setLoading(false);
    }
  }

  async function handleCriarDemanda() {
    if (!demandaNome || !demandaData || !canalSelecionado) {
      toast.error('Preencha todos os campos obrigatórios');
      return;
    }
    
    setCreating(true);
    try {
      // Preparar payload
      const payload = {
        nome: demandaNome,
        canal_venda_id: parseInt(canalSelecionado),
        data_entrega: demandaData,
        horario_coleta: demandaHorario || null,
        observacoes: demandaObs,
        tipo_demanda: 'Standard',
        status: 'EM_PRODUCAO',
        itens: itensConsolidados.map(item => ({
          sku: item.sku,
          descricao: item.descricao,
          quantidade: item.quantidade,
          pedidos_origem: item.pedidos.map(p => ({
            pedido_id: p.pedido_id,
            codigo_pedido_externo: p.codigo_pedido_externo,
            quantidade: p.quantidade
          }))
        }))
      };
      
      console.log("Payload enviado para criar demanda:", payload); // DEBUG LOG
      
      const response = await fetch('/api/v2/demanda_producao/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      
      if (response.ok) {
        toast.success('Demanda criada com sucesso!');
        setTimeout(() => {
          navigate('/producao/demanda');
        }, 1000);
      } else {
        const errorData = await response.json();
        throw new Error(errorData.message || 'Erro ao criar demanda');
      }
    } catch (error) {
      console.error('Erro ao criar demanda:', error);
      toast.error(error.message || 'Erro ao criar demanda');
    } finally {
      setCreating(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-center space-y-4">
          <Loader2 className="w-12 h-12 animate-spin text-primary mx-auto" />
          <p className="text-muted-foreground">Carregando resumo...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="container mx-auto py-8 px-4 max-w-6xl">
        {/* Cabeçalho */}
        <div className="mb-6">
          <Button 
            variant="ghost" 
            size="sm" 
            onClick={() => navigate('/consolidar')}
            className="mb-4 gap-2"
          >
            <ArrowLeft className="w-4 h-4" />
            Voltar
          </Button>
          
          <h1 className="text-3xl font-bold tracking-tight">
            Revisão da Consolidação
          </h1>
          <p className="text-muted-foreground">
            Revise os pedidos e itens antes de criar a demanda de produção
          </p>
        </div>

        {/* Resumo */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Pedidos
              </CardTitle>
              <Users className="w-4 h-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{pedidos.length}</div>
              <p className="text-xs text-muted-foreground">pedidos selecionados</p>
            </CardContent>
          </Card>
          
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Itens Distintos
              </CardTitle>
              <Package className="w-4 h-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{itensConsolidados.length}</div>
              <p className="text-xs text-muted-foreground">itens consolidados</p>
            </CardContent>
          </Card>
          
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Total Unidades
              </CardTitle>
              <CheckCircle2 className="w-4 h-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {itensConsolidados.reduce((sum, item) => sum + item.quantidade, 0)}
              </div>
              <p className="text-xs text-muted-foreground">unidades a produzir</p>
            </CardContent>
          </Card>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Coluna Principal - Itens */}
          <div className="lg:col-span-2 space-y-6">
            {/* Pedidos Selecionados */}
            <Card>
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <Users className="w-5 h-5" />
                  Pedidos Selecionados ({pedidos.length})
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {pedidos.map((pedido, idx) => (
                    <div
                      key={pedido.pedido_id || idx}
                      className="p-3 rounded-lg border bg-muted/30"
                    >
                      <div className="font-semibold text-sm text-blue-700">
                        {pedido.numero_pedido || '-'}
                      </div>
                      <div className="text-xs text-muted-foreground font-mono">
                        {pedido.codigo_pedido_externo}
                      </div>
                      <div className="text-xs mt-1">
                        {pedido.qtd_itens || 1} {pedido.qtd_itens === 1 ? 'item' : 'itens'}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* Itens Consolidados */}
            <Card>
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <Package className="w-5 h-5" />
                  Itens para Produção ({itensConsolidados.length})
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted/50">
                      <TableHead>SKU</TableHead>
                      <TableHead>Descrição</TableHead>
                      <TableHead className="text-right">Qtd Total</TableHead>
                      <TableHead className="text-center">Pedidos</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {itensConsolidados.map((item, idx) => (
                      <TableRow key={idx}>
                        <TableCell className="font-mono text-sm">
                          {item.sku || '-'}
                        </TableCell>
                        <TableCell className="text-sm">
                          {item.descricao}
                        </TableCell>
                        <TableCell className="text-right font-bold">
                          {item.quantidade}
                        </TableCell>
                        <TableCell className="text-center">
                          <Badge variant="secondary" className="text-xs">
                            {item.pedidos?.length || 1}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </div>

          {/* Coluna Lateral - Formulário */}
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Dados da Demanda</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="nome">Nome da Demanda *</Label>
                  <Input
                    id="nome"
                    value={demandaNome}
                    onChange={(e) => setDemandaNome(e.target.value)}
                    placeholder="Ex: Demanda Shopee - Março/2026"
                  />
                </div>
                
                <div className="space-y-2">
                  <Label htmlFor="canal">Canal de Venda *</Label>
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
                  <Label htmlFor="data">Data de Entrega *</Label>
                  <div className="relative">
                    <Calendar className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                    <Input
                      id="data"
                      type="date"
                      value={demandaData}
                      onChange={(e) => setDemandaData(e.target.value)}
                      className="pl-9"
                    />
                  </div>
                </div>
                
                <div className="space-y-2">
                  <Label htmlFor="horario">Horário de Coleta</Label>
                  <div className="relative">
                    <Clock className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                    <Input
                      id="horario"
                      type="time"
                      value={demandaHorario}
                      onChange={(e) => setDemandaHorario(e.target.value)}
                      className="pl-9"
                    />
                  </div>
                </div>
                
                <div className="space-y-2">
                  <Label htmlFor="obs">Observações</Label>
                  <Textarea
                    id="obs"
                    value={demandaObs}
                    onChange={(e) => setDemandaObs(e.target.value)}
                    placeholder="Observações adicionais para a produção..."
                    rows={4}
                  />
                </div>
                
                <div className="pt-4 space-y-2">
                  <Button 
                    onClick={handleCriarDemanda} 
                    disabled={creating || !demandaNome || !demandaData || !canalSelecionado}
                    className="w-full h-12 text-lg bg-green-600 hover:bg-green-700"
                  >
                    {creating ? (
                      <Loader2 className="w-5 h-5 animate-spin mr-2" />
                    ) : (
                      <CheckCircle2 className="w-5 h-5 mr-2" />
                    )}
                    {creating ? 'Criando...' : 'Confirmar e Criar Demanda'}
                  </Button>
                  
                  <Button 
                    variant="outline" 
                    onClick={() => navigate('/consolidar')}
                    className="w-full"
                  >
                    Cancelar
                  </Button>
                </div>
              </CardContent>
            </Card>
            
            {/* Alerta */}
            <Card className="border-amber-200 bg-amber-50/50">
              <CardContent className="pt-6">
                <div className="flex items-start gap-3">
                  <AlertCircle className="w-5 h-5 text-amber-600 mt-0.5" />
                  <div className="text-sm text-amber-800">
                    <p className="font-semibold mb-1">Atenção</p>
                    <p>
                      Após criar a demanda, os pedidos serão vinculados e o estoque será reservado automaticamente.
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
