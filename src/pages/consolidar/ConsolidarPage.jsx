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
import { AlertCircle, CheckCircle2, Copy, Database, ExternalLink, Eye, Link2, Link2Off, Loader2, Printer, Upload } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

function ConsolidarPage() {
  const [file, setFile] = useState(null);
  const [selectedChannel, setSelectedChannel] = useState('');
  const [selectedPlatform, setSelectedPlatform] = useState('');
  const [channels, setChannels] = useState([]);
  const [products, setProducts] = useState([]); // List of internal products for association
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [printOrders, setPrintOrders] = useState(false);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [periodFilter, setPeriodFilter] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [nfeResults, setNfeResults] = useState([]);
  const [modalOpen, setModalOpen] = useState(null); // 'channel' or 'bling' or 'demand' or null
  const [showForm, setShowForm] = useState(true); // Controla se mostra form ou resultado

  // Operational Mode State
  const [opMode, setOpMode] = useState('v2'); // 'v2' or 'legacy'
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
        if (data.canais) {
          setChannels(data.canais);
        }
      } catch (error) {
        console.error("Error fetching channels:", error);
        toast.error("Erro ao carregar canais de venda.");
      }
    };

    const fetchProducts = async () => {
      try {
        // Fetch only marketable products of type 'produto_acabado' optimized at backend
        const response = await fetch('/api/v2/produtos?page=1&per_page=10000&material_type=produto_acabado&only_marketable=true');
        const data = await response.json();
        if (data.produtos) {
          setProducts(data.produtos);
        }
      } catch (error) {
        console.error("Error fetching products:", error);
        toast.error("Erro ao carregar lista de produtos.");
      }
    };

    const fetchMode = async () => {
        try {
            const response = await fetch('/api/v2/configuracoes/sistema');
            const data = await response.json();
            if (data.success) setOpMode(data.database_operational_mode);
        } catch (e) { console.error(e); }
    };

    fetchChannels();
    fetchProducts();
    fetchMode();
  }, []);

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
            toast.success(`Modo de operação alterado para: ${newMode.toUpperCase()}`);
        } else {
            toast.error("Erro ao alterar modo.");
        }
    } catch (e) {
        toast.error("Erro de conexão.");
    } finally {
        setUpdatingMode(false);
    }
  };

  const handleFileChange = (e) => {
    if (e.target.files) {
      setFile(e.target.files[0]);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) {
      toast.error('Por favor, selecione um arquivo.');
      return;
    }
    if (!selectedChannel) {
        toast.error('Por favor, selecione um canal de venda.');
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
    formData.append('mode', opMode);

    try {
      console.log('Iniciando processamento para /api/v2/consolidar');
      const response = await fetch('/api/v2/consolidar', {
        method: 'POST',
        body: formData,
        headers: {
            'Accept': 'application/json'
        }
      });

      if (!response.ok) {
        console.error('Erro na resposta:', response.status, response.statusText);
        let errorMsg = 'Erro ao processar arquivo.';
        try {
          const errorData = await response.json();
          errorMsg = errorData.error || errorMsg;
        } catch (jsonError) {
          console.error('Erro ao fazer parse do JSON de erro:', jsonError);
          // Tenta ler o texto da resposta para debug
          const text = await response.text();
          console.error('Conteúdo da resposta (text):', text.substring(0, 500));
          throw new Error(`Erro na comunicação com o servidor (Status: ${response.status}). Verifique o console.`);
        }
        throw new Error(errorMsg);
      }

      const data = await response.json();
      setResults(data);
      // Initialize demand name with a default value
      setDemandName(`Demanda ${selectedPlatform} - ${new Date().toLocaleDateString()}`);

      // Set default horario coleta from channel using the shared formatTime function
      const channelObj = channels.find(c => (c.slug || c.nome) === selectedChannel);
      if (channelObj && channelObj.horario_coleta) {
        const formattedTime = formatTime(channelObj.horario_coleta);
        if (formattedTime) {
          setDemandHorarioColeta(formattedTime);
        } else {
          // If the time format is invalid, don't set it to prevent the error
          console.warn(`Invalid time format for channel ${channelObj.nome}: ${channelObj.horario_coleta}`);
        }
      }

      setPeriodFilter({
        start: startDate || new Date(Date.now() - 120 * 24 * 60 * 60 * 1000).toISOString(),
        end: endDate || new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString()
      });
      setShowForm(false); // Mostrar resultado após processamento
      toast.success('Arquivo processado com sucesso!');
    } catch (error) {
      console.error(error);
      toast.error('Erro ao processar: ' + error.message);
    } finally {
      setLoading(false);
    }
  };

  const updateProductAssociation = (platformKey, itemIndex, productId) => {
    const newResults = { ...results };
    const item = newResults[platformKey].capas_miolos_data[itemIndex];
    const selectedProduct = products.find(p => String(p.id) === String(productId));

    if (selectedProduct) {
        item.internal_product_id = selectedProduct.id;
        item.internal_product_name = selectedProduct.name;
        item.internal_product_sku = selectedProduct.sku; // or sku_mestre
        item.mapping_status = 'Mapeado Manualmente';
    } else {
        item.internal_product_id = null;
        item.internal_product_name = null;
        item.internal_product_sku = null;
        item.mapping_status = 'Não Mapeado';
    }
    setResults(newResults);
  };

  // Helper function to validate and format time
  const formatTime = (timeStr) => {
    if (!timeStr || timeStr.trim() === '') return null;

    // Check if it's already in the correct format HH:MM
    const timeRegex = /^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$/;
    if (timeRegex.test(timeStr)) {
      return timeStr;
    }

    // Try to parse other formats and convert to HH:MM
    const timeParts = timeStr.split(':');
    if (timeParts.length >= 2) {
      const hours = parseInt(timeParts[0]);
      const minutes = parseInt(timeParts[1]);

      // Validate ranges
      if (hours >= 0 && hours <= 23 && minutes >= 0 && minutes <= 59) {
        return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
      }
    }

    // If we can't parse it, return null
    console.warn(`Could not parse time: ${timeStr}`);
    return null;
  };

  const handleGenerateDemand = async (platformKey) => {
    if (!demandName || !demandDate) {
        toast.error("Por favor, preencha o Nome da Demanda e a Data de Entrega.");
        return;
    }

    // Validação do formato da data
    const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
    if (!dateRegex.test(demandDate)) {
        toast.error("Formato de data inválido. Use o formato YYYY-MM-DD.");
        return;
    }

    // Validação do formato do horário de coleta, se fornecido
    if (demandHorarioColeta && demandHorarioColeta.trim() !== '') {
        const timeRegex = /^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$/;
        if (!timeRegex.test(demandHorarioColeta)) {
            toast.error("Formato de horário inválido. Use o formato HH:MM (24 horas).");
            return;
        }
    }

    // Validação adicional para garantir que os resultados e a plataforma selecionada existam
    if (!results || !results[platformKey]) {
        toast.error("Dados insuficientes para gerar a demanda. Por favor, processe novamente o arquivo.");
        return;
    }

    // Melhoria na busca do canal de venda para lidar com diferentes formatos
    let channelObj = channels.find(c => c.id.toString() === selectedChannel);
    if (!channelObj) {
        channelObj = channels.find(c => (c.slug || c.nome) === selectedChannel);
    }

    if (!channelObj) {
        toast.error("Erro: Canal de venda não identificado.");
        return;
    }

    setCreatingDemand(true);

    try {
        const itemsToProcess = results[platformKey].capas_miolos_data;

        if (!itemsToProcess || itemsToProcess.length === 0) {
            toast.error("Nenhum item encontrado para gerar a demanda.");
            return;
        }

        const demandItems = itemsToProcess.map(item => ({
            produto_id: item.internal_product_id,
            sku: item.internal_product_sku || getItemSku(item),
            descricao: item.internal_product_name || getItemName(item) || 'Item sem nome',
            quantidade: item.Total || 1, // Garante que tenhamos pelo menos 1 como quantidade
            miolo_name: item.miolo_name || item.Miolo || '',
            variacao: getItemVariation(item)
        }));

        // Formatar a data de entrega para o formato esperado pelo backend (YYYY-MM-DD)
        const formattedDeliveryDate = new Date(demandDate).toISOString().split('T')[0];

        const formattedCollectionTime = formatTime(demandHorarioColeta);

        const payload = {
            nome: demandName,
            canal_venda_id: channelObj.id,
            data_entrega: formattedDeliveryDate,
            horario_coleta_especifico: formattedCollectionTime,
            observacoes: demandObservacoes,
            tipo_demanda: 'Standard',  // Mudado para 'Standard' para garantir que fique na linha principal
            itens: demandItems
        };

        const response = await fetch('/api/v2/demanda_producao/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.message || errorData.error || `Erro HTTP: ${response.status}`);
        }

        const data = await response.json();
        if (data.success) {
            toast.success("Demanda de produção gerada com sucesso!");
            
            // Redireciona para a lista de demandas após sucesso
            setTimeout(() => {
                window.location.href = '/frontend/producao/demanda';
            }, 1500);
        } else {
            toast.error("Erro ao gerar demanda: " + (data.message || data.error || "Erro desconhecido"));
        }

    } catch (error) {
        console.error("Error creating demand:", error);
        toast.error("Erro ao gerar demanda: " + error.message);
    } finally {
        setCreatingDemand(false);
    }
  };

  const getItemName = (item) => {
      return item['Nome do Produto'] || item['Título do anúncio'] || item['Título'] || item['Nome do produto'] || '';
  };
  
  const getItemSku = (item) => {
      return item['Número de referência SKU'] || item['Nº de referência do SKU principal'] || item['SKU'] || item['SKU do vendedor'] || '';
  };

  const getItemVariation = (item) => {
      const val = item['Nome da variação'] || item['Variation Name'] || item['Variação'] || '';
      return val === '-' ? '' : val;
  };

  const copyTable = (htmlContent) => {
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = htmlContent;
    const text = tempDiv.innerText || tempDiv.textContent;
    navigator.clipboard.writeText(text);
    toast.success('Conteúdo copiado!');
  };

  const handleCopyTable = (platformKey) => {
    const data = results[platformKey];
    if (!data || !data.capas_miolos_data) return;

    let textToCopy = '';

    // Linhas apenas (sem cabeçalho)
    data.capas_miolos_data.forEach(item => {
      const row = [
        getItemName(item),
        getItemSku(item),
        getItemVariation(item),
        item.miolo_name || item.Miolo || '',
        item.Total || 0
      ];
      textToCopy += row.join('\t') + '\n';
    });

    navigator.clipboard.writeText(textToCopy).then(() => {
      toast.success('Dados copiados para o clipboard!');
    }).catch(err => {
      console.error('Erro ao copiar:', err);
      toast.error('Falha ao copiar dados.');
    });
  };

  const handlePrint = (platformKey) => {
    const data = results[platformKey];
    if (!data || !data.bling_orders_data) {
      toast.error("Dados de pedidos não disponíveis para impressão.");
      return;
    }

    const ordersHtml = data.bling_orders_data.map(order => {
      const itemsList = order.itens?.map(item => `
        <div class="flex items-center border-t border-gray-100 py-1.5">
          <div class="flex-1 pr-4 min-w-0">
            <div class="text-base leading-tight font-medium uppercase break-words">${item.descricao || ''}</div>
            <div class="text-xs font-mono text-gray-500">${item.codigo || ''}</div>
            ${item.personalization_name ? `<div class="text-2xl font-black text-black mt-1 italic border-l-4 border-black pl-2 bg-yellow-50 py-1">${item.personalization_name}</div>` : ''}
          </div>
          <div class="w-12 text-center text-xl font-bold">${item.quantidade || ''}</div>
          <div class="w-24 text-right text-sm text-gray-700">R$ ${parseFloat(item.valor || 0).toLocaleString('pt-BR', {minimumFractionDigits: 2})}</div>
        </div>
      `).join('') || '';

      const customTags = order.itens?.filter(i => i.custom_tag).map(i => `
        <div class="border-2 border-black px-3 py-1 text-xl font-bold uppercase bg-gray-50">
          ${i.custom_tag}
        </div>
      `).join('') || '';

      return `
        <div class="stamp-card-container">
          <div class="flex flex-col h-full bg-white overflow-hidden">
            <!-- Header -->
            <div class="flex justify-between items-start mb-2 border-b pb-1 flex-none">
              <div class="space-y-0">
                <div class="text-lg font-semibold">Nome: ${order.contato?.nome || ''}</div>
                <div class="text-sm text-gray-600">Doc: ${order.contato?.numeroDocumento || ''}</div>
              </div>
              <div class="text-right space-y-0">
                <div class="flex items-center justify-end gap-2 text-xl font-bold">
                  <img src="/static/img/${platformKey.toLowerCase()}.svg" class="h-5 w-5" onerror="this.style.display='none'"/>
                  ${platformKey.toUpperCase()}
                </div>
                <div class="text-sm font-medium text-gray-500">${order.numeroLoja || ''}</div>
              </div>
            </div>

            <!-- Main Content (Área Flexível) -->
            <div class="flex-grow flex flex-col border-2 border-black p-3 rounded-lg min-h-0 mb-2">
              <div class="text-center py-1 mb-2 border-b-2 border-black flex-none">
                <div class="text-2xl font-bold tracking-tight uppercase">Pedido ${order.numero || ''}</div>
              </div>

              <!-- Lista de Itens -->
              <div class="flex-grow overflow-hidden min-h-0">
                ${itemsList}
              </div>
              
              <!-- Total Products Row -->
              <div class="flex items-center border-t-2 border-gray-200 pt-1 mt-1 font-semibold flex-none">
                <div class="flex-1 text-right pr-6 text-sm uppercase">Total Produtos</div>
                <div class="w-32 text-right text-base">R$ ${parseFloat(order.totalProdutos || 0).toLocaleString('pt-BR', {minimumFractionDigits: 2})}</div>
              </div>

              <!-- Total Quantity Indicator -->
              <div class="text-center py-1 flex-none">
                <div class="text-3xl font-bold">
                  ${order.total_items || 0} ${order.total_items > 1 ? 'ITENS' : 'ITEM'}
                </div>
              </div>
            </div>

            <!-- Personalizações (Em linha com wrap) -->
            <div class="flex-none flex flex-wrap justify-center gap-1.5 mb-2">
              ${customTags}
            </div>

            <!-- Footer -->
            <div class="flex justify-between items-end pt-1 border-t border-gray-100 flex-none">
              <div class="text-lg font-bold uppercase">
                ${order.transporte?.contato?.id ? '<span class="border border-black px-2 py-0.5 rounded text-xs">[FLEX]</span>' : ''}
              </div>
              <div class="text-sm font-medium text-gray-400">
                ${periodFilter?.start ? new Date(periodFilter.start).toLocaleDateString('pt-BR') : ''}
              </div>
            </div>
          </div>
        </div>
      `;
    }).join('');

    const htmlContent = `
      <!DOCTYPE html>
      <html>
        <head>
          <meta charset="UTF-8">
          <script src="https://cdn.tailwindcss.com"></script>
          <style>
            @media print {
              @page { size: A4; margin: 0; }
              body { margin: 0; padding: 0; -webkit-print-color-adjust: exact; }
              .stamp-card-container { 
                width: 210mm; 
                height: 297mm; 
                padding: 10mm;
                box-sizing: border-box;
                page-break-after: always;
                overflow: hidden;
                display: block;
              }
            }
            .stamp-card-container { 
              width: 210mm; 
              height: 297mm; 
              padding: 10mm;
              box-sizing: border-box;
              margin: 0 auto;
              background: white;
            }
            body { font-family: sans-serif; }
          </style>
        </head>
        <body class="bg-gray-100 print:bg-white">
          ${ordersHtml}
        </body>
      </html>
    `;

    const iframe = document.createElement('iframe');
    iframe.style.position = 'absolute';
    iframe.style.top = '-9999px';
    document.body.appendChild(iframe);
    iframe.contentDocument.open();
    iframe.contentDocument.write(htmlContent);
    iframe.contentDocument.close();
    
    setTimeout(() => {
      iframe.contentWindow.print();
      setTimeout(() => iframe.remove(), 2000);
    }, 1000);
  };

  const generateNfe = async (platformName, blingOrders) => {
    toast.info('Funcionalidade de geração de NFs ainda não migrada para API V2 neste componente.');
  };

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('pt-BR');
  };

  const openSidebar = () => setSidebarOpen(true);
  const closeSidebar = () => setSidebarOpen(false);

  const handleNewProcessing = () => {
    // Limpar todos os dados do formulário e resultado
    setFile(null);
    setSelectedChannel('');
    setSelectedPlatform('');
    setStartDate('');
    setEndDate('');
    setPrintOrders(false);
    setResults(null);
    setPeriodFilter(null);
    setDemandName('');
    setDemandDate('');
    setDemandHorarioColeta(''); // Resetar para string vazia
    setDemandObservacoes('');
    setModalOpen(null);
    setSidebarOpen(false);
    setNfeResults([]);
    setShowForm(true);
  };

  return (
    <div className="container mx-auto py-8">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold">Consolidar Produção</h1>
        <div className="flex gap-2">
            <Button 
                variant={opMode === 'legacy' ? 'destructive' : 'secondary'}
                onClick={toggleOpMode}
                disabled={updatingMode}
                className="gap-2"
                title={opMode === 'legacy' ? "Usando MySQL (Legado)" : "Usando Supabase (V2)"}
            >
                <Database className={`h-4 w-4 ${updatingMode ? 'animate-pulse' : ''}`} />
                Modo: {opMode.toUpperCase()}
            </Button>
        </div>
      </div>

      {showForm ? (
        <Card className="mb-8">
          <CardHeader>
            <CardTitle>Processar Arquivo</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="file">Arquivo (.xlsx, .csv)</Label>
                  <Input id="file" type="file" accept=".xlsx, .csv" onChange={handleFileChange} />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="selectedChannel">Canal de Venda</Label>
                  <Select id="selectedChannel" value={selectedChannel} onValueChange={(selectedValue) => {
                    setSelectedChannel(selectedValue);
                    const foundChannel = channels.find(c => (c.slug || c.nome) === selectedValue);
                    if (foundChannel) {
                      // Normalize platform name to match template values
                      const plataforma = foundChannel.plataforma || '';
                      const normalizedPlataforma = plataforma.replace(/\s+/g, '');
                      setSelectedPlatform(normalizedPlataforma);
                    }
                  }}>
                    <SelectTrigger>
                      <SelectValue placeholder="Selecione o canal de venda" />
                    </SelectTrigger>
                    <SelectContent>
                      {channels.map((channel) => (
                        <SelectItem key={channel.id} value={channel.slug || channel.nome}>
                          {channel.nome}
                        </SelectItem>
                      ))}
                      {channels.length === 0 && (
                          <SelectItem value="loading" disabled>Carregando canais...</SelectItem>
                      )}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="start_date">Data Inicial</Label>
                  <Input
                    id="start_date"
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                  />
                </div>

                 <div className="space-y-2">
                  <Label htmlFor="end_date">Data Final</Label>
                  <Input
                    id="end_date"
                    type="datetime-local"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                  />
                </div>
              </div>

              <div className="flex items-center space-x-2">
                <Checkbox
                  id="print_orders"
                  checked={printOrders}
                  onCheckedChange={setPrintOrders}
                />
                <Label htmlFor="print_orders">Imprimir pedidos e gerar notas</Label>
              </div>

              <Button type="submit" disabled={loading} className="w-full md:w-auto">
                {loading ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Processando...</> : <><Upload className="mr-2 h-4 w-4" /> Processar</>}
              </Button>
            </form>
          </CardContent>
        </Card>
      ) : (
        <div>
          <div className="d-flex justify-content-between align-items-center mb-4">
            <h2>Resultado da Consolidação</h2>
            <div className="flex gap-2">
              <Button variant="outline" onClick={handleNewProcessing}>
                Novo Processamento
              </Button>
              <Button variant="default" onClick={() => setModalOpen('demand')} className="bg-green-600 hover:bg-green-700">
                Gerar Demanda
              </Button>
              <Button variant="outline" onClick={openSidebar} disabled={!printOrders}>
                <Eye className="mr-2 h-4 w-4" /> Resultado NFs
              </Button>
            </div>
          </div>

          {periodFilter && (
            <div className="text-sm text-gray-500 mb-4">
              Período: {formatDate(periodFilter.start)} a {formatDate(periodFilter.end)}
            </div>
          )}

          <Tabs defaultValue={Object.keys(results)[0]}> 
            <TabsList className="mb-4">
              {Object.keys(results).map((key) => (
                <TabsTrigger key={key} value={key}>{key} ({results[key].total_pedidos_plataforma})</TabsTrigger>
              ))}
            </TabsList>

            {Object.entries(results).map(([key, data]) => (
              <TabsContent key={key} value={key} className="space-y-6">

                {/* Alert for Bling Integration Error */}
                {printOrders && (!data.bling_orders_data || data.bling_orders_data.length === 0) && (
                  <Card className="border-red-200 bg-red-50">
                    <CardContent className="pt-4">
                      <div className="flex items-center space-x-2 text-red-700">
                        <AlertCircle className="h-5 w-5" />
                        <div>
                          <p className="font-medium">Integração com Bling falhou</p>
                          <p className="text-sm">Não será possível imprimir pedidos ou gerar notas fiscais para este processamento.</p>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                )}

                {/* Actions Bar */}
                <div className="flex flex-wrap gap-2 mb-4">
                  <Button variant="secondary" onClick={() => setModalOpen(`${key}-channel`)}>
                    Ver {data.total_pedidos_plataforma} IDs
                  </Button>
                  <Button 
                    variant="secondary" 
                    onClick={() => handlePrint(key)} 
                    disabled={!printOrders || (!data.bling_orders_data || data.bling_orders_data.length === 0)}
                  >
                    <Printer className="mr-2 h-4 w-4" />
                    Imprimir {data.bling_orders_data?.length || 0} pedidos
                  </Button>
                </div>

                {/* Main Consolidation Table */}
                <Card>
                  <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                    <CardTitle className="text-xl font-bold">Itens Consolidados ({data.total_capas})</CardTitle>
                    <div className="flex gap-1">
                        <Button variant="ghost" size="sm" onClick={() => handleCopyTable(key)} title="Copiar Tabela">
                          <Copy className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => handlePrint(key)} title="Imprimir Etiquetas">
                          <Printer className="h-4 w-4" />
                        </Button>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <ScrollArea className="h-[600px] w-full rounded-md border">
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead className="w-[300px]">Produto (Externo)</TableHead>
                                    <TableHead>SKU (Externo)</TableHead>
                                    <TableHead className="w-[150px]">Variação</TableHead>
                                    <TableHead>Miolo</TableHead>
                                    <TableHead className="text-right">Qtd</TableHead>
                                    <TableHead>Status</TableHead>
                                    <TableHead className="w-[300px]">Associar Produto Interno</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {data.capas_miolos_data && data.capas_miolos_data.map((item, index) => (
                                    <TableRow key={index}>
                                        <TableCell className="font-medium text-xs">{getItemName(item)}</TableCell>
                                        <TableCell className="text-xs">{getItemSku(item)}</TableCell>
                                        <TableCell className="text-xs">{getItemVariation(item)}</TableCell>
                                        <TableCell className="text-xs">{item.miolo_name || item.Miolo}</TableCell>
                                        <TableCell className="text-right font-bold">{item.Total}</TableCell>
                                        <TableCell>
                                            {item.mapping_status === 'Mapeado' || item.mapping_status === 'Mapeado Manualmente' ? (
                                                <Badge variant="default" className="bg-green-600"><CheckCircle2 className="w-3 h-3 mr-1"/> Mapeado</Badge>
                                            ) : item.mapping_status === 'Múltiplas Correspondências' ? (
                                                <Badge variant="secondary" className="bg-yellow-500 text-black"><AlertCircle className="w-3 h-3 mr-1"/> Múltiplos</Badge>
                                            ) : (
                                                <Badge variant="destructive"><AlertCircle className="w-3 h-3 mr-1"/> Pendente</Badge>
                                            )}
                                        </TableCell>
                                        <TableCell>
                                            <div className="flex items-center gap-2">
                                                {item.internal_product_id ? (
                                                    <div className="flex items-center gap-2">
                                                        <Link2 className="w-4 h-4 text-green-600" title="Mapeado" />
                                                        <span className="text-xs font-medium truncate max-w-[150px]" title={item.internal_product_name}>
                                                            {item.internal_product_name}
                                                        </span>
                                                        <a 
                                                            href={`/frontend/produtos/${item.internal_product_id}/editar`} 
                                                            target="_blank" 
                                                            rel="noopener noreferrer"
                                                            className="text-blue-600 hover:text-blue-800"
                                                        >
                                                            <ExternalLink className="w-3 h-3" />
                                                        </a>
                                                        <Button 
                                                            variant="ghost" 
                                                            size="sm" 
                                                            className="h-6 w-6 p-0 text-gray-400 hover:text-red-600"
                                                            onClick={() => updateProductAssociation(key, index, null)}
                                                            title="Remover vínculo"
                                                        >
                                                            ×
                                                        </Button>
                                                    </div>
                                                ) : (
                                                    <div className="flex items-center gap-2 w-full">
                                                        <Link2Off className="w-4 h-4 text-gray-400" title="Não Mapeado" />
                                                        <Select
                                                            value="none"
                                                            onValueChange={(val) => updateProductAssociation(key, index, val === "none" ? null : val)}
                                                        >
                                                            <SelectTrigger className="h-8 w-full min-w-[150px]">
                                                                <SelectValue placeholder="Vincular produto..." />
                                                            </SelectTrigger>
                                                            <SelectContent>
                                                                <SelectItem value="none">-- Selecione --</SelectItem>
                                                                {products.map(p => (
                                                                    <SelectItem key={p.id} value={String(p.id)}>
                                                                        {p.sku} - {p.name}
                                                                    </SelectItem>
                                                                ))}
                                                            </SelectContent>
                                                        </Select>
                                                    </div>
                                                )}
                                            </div>
                                            {item.mapping_status === 'Múltiplas Correspondências' && item.potential_matches && (
                                                <div className="text-[10px] text-muted-foreground mt-1 bg-yellow-50 p-1 rounded border border-yellow-100">
                                                    Sugestões: {JSON.parse(item.potential_matches).map(m => m.name || m.nome).join(', ')}
                                                </div>
                                            )}
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </ScrollArea>
                  </CardContent>
                </Card>




                {/* Modals Logic (Keep existing for Channel IDs and Bling Orders) */}
                {modalOpen === `${key}-channel` && (
                  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
                    <div className="bg-white rounded-lg p-6 max-w-lg w-full max-h-[80vh] overflow-y-auto">
                        <div className="flex justify-between items-center mb-4">
                          <h3 className="text-lg font-bold">IDs no canal de venda</h3>
                          <button onClick={() => setModalOpen(null)} className="text-gray-500 hover:text-black">×</button>
                        </div>
                        <div className="space-y-4">
                           <h4 className="font-semibold">Todos:</h4>
                           <div className="bg-gray-100 p-2 rounded text-xs font-mono break-all max-h-40 overflow-y-auto">
                               {data.ids_pedidos?.join(', ')}
                           </div>
                           {data.bling_orders_not_found?.length > 0 && (
                               <>
                                   <h4 className="font-semibold text-red-600">Não encontrados no Bling:</h4>
                                   <div className="bg-red-50 p-2 rounded text-xs font-mono text-red-600">
                                       {data.bling_orders_not_found.join(', ')}
                                   </div>
                               </>
                           )}
                        </div>
                    </div>
                  </div>
                )}

              </TabsContent>
            ))}
          </Tabs>

          {/* Styles for printing (hidden in normal view) */}
          <style>{`
             @media print {
               @page { size: auto; margin: 0mm; }
               body { margin: 10mm; }
               .no-print { display: none !important; }
             }
          `}</style>

          {/* Sidebar for NFE results */}
          {sidebarOpen && (
            <div className="fixed top-0 right-0 w-80 h-full bg-white shadow-xl border-l p-4 z-50 transition-transform transform translate-x-0">
              <div className="flex justify-between items-center mb-4">
                  <h3 className="font-bold text-lg">Notas fiscais</h3>
                  <Button variant="ghost" size="sm" onClick={closeSidebar}>×</Button>
              </div>
              <ul className="space-y-2">
                {nfeResults.map((result, index) => (
                  <li key={index} className="text-sm border-b pb-1">
                    {result.nfe_id ? (
                      <a href={`https://www.bling.com.br/notas.fiscais.php#edit/${result.nfe_id}`} target="_blank" className="text-blue-600 hover:underline">
                        #{result.numero}
                      </a>
                    ) : (
                      <a href={`https://www.bling.com.br/vendas.php#edit/${result.id}`} target="_blank" className="text-blue-600 hover:underline">
                        #{result.numero}
                      </a>
                    )}
                    : {result.error || 'sucesso'}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Demand Generation Modal */}
          {modalOpen === 'demand' && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
              <div className="bg-white rounded-lg p-6 max-w-md w-full max-h-[80vh] overflow-y-auto">
                <div className="flex justify-between items-center mb-4">
                  <h3 className="text-lg font-bold">Gerar Demanda de Produção</h3>
                  <button onClick={() => setModalOpen(null)} className="text-gray-500 hover:text-black">×</button>
                </div>
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="demandName">Nome da Demanda</Label>
                    <Input
                      id="demandName"
                      value={demandName}
                      onChange={(e) => setDemandName(e.target.value)}
                      placeholder="Ex: Demanda Shopee 10/10"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="demandDate">Data de Entrega</Label>
                    <Input
                      id="demandDate"
                      type="date"
                      value={demandDate}
                      onChange={(e) => setDemandDate(e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="demandHorarioColeta">Horário de Coleta desta Demanda</Label>
                    <Input
                      id="demandHorarioColeta"
                      type="time"
                      value={demandHorarioColeta || ''}
                      onChange={(e) => {
                        // Validate the time format when user inputs
                        const timeRegex = /^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$/;
                        if (e.target.value === '' || timeRegex.test(e.target.value)) {
                          setDemandHorarioColeta(e.target.value);
                        } else {
                          // Optionally show a warning to the user
                          toast.warning("Formato de horário inválido. Use o formato HH:MM (24 horas).");
                        }
                      }}
                      placeholder="HH:MM"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="demandObservacoes">Observações (Opcional)</Label>
                    <Input
                      id="demandObservacoes"
                      value={demandObservacoes}
                      onChange={(e) => setDemandObservacoes(e.target.value)}
                      placeholder="Ex: Prioridade máxima"
                    />
                  </div>
                  <Button
                    onClick={() => {
                      // Usa a primeira plataforma dos resultados como antes
                      const platformKey = Object.keys(results)[0];
                      handleGenerateDemand(platformKey);
                      setModalOpen(null);
                    }}
                    disabled={creatingDemand}
                    className="w-full bg-green-600 hover:bg-green-700 text-white"
                  >
                    {creatingDemand ? <Loader2 className="mr-2 h-4 w-4 animate-spin"/> : null}
                    Gerar Demanda
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* Modal backdrop */}
          {modalOpen && (
            <div className="fixed inset-0 bg-black/50 z-40" onClick={() => setModalOpen(null)}></div>
          )}
        </div>

      )}
    </div>
  );
}

export default ConsolidarPage;