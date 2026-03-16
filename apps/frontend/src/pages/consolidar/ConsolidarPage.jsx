import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { AlertCircle, CheckCircle2, Copy, Database, ExternalLink, Eye, FileSpreadsheet, Filter, Link2, Link2Off, Loader2, Printer, Upload } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import ConsolidarBaseTab from './ConsolidarBaseTab';

function ConsolidarPage() {
  const [file, setFile] = useState(null);
  const [selectedChannel, setSelectedChannel] = useState('');
  const [selectedPlatform, setSelectedPlatform] = useState('');
  const [channels, setChannels] = useState([]);
  const [products, setProducts] = useState([]);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [printOrders, setPrintOrders] = useState(false);
  const [isFlex, setIsFlex] = useState(false);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [activeTab, setActiveTab] = useState('spreadsheet');

  // Operational Mode State
  const [opMode, setOpMode] = useState('v2');
  const [updatingMode, setUpdatingMode] = useState(false);

  // Demand Generation State
  const [demandName, setDemandName] = useState('');
  const [demandDate, setDemandDate] = useState('');
  const [demandHorarioColeta, setDemandHorarioColeta] = useState('');
  const [demandObservacoes, setDemandObservacoes] = useState('');
  const [creatingDemand, setCreatingDemand] = useState(false);

  useEffect(() => {
    const fetchChannels = async () => {
      try {
        const response = await fetch('/api/v2/cadastros/canal-venda?active_only=true');
        const data = await response.json();
        if (data.canais) setChannels(data.canais);
      } catch (error) {
        toast.error("Erro ao carregar canais.");
      }
    };

    const fetchProducts = async () => {
      try {
        const response = await fetch('/api/v2/produtos?page=1&per_page=10000&material_type=produto_acabado&only_marketable=true');
        const data = await response.json();
        if (data.produtos) setProducts(data.produtos);
      } catch (error) {
        toast.error("Erro ao carregar produtos.");
      }
    };

    const fetchMode = async () => {
        try {
            const response = await fetch('/api/v2/configuracoes/sistema');
            const data = await response.json();
            if (data.success) setOpMode(data.database_operational_mode);
        } catch (e) {}
    };

    fetchChannels();
    fetchProducts();
    fetchMode();
  }, []);

  const handleDatabaseAnalysis = (analysisData) => {
    const transformedResults = {
      'SISTEMA': {
        total_pedidos_plataforma: analysisData.total_pedidos,
        total_capas: analysisData.itens_consolidados.length,
        capas_miolos_data: analysisData.itens_consolidados.map(item => ({
          'Nome do Produto': item.produto_nome,
          'SKU': item.sku,
          'Variação': '',
          'Miolo': '',
          'Total': item.quantidade,
          internal_product_id: item.produto_id,
          internal_product_name: item.produto_nome,
          internal_product_sku: item.sku,
          mapping_status: item.produto_id ? 'Mapeado' : 'Não Mapeado',
          pedidos_origem: item.pedidos
        })),
        bling_orders_data: []
      }
    };
    setResults(transformedResults);
    setDemandName(`Demanda Base - ${new Date().toLocaleDateString('pt-BR')}`);
    toast.success('Análise concluída!');
  };

  const toggleOpMode = async () => {
    const newMode = opMode === 'v2' ? 'legacy' : 'v2';
    setUpdatingMode(true);
    try {
        const response = await fetch('/api/v2/configuracoes/sistema', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ database_operational_mode: newMode })
        });
        const data = await response.json();
        if (data.success) {
            setOpMode(newMode);
            toast.success(`Modo: ${newMode.toUpperCase()}`);
        }
    } catch (e) {
        toast.error("Erro de conexão.");
    } finally {
        setUpdatingMode(false);
    }
  };

  const handleFileChange = (e) => {
    if (e.target.files) setFile(e.target.files[0]);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file || !selectedChannel) {
      toast.error('Selecione o arquivo e o canal.');
      return;
    }

    setLoading(true);
    const formData = new FormData();
    formData.append('file', file);
    formData.append('platform', selectedPlatform);
    formData.append('channel', selectedChannel);
    if (startDate) formData.append('start_date', startDate);
    if (endDate) formData.append('end_datetime', endDate);
    formData.append('print-orders', printOrders);
    formData.append('is_flex', isFlex);
    formData.append('mode', opMode);

    try {
      const response = await fetch('/api/v2/consolidar', {
        method: 'POST',
        body: formData
      });
      if (!response.ok) throw new Error('Erro ao processar arquivo.');
      const data = await response.json();
      setResults(data);
      setDemandName(`Demanda ${selectedPlatform} - ${new Date().toLocaleDateString('pt-BR')}`);
      toast.success('Processado com sucesso!');
    } catch (error) {
      toast.error(error.message);
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateDemand = async (platformKey) => {
    if (!demandName || !demandDate) {
        toast.error("Preencha o Nome e a Data.");
        return;
    }
    setCreatingDemand(true);
    try {
        const itemsToProcess = results[platformKey].capas_miolos_data;
        const demandItems = itemsToProcess.map(item => ({
            produto_id: item.internal_product_id,
            sku: item.internal_product_sku || item['SKU'] || item['Código'],
            descricao: item.internal_product_name || item['Nome do Produto'] || item['Título'],
            quantidade: item.Total || 1,
            miolo_name: item.miolo_name || item.Miolo || '',
            variacao: item['Variação'] || '',
            pedidos_origem: item.pedidos_origem || []
        }));

        let channelObj = channels.find(c => c.id.toString() === selectedChannel || (c.slug || c.nome) === selectedChannel);
        if (!channelObj && activeTab === 'database') channelObj = channels[0];

        const payload = {
            nome: demandName,
            canal_venda_id: channelObj?.id,
            data_entrega: demandDate,
            horario_coleta_especifico: demandHorarioColeta,
            observacoes: demandObservacoes,
            tipo_demanda: 'Standard',
            itens: demandItems
        };

        const response = await fetch('/api/v2/demanda_producao/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (response.ok) {
            toast.success("Demanda gerada!");
            setTimeout(() => { window.location.href = '/producao/demanda'; }, 1000);
        } else {
            throw new Error("Erro ao salvar demanda.");
        }
    } catch (error) {
        toast.error(error.message);
    } finally {
        setCreatingDemand(false);
    }
  };

  const updateProductAssociation = (platformKey, itemIndex, productId) => {
    const newResults = { ...results };
    const item = newResults[platformKey].capas_miolos_data[itemIndex];
    const selectedProduct = products.find(p => String(p.id) === String(productId));
    if (selectedProduct) {
        item.internal_product_id = selectedProduct.id;
        item.internal_product_name = selectedProduct.name;
        item.internal_product_sku = selectedProduct.sku;
    } else {
        item.internal_product_id = null;
    }
    setResults(newResults);
  };

  const handleCopyTable = (platformKey) => {
    const data = results[platformKey];
    let text = data.capas_miolos_data.map(i => `${i['Nome do Produto'] || i['Título']}\t${i['SKU'] || i['Código']}\t${i.Total}`).join('\n');
    navigator.clipboard.writeText(text);
    toast.success('Copiado!');
  };

  return (
    <div className="flex flex-col w-full max-w-7xl mx-auto pb-20">
      <div className="flex justify-between items-center mb-8 bg-white p-4 rounded-lg border shadow-sm">
        <div>
            <h1 className="text-2xl font-bold tracking-tight">Consolidar Produção</h1>
            <p className="text-muted-foreground">Agrupe pedidos e gere demandas de fabricação.</p>
        </div>
        <Button variant={opMode === 'legacy' ? 'destructive' : 'outline'} onClick={toggleOpMode} disabled={updatingMode} className="gap-2">
            <Database className="h-4 w-4" /> Base: {opMode.toUpperCase()}
        </Button>
      </div>

      {!results ? (
        <Card className="shadow-md">
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Filter className="h-5 w-5 text-primary" /> Origem dos Dados</CardTitle>
          </CardHeader>
          <CardContent>
            <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
              <TabsList className="grid w-full grid-cols-2 h-12 mb-8">
                <TabsTrigger value="spreadsheet" className="gap-2 text-base"><FileSpreadsheet className="h-4 w-4" /> Planilha ERP/Marketplace</TabsTrigger>
                <TabsTrigger value="database" className="gap-2 text-base"><Database className="h-4 w-4" /> Pedidos Sincronizados (API)</TabsTrigger>
              </TabsList>

              <TabsContent value="spreadsheet" className="animate-in fade-in-50 duration-300">
                <form onSubmit={handleSubmit} className="space-y-6 p-4 border rounded-lg bg-muted/30">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div className="space-y-2">
                          <Label>Arquivo de Pedidos</Label>
                          <Input type="file" accept=".xlsx, .csv" onChange={handleFileChange} className="bg-white" />
                        </div>
                        <div className="space-y-2">
                          <Label>Canal de Venda</Label>
                          <Select value={selectedChannel} onValueChange={setSelectedChannel}>
                            <SelectTrigger className="bg-white"><SelectValue placeholder="Selecione o canal" /></SelectTrigger>
                            <SelectContent>{channels.map(c => <SelectItem key={c.id} value={c.slug || c.nome}>{c.nome}</SelectItem>)}</SelectContent>
                          </Select>
                        </div>
                        <div className="space-y-2">
                          <Label>Data Envio (Início)</Label>
                          <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="bg-white" />
                        </div>
                        <div className="space-y-2">
                          <Label>Data Envio (Fim - Opcional)</Label>
                          <Input type="datetime-local" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="bg-white" />
                        </div>
                    </div>

                    <div className="flex flex-wrap gap-6 items-center border-t border-b py-4">
                        <div className="flex items-center space-x-2">
                          <Checkbox id="print_orders" checked={printOrders} onCheckedChange={setPrintOrders} />
                          <Label htmlFor="print_orders" className="cursor-pointer">Imprimir pedidos e gerar notas</Label>
                        </div>
                        <div className="flex items-center space-x-2">
                          <Checkbox id="is_flex" checked={isFlex} onCheckedChange={setIsFlex} />
                          <Label htmlFor="is_flex" className="text-blue-600 font-bold cursor-pointer">Apenas Pedidos FLEX</Label>
                        </div>
                    </div>

                    <Button type="submit" disabled={loading} className="w-full h-12 text-lg">
                        {loading ? <Loader2 className="animate-spin mr-2" /> : <Upload className="mr-2" />} Processar Planilha
                    </Button>
                </form>
              </TabsContent>

              <TabsContent value="database" className="animate-in fade-in-50 duration-300">
                <ConsolidarBaseTab onAnalyse={handleDatabaseAnalysis} />
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-6 animate-in zoom-in-95 duration-300">
          <div className="flex flex-wrap justify-between items-center gap-4 bg-white p-4 rounded-lg border shadow-sm sticky top-0 z-20">
            <h2 className="text-xl font-bold flex items-center gap-2"><CheckCircle2 className="h-6 w-6 text-green-600" /> Itens Consolidados</h2>
            <div className="flex gap-3">
              <Button variant="outline" onClick={() => setResults(null)}>Voltar / Novo</Button>
              <Button className="bg-green-600 hover:bg-green-700" onClick={() => setModalOpen('demand')}>Gerar Demanda</Button>
            </div>
          </div>

          {Object.entries(results).map(([key, data]) => (
            <Card key={key}>
              <CardHeader className="flex flex-row items-center justify-between border-b bg-muted/20 py-3">
                <CardTitle className="text-lg">{key} ({data.total_pedidos_plataforma} pedidos)</CardTitle>
                <Button variant="ghost" size="sm" onClick={() => handleCopyTable(key)}><Copy className="h-4 w-4 mr-2" /> Copiar</Button>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                    <TableHeader><TableRow><TableHead>Produto</TableHead><TableHead>SKU</TableHead><TableHead className="text-right">Qtd</TableHead><TableHead>Status</TableHead><TableHead>Ação</TableHead></TableRow></TableHeader>
                    <TableBody>
                        {data.capas_miolos_data.map((item, idx) => (
                            <TableRow key={idx}>
                                <TableCell className="font-medium text-xs">{item['Nome do Produto'] || item['Título']}</TableCell>
                                <TableCell className="text-xs font-mono">{item['SKU'] || item['Código']}</TableCell>
                                <TableCell className="text-right font-bold">{item.Total}</TableCell>
                                <TableCell>{item.internal_product_id ? <Badge className="bg-green-600">Mapeado</Badge> : <Badge variant="destructive">Pendente</Badge>}</TableCell>
                                <TableCell>
                                    <Select value={String(item.internal_product_id || 'none')} onValueChange={(val) => updateProductAssociation(key, idx, val === 'none' ? null : val)}>
                                        <SelectTrigger className="h-8 w-[200px] text-xs"><SelectValue placeholder="Vincular..." /></SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="none">-- Selecione --</SelectItem>
                                            {products.map(p => <SelectItem key={p.id} value={String(p.id)}>{p.sku} - {p.name}</SelectItem>)}
                                        </SelectContent>
                                    </Select>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
              </CardContent>
            </Card>
          ))}

          {modalOpen === 'demand' && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
              <Card className="max-w-md w-full shadow-2xl animate-in slide-in-from-bottom-4">
                <CardHeader className="border-b"><CardTitle>Gerar Nova Demanda</CardTitle></CardHeader>
                <CardContent className="space-y-4 pt-6">
                  <div className="space-y-2"><Label>Nome da Demanda</Label><Input value={demandName} onChange={(e) => setDemandName(e.target.value)} /></div>
                  <div className="space-y-2"><Label>Data de Entrega</Label><Input type="date" value={demandDate} onChange={(e) => setDemandDate(e.target.value)} /></div>
                  <Button onClick={() => handleGenerateDemand(Object.keys(results)[0])} disabled={creatingDemand} className="w-full bg-primary h-12 text-lg">
                    {creatingDemand ? <Loader2 className="animate-spin mr-2" /> : null} Gerar Demanda
                  </Button>
                  <Button variant="ghost" onClick={() => setModalOpen(null)} className="w-full">Cancelar</Button>
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ConsolidarPage;
