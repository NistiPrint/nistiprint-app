import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { CheckCircle2, ClipboardList, Copy, Database, Filter, Loader2, Printer, Upload, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

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

  // Operational Mode State
  const [opMode, setOpMode] = useState('v2');
  const [updatingMode, setUpdatingMode] = useState(false);

  // Demand Generation State
  const [demandName, setDemandName] = useState('');
  const [demandDate, setDemandDate] = useState('');
  const [demandHorarioColeta, setDemandHorarioColeta] = useState('');
  const [demandObservacoes, setDemandObservacoes] = useState('');
  const [creatingDemand, setCreatingDemand] = useState(false);
  const [modalOpen, setModalOpen] = useState(null);

  // Async Processing State
  const [asyncProcessing, setAsyncProcessing] = useState(null); // { consolidacaoId, status }

  // NFE Generation State
  const [nfeSidebarOpen, setNfeSidebarOpen] = useState(false);
  const [nfeResults, setNfeResults] = useState([]);
  const [nfeGenerating, setNfeGenerating] = useState(false);
  const [blingAccounts, setBlingAccounts] = useState([]);
  const [selectedBlingAccountId, setSelectedBlingAccountId] = useState('');

  // Ref para armazenar o intervalo do polling
  const pollingIntervalRef = useRef(null);
  const eventSourceRef = useRef(null);

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

    const fetchBlingAccounts = async () => {
      try {
        const response = await fetch('/api/v2/integracoes/bling/accounts');
        const data = await response.json();
        if (data.accounts) setBlingAccounts(data.accounts);
      } catch (error) {
        console.error("Erro ao carregar contas Bling:", error);
      }
    };

    fetchChannels();
    fetchProducts();
    fetchMode();
    fetchBlingAccounts();
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
        if (!channelObj) channelObj = channels[0];

        const payload = {
            nome: demandName,
            canal_venda_id: channelObj?.id,
            data_entrega: demandDate,
            horario_coleta_especifico: demandHorarioColeta || null,
            observacoes: demandObservacoes || null,
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
            setModalOpen(null); // Fecha o modal
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

  // Async processing functions
  const startAsyncProcessing = async (e) => {
    e.preventDefault();
    if (!file || !selectedChannel) {
      toast.error('Selecione o arquivo e o canal.');
      return;
    }

    setLoading(true);
    const formData = new FormData();
    formData.append('file', file);
    formData.append('channel', selectedChannel);
    if (startDate) formData.append('start_date', startDate);
    if (endDate) formData.append('end_datetime', endDate);
    formData.append('print-orders', printOrders);
    formData.append('is_flex', isFlex);
    formData.append('mode', opMode);

    try {
      const response = await fetch('/api/v2/consolidar-async', {
        method: 'POST',
        body: formData
      });
      
      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Erro ao iniciar processamento');
      }
      
      const data = await response.json();
      setAsyncProcessing({
        consolidacaoId: data.consolidacao_id,
        status: data.status,
        pollingInterval: null
      });
      
      // Inicia polling
      startPolling(data.consolidacao_id);
      toast.success('Processamento iniciado em background!');
    } catch (error) {
      toast.error(error.message);
    } finally {
      setLoading(false);
    }
  };

  const startPolling = (consolidacaoId) => {
    // Limpa polling anterior se existir
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
    }
    
    pollingIntervalRef.current = setInterval(async () => {
      try {
        const response = await fetch(`/api/v2/consolidar-async/${consolidacaoId}`);
        const data = await response.json();

        setAsyncProcessing(prev => ({ ...prev, status: data.status }));

        if (data.status === 'PRONTO') {
          if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current);
            pollingIntervalRef.current = null;
          }
          // Processa os dados para adicionar pedidos_origem a partir de order_refs
          const processedResult = processarResultData(data.result);
          setResults(processedResult);
          setAsyncProcessing(null);
          setDemandName(`Demanda - ${new Date().toLocaleDateString('pt-BR')}`);
          toast.success('Processamento concluído!');
        } else if (data.status === 'ERRO') {
          if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current);
            pollingIntervalRef.current = null;
          }
          setAsyncProcessing(null);
          toast.error(`Erro no processamento: ${data.error_message}`);
        }
      } catch (error) {
        console.error('Polling error:', error);
      }
    }, 3000); // Poll a cada 3 segundos
  };
  
  // Limpa polling ao desmontar componente
  useEffect(() => {
    return () => {
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
      }
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  const processarResultData = (result) => {
    // Processa cada plataforma para adicionar pedidos_origem a partir de order_refs
    const processed = {};
    for (const [platform, platformData] of Object.entries(result)) {
      const capasMiolosData = platformData.capas_miolos_data?.map(item => ({
        ...item,
        // Se não tiver pedidos_origem, tenta usar order_refs
        pedidos_origem: item.pedidos_origem || (item.order_refs?.map(ref => ({
          codigo_pedido_externo: ref,
          numero_pedido: null // Não tem numero do Bling
        })) || [])
      })) || [];
      
      processed[platform] = {
        ...platformData,
        capas_miolos_data: capasMiolosData
      };
    }
    return processed;
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
    let text = data.capas_miolos_data.map(i => `${i['Nome do Produto'] || i['Título']}\t${i['SKU'] || i['Código']}\t${i['Miolo'] || '-'}\t${i.Total}`).join('\n');
    navigator.clipboard.writeText(text);
    toast.success('Copiado!');
  };

  const printBlingData = (platformKey) => {
    const platformData = results[platformKey];
    if (!platformData || !platformData.bling_orders_data || platformData.bling_orders_data.length === 0) {
      toast.error('Nenhum pedido para imprimir.');
      return;
    }

    const orders = platformData.bling_orders_data;
    let ordersHtml = '';

    orders.forEach((order) => {
      ordersHtml += `
        <div class="stamp-card" style="border: 1px solid #000; border-radius: 8px; padding: 20px; background-color: #fff; width: 100%; height: 100vh; box-sizing: border-box; page-break-after: always; display: flex; flex-direction: column; position: relative;">
          <div class="stamp-header" style="font-size: 1.5rem; margin-bottom: 30px; justify-content: space-between; display: flex;">
            <div>
              <div style="padding: 15px 0;">Nome: ${order.contato?.nome || 'N/A'}</div>
              <div style="padding: 15px 0;">CPF: ${order.contato?.numeroDocumento || 'N/A'}</div>
              ${order.contato?.endereco ? `<div style="padding: 15px 0;">${order.contato.endereco}</div>` : ''}
            </div>
            <div></div>
            <div>
              <div style="padding: 15px 0;">
                <img src="/static/img/${platformKey.toLowerCase()}.svg" alt="Platform Icon" height="20" style="margin-right: 10px;" />${platformKey}
              </div>
              <div style="padding: 15px 0;">${order.numeroLoja || 'N/A'}</div>
            </div>
          </div>
          <div class="stamp-content" style="font-family: Arial, sans-serif; flex-grow: 1; display: flex; flex-direction: column; justify-content: space-between;">
            <div class="order-info" style="text-align: center; font-size: 2.5rem; margin-bottom: 40px;">
              <div>Pedido ${order.numero || order.id || 'N/A'}</div>
            </div>
            ${order.itens?.map((item) => `
              <div class="item" style="display: flex; align-items: center; border-top: 1px solid #ddd; padding: 15px 0; margin-bottom: 15px;">
                <div class="item-details" style="width: 80%; font-size: 1.2rem;">
                  <div>${item.descricao || 'N/A'}</div>
                  ${item.variacao && item.variacao !== '' ? `<div style="font-size: 0.8rem; color: #666;">${item.variacao}</div>` : ''}
                  <div><strong>${item.codigo || 'N/A'}</strong></div>
                  ${item.original_id && item.original_id !== order.numeroLoja ? `<div style="font-size: 0.8rem; color: #666;">Ref: ${item.original_id}</div>` : ''}
                  ${item.personalizations && item.personalizations.length > 0 ? `
                    <div style="margin-top: 5px;">
                      ${item.personalizations.map((p) => `
                        ${p.customization_name ? `
                          <div style="font-size: 1.1rem; color: #d32f2f; font-weight: bold; border: 1px dashed #d32f2f; padding: 2px 5px; margin-top: 5px; display: inline-block;">
                            ${p.customization_name}
                            ${p.customization_initial ? `(${p.customization_initial})` : ''}
                            ${p.quantity_to_personalize > 1 ? `<span style="background-color: #ffc107; color: #000; padding: 2px 5px; border-radius: 3px; margin-left: 5px;">x${p.quantity_to_personalize}</span>` : ''}
                          </div>
                        ` : ''}
                      `).join('')}
                    </div>
                  ` : ''}
                </div>
                <div class="item-quantity" style="width: 10%; text-align: center; font-size: 1.6rem;">${item.quantidade || 1}</div>
                <div class="item-price" style="width: 10%; text-align: center; font-size: 0.8rem;">R$ ${(item.valor || 0).toFixed(2)}</div>
              </div>
            `).join('') || ''}
            <div class="item" style="display: flex; align-items: center; border-top: 1px solid #ddd; padding: 15px 0; margin-bottom: 15px;">
              <div class="item-details" style="width: 80%; font-size: 1.2rem;"></div>
              <div class="item-quantity" style="width: 10%; text-align: center; font-size: 1.6rem;"></div>
              <div class="item-price" style="width: 10%; text-align: center; font-size: 0.8rem;">R$ ${(order.totalProdutos || 0).toFixed(2)}</div>
            </div>
            <div class="total-items" style="text-align: center; margin-top: auto; margin-bottom: 20px;">
              <span style="font-size: 2.5rem;">${order.total_items || 0} ${order.total_items > 1 ? 'itens' : 'item'}</span>
            </div>
          </div>
          <div class="stamp-footer" style="display: flex; justify-content: space-between; margin-top: auto; padding-top: 20px;">
            <div>
              ${order.hasCustomItem === 1 ? order.itens?.map((item) => item.custom_tag && item.custom_tag !== '' && item.custom_tag !== null ? `<div class="custom-tag" style="font-size: 1.8rem; font-weight: bolder; border: 1px solid #000; padding: 10px 25px;">${item.custom_tag}</div>` : '').join('') || '' : ''}
            </div>
            <div>${new Date().toLocaleDateString('pt-BR')}</div>
          </div>
        </div>
      `;
    });

    const htmlContent = `
      <html>
        <head>
          <style>
            @media print {
              .stamp-card {
                width: 210mm;
                height: 297mm;
                margin: 0;
                padding: 20mm;
                box-shadow: none;
                border: none;
                page-break-after: always;
              }
              body {
                margin: 0;
                padding: 0;
              }
            }
          </style>
        </head>
        <body>${ordersHtml}</body>
      </html>
    `;

    const iframe = document.createElement('iframe');
    iframe.style.position = 'absolute';
    iframe.style.top = '-9999px';
    iframe.style.left = '-9999px';
    document.body.appendChild(iframe);

    iframe.onload = () => {
      iframe.contentWindow.print();
      setTimeout(() => iframe.remove(), 1000);
    };

    iframe.contentDocument.open();
    iframe.contentDocument.write(htmlContent);
    iframe.contentDocument.close();
  };

  const generateNFE = (platformKey) => {
    const platformData = results[platformKey];
    if (!platformData || !platformData.bling_orders_id_numero) {
      toast.error('Nenhum pedido para gerar NF.');
      return;
    }

    if (!selectedBlingAccountId) {
      toast.error('Selecione uma conta Bling para gerar NF.');
      return;
    }

    let blingOrders = [];
    try {
      if (typeof platformData.bling_orders_id_numero === 'string') {
        blingOrders = JSON.parse(platformData.bling_orders_id_numero.replace(/'/g, '"'));
      } else {
        blingOrders = platformData.bling_orders_id_numero;
      }
    } catch (error) {
      console.error('Error parsing JSON:', error);
      toast.error('Erro ao processar os pedidos.');
      return;
    }

    if (!blingOrders || blingOrders.length === 0) {
      toast.error('Nenhum pedido para gerar NF.');
      return;
    }

    setNfeGenerating(true);
    setNfeResults([]);
    setNfeSidebarOpen(true);

    // Close previous EventSource if exists
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const platformLower = platformKey.toLowerCase();
    const eventSource = new EventSource(`/api/v2/nfe/generate_nfe?platform=${encodeURIComponent(platformLower)}&bling_orders=${encodeURIComponent(JSON.stringify(blingOrders))}&instance_id=${encodeURIComponent(selectedBlingAccountId)}`);
    eventSourceRef.current = eventSource;

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.status === 'complete') {
        toast.success('Processamento concluído!');
        setNfeGenerating(false);
        eventSource.close();
        return;
      }

      if (data.status === 'processing') {
        setNfeResults((prev) => [...prev, data]);
      } else if (data.status === 'error') {
        // Extract detailed error message from API response
        let errorMessage = data.error || 'Erro desconhecido';
        if (data.error_details) {
          try {
            const errorDetails = typeof data.error_details === 'string' 
              ? JSON.parse(data.error_details) 
              : data.error_details;
            if (errorDetails.error?.fields?.[0]?.msg) {
              errorMessage = errorDetails.error.fields[0].msg;
            }
          } catch (e) {
            console.error('Error parsing error_details:', e);
          }
        }
        const resultWithError = { ...data, error: errorMessage };
        setNfeResults((prev) => [...prev, resultWithError]);
        toast.error(`Erro: ${errorMessage}`);
      }
    };

    eventSource.onerror = (error) => {
      console.error('EventSource failed:', error);
      toast.error('Erro na conexão com o servidor.');
      setNfeGenerating(false);
      eventSource.close();
    };
  };

  return (
    <div className="flex flex-col w-full max-w-7xl mx-auto pb-20">
      <div className="flex justify-between items-center mb-8 bg-white p-4 rounded-lg border shadow-sm">
        <div>
            <h1 className="text-2xl font-bold tracking-tight">Consolidar Produção</h1>
            <p className="text-muted-foreground">Agrupe pedidos e gere demandas de fabricação.</p>
        </div>
        <div className="flex gap-2">
            <Button variant="outline" onClick={() => window.location.href = '/producao/demanda/rascunhos'} className="gap-2">
                <ClipboardList className="h-4 w-4" /> Rascunhos Automáticos
            </Button>
            <Button variant={opMode === 'legacy' ? 'destructive' : 'outline'} onClick={toggleOpMode} disabled={updatingMode} className="gap-2">
                <Database className="h-4 w-4" /> Base: {opMode.toUpperCase()}
            </Button>
        </div>
      </div>

      {!results ? (
        <Card className="shadow-md">
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Filter className="h-5 w-5 text-primary" /> Origem dos Dados</CardTitle>
          </CardHeader>
          <CardContent className="pt-6">
            {/* Status de Processamento em Background */}
            {asyncProcessing && (
              <div className="mb-8 p-6 bg-blue-50 border-2 border-blue-200 rounded-xl animate-in slide-in-from-top duration-500 shadow-sm">
                <div className="flex flex-col md:flex-row items-center justify-between gap-6">
                  <div className="flex items-center gap-4 w-full md:w-auto">
                    <div className="p-3 bg-blue-100 rounded-full">
                      <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
                    </div>
                    <div>
                      <h3 className="text-lg font-bold text-blue-900">Processamento em Andamento</h3>
                      <p className="text-sm text-blue-700 font-medium">
                        Status atual: <span className="bg-blue-200 px-2 py-0.5 rounded uppercase text-xs">{asyncProcessing.status || 'Enfileirado'}</span>
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-col items-center md:items-end gap-3 w-full md:w-64">
                    <div className="w-full bg-blue-200 rounded-full h-3 overflow-hidden">
                      <div
                        className="bg-blue-600 h-full transition-all duration-1000 ease-in-out"
                        style={{ width: asyncProcessing.status === 'PROCESSANDO' ? '65%' : '20%' }}
                      />
                    </div>
                    <p className="text-[10px] text-blue-500 font-medium uppercase tracking-wider text-center md:text-right">
                      Seu arquivo está sendo processado nos servidores. Você pode aguardar nesta tela.
                    </p>
                  </div>
                </div>
              </div>
            )}

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

                    <div className="flex gap-3">
                      <Button type="submit" disabled={loading} className="flex-1 h-12 text-lg">
                          {loading ? <Loader2 className="animate-spin mr-2" /> : <Upload className="mr-2" />} Processar
                      </Button>
                    </div>
                </form>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-6 animate-in zoom-in-95 duration-300">
          <div className="flex flex-wrap justify-between items-center gap-4 bg-white p-4 rounded-lg border shadow-sm sticky top-0 z-20">
            <h2 className="text-xl font-bold flex items-center gap-2"><CheckCircle2 className="h-6 w-6 text-green-600" /> Itens Consolidados</h2>
            <div className="flex gap-3">
              <Button variant="outline" onClick={() => setResults(null)}>Voltar / Novo</Button>
              <Button className="bg-green-600 hover:bg-green-700" onClick={() => {
                const canal = channels.find(c => c.id.toString() === selectedChannel || (c.slug || c.nome) === selectedChannel);
                if (canal && canal.horario_coleta) {
                  setDemandHorarioColeta(canal.horario_coleta);
                }
                setModalOpen('demand');
              }}>Gerar Demanda</Button>
            </div>
          </div>

          {Object.entries(results).map(([key, data]) => (
            <Card key={key}>
              <CardHeader className="flex flex-row items-center justify-between border-b bg-muted/20 py-3">
                <CardTitle className="text-lg">{key} ({data.total_pedidos_plataforma} pedidos)</CardTitle>
                <div className="flex gap-2">
                  {data.options?.print_orders && data.bling_orders_data && data.bling_orders_data.length > 0 && (
                    <>
                      <Button variant="outline" size="sm" onClick={() => printBlingData(key)} disabled={nfeGenerating}>
                        <Printer className="h-4 w-4 mr-2" /> Imprimir {data.bling_orders_data.length} pedidos
                      </Button>
                      <Select value={selectedBlingAccountId} onValueChange={setSelectedBlingAccountId}>
                        <SelectTrigger className="w-[200px]">
                          <SelectValue placeholder="Conta Bling" />
                        </SelectTrigger>
                        <SelectContent>
                          {blingAccounts.length === 0 ? (
                            <SelectItem value="" disabled>Nenhuma conta</SelectItem>
                          ) : (
                            blingAccounts.map((account) => (
                              <SelectItem key={account.id} value={String(account.id)}>
                                {account.instance_name || `Conta ${account.id}`}
                              </SelectItem>
                            ))
                          )}
                        </SelectContent>
                      </Select>
                      <Button variant="outline" size="sm" onClick={() => generateNFE(key)} disabled={nfeGenerating}>
                        <Database className="h-4 w-4 mr-2" /> Gerar NFs
                      </Button>
                    </>
                  )}
                  <Button variant="ghost" size="sm" onClick={() => handleCopyTable(key)}><Copy className="h-4 w-4 mr-2" /> Copiar</Button>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                    <TableHeader><TableRow><TableHead>Produto</TableHead><TableHead>SKU</TableHead><TableHead>Miolo</TableHead><TableHead className="text-right">Qtd</TableHead><TableHead>Status</TableHead><TableHead>Ação</TableHead></TableRow></TableHeader>
                    <TableBody>
                        {data.capas_miolos_data.map((item, idx) => (
                            <TableRow key={idx}>
                                <TableCell className="font-medium text-xs">{item['Nome do Produto'] || item['Título']}</TableCell>
                                <TableCell className="text-xs font-mono">{item['SKU'] || item['Código']}</TableCell>
                                <TableCell className="text-xs">{item['Miolo'] || '-'}</TableCell>
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

          {/* Modal de Processamento Assíncrono */}
          {asyncProcessing && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
              <Card className="max-w-md w-full shadow-2xl animate-in slide-in-from-bottom-4">
                <CardHeader className="border-b">
                  <CardTitle className="flex items-center gap-2">
                    <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
                    Processando em Background
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4 pt-6">
                  <div className="text-center space-y-2">
                    <p className="text-muted-foreground">Seu arquivo está sendo processado...</p>
                    <div className="flex items-center justify-center gap-2">
                      <span className="text-sm font-medium">Status:</span>
                      <span className={`text-sm font-bold px-3 py-1 rounded-full ${
                        asyncProcessing.status === 'PRONTO' ? 'bg-green-100 text-green-800' :
                        asyncProcessing.status === 'ERRO' ? 'bg-red-100 text-red-800' :
                        'bg-blue-100 text-blue-800'
                      }`}>
                        {asyncProcessing.status || 'PROCESSANDO'}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-4">
                      Esta janela será atualizada automaticamente quando o processamento for concluído.
                    </p>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {modalOpen === 'demand' && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
              <Card className="max-w-md w-full shadow-2xl animate-in slide-in-from-bottom-4">
                <CardHeader className="border-b"><CardTitle>Gerar Nova Demanda</CardTitle></CardHeader>
                <CardContent className="space-y-4 pt-6">
                  <div className="space-y-2"><Label>Nome da Demanda</Label><Input value={demandName} onChange={(e) => setDemandName(e.target.value)} placeholder="Ex: Demanda Shopee - Março" /></div>
                  <div className="space-y-2"><Label>Data de Entrega</Label><Input type="date" value={demandDate} onChange={(e) => setDemandDate(e.target.value)} /></div>
                  <div className="space-y-2"><Label>Horário de Coleta (Opcional)</Label><Input type="time" value={demandHorarioColeta} onChange={(e) => setDemandHorarioColeta(e.target.value)} /></div>
                  <div className="space-y-2"><Label>Observações (Opcional)</Label><Input value={demandObservacoes} onChange={(e) => setDemandObservacoes(e.target.value)} placeholder="Ex: Urgente, entregar na portaria..." /></div>
                  <Button onClick={() => handleGenerateDemand(Object.keys(results)[0])} disabled={creatingDemand} className="w-full bg-primary h-12 text-lg">
                    {creatingDemand ? <Loader2 className="animate-spin mr-2" /> : null} Gerar Demanda
                  </Button>
                  <Button variant="ghost" onClick={() => setModalOpen(null)} className="w-full">Cancelar</Button>
                </CardContent>
              </Card>
            </div>
          )}

          {/* NFE Sidebar */}
          <div className={`fixed inset-y-0 right-0 z-50 w-96 bg-white shadow-2xl transform transition-transform duration-300 ease-in-out ${nfeSidebarOpen ? 'translate-x-0' : 'translate-x-full'}`}>
            <div className="flex flex-col h-full">
              <div className="flex items-center justify-between p-4 border-b bg-muted">
                <h3 className="text-lg font-bold">Notas Fiscais</h3>
                <Button variant="ghost" size="sm" onClick={() => setNfeSidebarOpen(false)}>
                  <X className="h-5 w-5" />
                </Button>
              </div>
              <div className="flex-1 overflow-y-auto p-4">
                {nfeGenerating && nfeResults.length === 0 && (
                  <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
                    <Loader2 className="h-8 w-8 animate-spin mb-2" />
                    <p>Processando pedidos...</p>
                  </div>
                )}
                {nfeResults.length > 0 && (
                  <ul className="space-y-2">
                    {nfeResults.map((result, idx) => (
                      <li key={idx} className={`p-3 rounded-lg border ${result.success ? 'border-green-200 bg-green-50' : 'border-red-200 bg-red-50'}`}>
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-medium">
                            #{result.order?.numero || result.order?.id || 'N/A'}
                          </span>
                          <span className={`text-sm ${result.success ? 'text-green-600' : 'text-red-600'}`}>
                            {result.success ? '✓' : '✗'}
                          </span>
                        </div>
                        {result.success && result.order?.nfe_id && (
                          <a
                            href={`https://www.bling.com.br/notas.fiscais.php#edit/${result.order.nfe_id}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-sm text-blue-600 hover:underline"
                          >
                            NF-e
                          </a>
                        )}
                        {result.error && (
                          <p className="text-sm text-red-600 mt-1">{result.error}</p>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default ConsolidarPage;
