import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { AlertCircle, Calendar, Filter, Loader2, Search, ShoppingBag, Zap } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

export default function ConsolidarBaseTab({ onAnalyse }) {
  const [loading, setLoading] = useState(false);
  const [pedidos, setPedidos] = useState([]);
  const [plataformas, setPlataformas] = useState([]);
  const [selectedPedidos, setSelectedPedidos] = useState([]);
  
  // Filtros
  const [plataformaId, setPlataformaId] = useState('all');
  const [isFlex, setIsFlex] = useState('all');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [search, setSearch] = useState('');

  useEffect(() => {
    fetchPlataformas();
    fetchPedidos();
  }, []);

  const fetchPlataformas = async () => {
    try {
      const response = await fetch('/api/v2/consolidar-base/plataformas');
      const data = await response.json();
      if (data.success) setPlataformas(data.data);
    } catch (error) {}
  };

  const fetchPedidos = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (plataformaId !== 'all') params.append('plataforma_id', plataformaId);
      if (isFlex !== 'all') params.append('is_flex', isFlex === 'true');
      if (startDate) params.append('data_inicio', startDate);
      if (endDate) params.append('data_fim', endDate);
      if (search) params.append('search', search);

      const response = await fetch(`/api/v2/consolidar-base/pedidos?${params.toString()}`);
      const data = await response.json();
      if (data.success) {
        setPedidos(data.data);
        setSelectedPedidos([]);
      } else {
        toast.error(data.message || "Erro ao buscar pedidos");
      }
    } catch (error) {
      toast.error("Erro de conexão");
    } finally {
      setLoading(false);
    }
  };

  const handleSelectPedido = (pedidoId, checked) => {
    if (checked) setSelectedPedidos(prev => [...prev, pedidoId]);
    else setSelectedPedidos(prev => prev.filter(id => id !== pedidoId));
  };

  const handleAnalyse = async () => {
    if (selectedPedidos.length === 0) return;
    setLoading(true);
    try {
      const response = await fetch('/api/v2/consolidar-base/analisar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pedido_ids: selectedPedidos })
      });
      const data = await response.json();
      if (data.success) onAnalyse(data.data);
      else toast.error(data.message);
    } catch (error) {
      toast.error("Erro ao analisar");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <Card className="bg-muted/20 border-none shadow-none">
        <CardContent className="pt-6">
          <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4">
            <div className="space-y-2">
              <Label>Plataforma</Label>
              <Select value={plataformaId} onValueChange={setPlataformaId}>
                <SelectTrigger className="bg-white"><SelectValue placeholder="Todas" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todas</SelectItem>
                  {plataformas.map(p => <SelectItem key={p.id} value={String(p.id)}>{p.nome}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Tipo Envio</Label>
              <Select value={isFlex} onValueChange={setIsFlex}>
                <SelectTrigger className="bg-white"><SelectValue placeholder="Todos" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todos</SelectItem>
                  <SelectItem value="true">Apenas FLEX (Prioridade)</SelectItem>
                  <SelectItem value="false">Normal</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label className="text-blue-600 font-bold">Data ENVIO (Início)</Label>
              <Input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} className="bg-white" />
            </div>

            <div className="space-y-2">
              <Label className="text-blue-600 font-bold">Data ENVIO (Fim)</Label>
              <Input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} className="bg-white" />
            </div>

            <div className="space-y-2">
              <Label>Pesquisar</Label>
              <div className="relative">
                <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input placeholder="Número, Cliente ou SKU" className="pl-8 bg-white" value={search} onChange={e => setSearch(e.target.value)} />
              </div>
            </div>
          </div>

          <div className="mt-4 flex justify-end">
            <Button onClick={fetchPedidos} disabled={loading} className="px-8 h-11">
              {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Search className="h-4 w-4 mr-2" />}
              Buscar Pedidos na Base
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between py-4">
          <CardTitle className="text-lg font-medium flex items-center gap-2">
            Pedidos Sincronizados ({pedidos.length})
            {pedidos.some(p => p.is_flex) && (
                <Badge className="bg-amber-100 text-amber-900 border-amber-200 gap-1 animate-pulse">
                    <Zap className="w-3 h-3 fill-amber-600" /> Possui Pedidos FLEX
                </Badge>
            )}
          </CardTitle>
          {selectedPedidos.length > 0 && (
            <Button className="bg-green-600 hover:bg-green-700 h-9" onClick={handleAnalyse} disabled={loading}>
              Analisar {selectedPedidos.length} Selecionados
            </Button>
          )}
        </CardHeader>
        <CardContent className="p-0">
          <ScrollArea className="h-[500px] w-full border-t">
            <Table>
              <TableHeader className="bg-muted/50 sticky top-0 z-10">
                <TableRow>
                  <TableHead className="w-12 text-center">
                    <Checkbox checked={pedidos.length > 0 && selectedPedidos.length === pedidos.length} onCheckedChange={(checked) => checked ? setSelectedPedidos(pedidos.map(p => p.pedido_id)) : setSelectedPedidos([])} />
                  </TableHead>
                  <TableHead>Plataforma</TableHead>
                  <TableHead className="text-blue-700 font-bold">Número Pedido</TableHead>
                  <TableHead>Marketplace ID</TableHead>
                  <TableHead className="text-blue-600 font-bold">Data ENVIO</TableHead>
                  <TableHead>Cliente</TableHead>
                  <TableHead>Itens</TableHead>
                  <TableHead>Status Envio</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pedidos.map((p) => {
                  const isFlexOrder = p.is_flex;
                  return (
                    <TableRow 
                        key={p.pedido_id} 
                        className={`
                            ${selectedPedidos.includes(p.pedido_id) ? "bg-blue-50/50" : ""}
                            ${isFlexOrder ? "bg-amber-50/40 hover:bg-amber-50/60" : ""}
                        `}
                    >
                        <TableCell className="text-center">
                            <Checkbox checked={selectedPedidos.includes(p.pedido_id)} onCheckedChange={(checked) => handleSelectPedido(p.pedido_id, checked)} />
                        </TableCell>
                        <TableCell><Badge variant="outline">{p.plataforma_nome}</Badge></TableCell>
                        <TableCell className="font-bold text-sm text-blue-800">{p.numero_pedido || '-'}</TableCell>
                        <TableCell className="font-mono text-[10px] text-muted-foreground">{p.codigo_pedido_externo}</TableCell>
                        <TableCell className="text-xs font-bold text-blue-700 whitespace-nowrap">
                            {p.data_prevista_entrega ? new Date(p.data_prevista_entrega).toLocaleDateString('pt-BR') : '-'}
                        </TableCell>
                        <TableCell className="text-xs font-medium truncate max-w-[120px]">{p.cliente_nome}</TableCell>
                        <TableCell>
                            <div className="flex flex-col gap-0.5">
                                {p.itens?.map((it, idx) => (
                                    <div key={idx} className="text-[9px] text-muted-foreground leading-tight whitespace-nowrap">
                                        {it.quantidade}x {it.sku_externo}
                                    </div>
                                ))}
                            </div>
                        </TableCell>
                        <TableCell>
                            <div className="flex flex-wrap gap-1">
                                {isFlexOrder && (
                                    <Badge className="bg-amber-600 hover:bg-amber-700 text-[10px] h-5 gap-1 font-bold">
                                        <Zap className="w-2 h-2 fill-white" /> FLEX
                                    </Badge>
                                )}
                                {p.is_fulfillment && <Badge className="bg-orange-500 text-[9px] h-5">FULL</Badge>}
                            </div>
                        </TableCell>
                    </TableRow>
                  );
                })}
                {pedidos.length === 0 && !loading && (
                    <TableRow>
                        <TableCell colSpan={8} className="text-center py-20 text-muted-foreground italic">
                            Nenhum pedido pendente de consolidação encontrado na base.
                        </TableCell>
                    </TableRow>
                )}
              </TableBody>
            </Table>
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  );
}
