import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { AlertTriangle, ArrowRight, CheckCircle2, Copy, Database, Filter, Loader2, Printer, TowerControl, Upload, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useSecaoSidebar } from '@/lib/hooks/useSecaoSidebar';

const PLATFORM_OPTIONS = [
  { label: 'Shopee', moduleId: 'shopee' },
  { label: 'MercadoLivre', moduleId: 'mercadolivre' },
  { label: 'Amazon', moduleId: 'amazon' },
  { label: 'Shein', moduleId: 'shein' }
];

// O resultado do casamento, na ordem em que ele decide o proximo clique:
// primeiro o que a base ainda nao tem (unico problema que exige acao fora
// daqui), depois o que ja saiu, e por ultimo os nos da torre — o caminho.
//
// "Nao encontrado" e "ja despachado" aparecem separados de proposito. Somados
// num unico contador de "faltando", eles fazem o operador reimportar pedidos
// que ele mesmo produziu ontem.
function ConferenciaCard({ conferencia, onAbrirNaTorre }) {
  const { total_refs, encontrados, nao_encontrados = [], fora_da_torre = [], nos = [] } = conferencia;
  const naTorre = nos.reduce((soma, no) => soma + no.qtd_pedidos, 0);

  return (
    <Card className="border-slate-900">
      <CardHeader className="border-b bg-muted/20 py-3">
        <CardTitle className="text-lg">Conferência contra a base</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 pt-5">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <div>
            <div className="text-2xl font-semibold tabular-nums">{total_refs}</div>
            <div className="text-xs text-muted-foreground">pedidos no arquivo</div>
          </div>
          <div>
            <div className="text-2xl font-semibold tabular-nums">{encontrados}</div>
            <div className="text-xs text-muted-foreground">encontrados na base</div>
          </div>
          <div>
            <div className="text-2xl font-semibold tabular-nums text-emerald-700">{naTorre}</div>
            <div className="text-xs text-muted-foreground">pendentes na torre</div>
          </div>
          <div>
            <div className={'text-2xl font-semibold tabular-nums ' + (nao_encontrados.length ? 'text-amber-700' : '')}>
              {nao_encontrados.length}
            </div>
            <div className="text-xs text-muted-foreground">a base ainda não tem</div>
          </div>
        </div>

        {nao_encontrados.length > 0 && (
          <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <div>
              {nao_encontrados.length} pedido{nao_encontrados.length > 1 ? 's do arquivo não chegaram' : ' do arquivo não chegou'}{' '}
              na base pelo ID de origem. Verifique a integração do marketplace antes de consolidar o lote.
              <div className="mt-1 font-mono">
                {nao_encontrados.slice(0, 10).join(', ')}
                {nao_encontrados.length > 10 && ` e mais ${nao_encontrados.length - 10}`}
              </div>
            </div>
          </div>
        )}

        {fora_da_torre.length > 0 && (
          <div className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">
            {fora_da_torre.length} pedido{fora_da_torre.length > 1 ? 's já saíram' : ' já saiu'} da torre
            (despachado, cancelado ou em demanda já publicada). Estão na base — só não entram em lote novo.
            <div className="mt-1 font-mono">
              {fora_da_torre.slice(0, 10).map((p) => p.numero_pedido || p.ref).join(', ')}
              {fora_da_torre.length > 10 && ` e mais ${fora_da_torre.length - 10}`}
            </div>
          </div>
        )}

        {nos.length > 0 ? (
          <div>
            <div className="mb-2 text-sm font-medium">Onde estes pedidos caem na torre</div>
            <div className="space-y-2">
              {nos.map((no) => (
                <button
                  key={`${no.integration_id}-${no.modalidade_id}`}
                  type="button"
                  onClick={() => onAbrirNaTorre(no)}
                  className="flex w-full items-center justify-between gap-3 rounded-md border px-4 py-3 text-left transition-colors hover:border-primary/60"
                >
                  <div className="min-w-0">
                    <div className="text-sm font-medium">
                      {no.marketplace_nome} · {no.modalidade_nome}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {no.qtd_pedidos} {no.qtd_pedidos === 1 ? 'pedido do arquivo' : 'pedidos do arquivo'} neste nó
                    </div>
                  </div>
                  <span className="flex shrink-0 items-center gap-1 text-sm text-primary">
                    Consolidar na torre
                    <ArrowRight className="h-4 w-4" />
                  </span>
                </button>
              ))}
            </div>
            {/* A torre consolida o no inteiro, nao o recorte do arquivo. Dizer
                isso aqui evita a leitura de que o botao "leva estes pedidos":
                ele leva ao no, que pode ter mais pedidos — os que entraram
                depois da exportacao e saem na mesma coleta. */}
            <p className="mt-2 text-xs text-muted-foreground">
              A torre consolida o nó inteiro: pode incluir pedidos que entraram depois desta exportação
              e saem na mesma coleta.
            </p>
          </div>
        ) : (
          <div className="rounded-md border border-dashed p-4 text-center text-sm text-muted-foreground">
            Nenhum pedido deste arquivo está pendente na torre.
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Conferencia de arquivo — nao geracao de demanda.
//
// Esta tela recebe uma planilha exportada do painel do marketplace e responde
// a uma unica pergunta: o que esta no painel ja chegou na base? Antes ela
// respondia gerando a demanda direto do arquivo, e esse era o problema: o
// arquivo nao sabe a modalidade logistica nem a janela de coleta do pedido,
// entao o lote que saia daqui nao correspondia a nenhum no da Torre de
// Despacho — e o mesmo pedido podia acabar em duas demandas.
//
// A demanda agora nasce em um lugar so. O que esta tela entrega e o casamento
// pelo ID de origem do marketplace e o caminho ate o no da torre onde aqueles
// pedidos caem.
function ConsolidarPage() {
  const navigate = useNavigate();
  const [file, setFile] = useState(null);
  const [selectedPlatform, setSelectedPlatform] = useState('');
  const [selectedMarketplaceIntegrationId, setSelectedMarketplaceIntegrationId] = useState('');
  const [marketplaceIntegrations, setMarketplaceIntegrations] = useState([]);
  const [products, setProducts] = useState([]);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [printOrders, setPrintOrders] = useState(false);
  const [isFlex, setIsFlex] = useState(false);
  const [persistNewOrders, setPersistNewOrders] = useState(true);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);

  // Operational Mode State
  const [opMode, setOpMode] = useState('v2');
  const [updatingMode, setUpdatingMode] = useState(false);

  // Conferencia contra a base (casamento pelo ID de origem)
  const [conferencia, setConferencia] = useState(null);
  const [conferindo, setConferindo] = useState(false);

  // A barra lateral vem do registro unico de navegacao (secao "Pedidos").
  useSecaoSidebar();

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

    fetchProducts();
    fetchMode();
    fetchBlingAccounts();
  }, []);

  useEffect(() => {
    const fetchMarketplaceIntegrations = async () => {
      if (!selectedPlatform) {
        setMarketplaceIntegrations([]);
        setSelectedMarketplaceIntegrationId('');
        return;
      }

      const platformOption = PLATFORM_OPTIONS.find((item) => item.label === selectedPlatform);
      if (!platformOption) return;

      try {
        const response = await fetch(`/api/v2/marketplace/installed?module_id=${encodeURIComponent(platformOption.moduleId)}`);
        const data = await response.json();
        const installations = data.installations || [];
        setMarketplaceIntegrations(installations);

        setSelectedMarketplaceIntegrationId((current) => {
          if (installations.some((item) => String(item.id) === current)) {
            return current;
          }
          return installations[0] ? String(installations[0].id) : '';
        });
      } catch (error) {
        setMarketplaceIntegrations([]);
        setSelectedMarketplaceIntegrationId('');
        toast.error('Erro ao carregar integracoes da plataforma.');
      }
    };

    fetchMarketplaceIntegrations();
  }, [selectedPlatform]);

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
    if (!file || !selectedPlatform) {
      toast.error('Selecione o arquivo e a plataforma.');
      return;
    }

    setLoading(true);
    const formData = new FormData();
    formData.append('file', file);
    const platformOption = PLATFORM_OPTIONS.find((item) => item.label === selectedPlatform);
    formData.append('platform', selectedPlatform);
    formData.append('module_id', platformOption?.moduleId || '');
    if (selectedMarketplaceIntegrationId) formData.append('marketplace_integration_id', selectedMarketplaceIntegrationId);
    if (selectedBlingAccountId) formData.append('bling_integration_id', selectedBlingAccountId);
    if (startDate) formData.append('start_date', startDate);
    if (endDate) formData.append('end_datetime', endDate);
    formData.append('print-orders', printOrders);
    formData.append('is_flex', isFlex);
    formData.append('persist_new_orders', persistNewOrders);
    formData.append('mode', opMode);

    try {
      const response = await fetch('/api/v2/consolidar', {
        method: 'POST',
        body: formData
      });
      if (!response.ok) throw new Error('Erro ao processar arquivo.');
      const data = await response.json();
      setResults(data);
      setConferencia(null);
      const firstPlatformKey = Object.keys(data)[0];
      const resolvedBlingId = data[firstPlatformKey]?.options?.bling_integration_id;
      if (resolvedBlingId) setSelectedBlingAccountId(String(resolvedBlingId));
      toast.success('Processado com sucesso!');
    } catch (error) {
      toast.error(error.message);
    } finally {
      setLoading(false);
    }
  };

  // Junta os IDs de origem que o arquivo trouxe. `pedidos_origem` vem do
  // processamento com os dois campos possiveis; `order_refs` e a forma crua
  // que o caminho assincrono devolve. Reunir os dois aqui evita que metade do
  // arquivo pareca "pedido que a base nao tem" so porque veio pelo outro
  // caminho.
  const refsDoResultado = (platformKey) => {
    const data = results?.[platformKey];
    if (!data) return [];
    const refs = new Set();
    for (const item of data.capas_miolos_data || []) {
      for (const pedido of item.pedidos_origem || []) {
        const ref = pedido?.codigo_pedido_externo || pedido?.marketplace_order_id || pedido;
        if (ref) refs.add(String(ref).trim());
      }
      for (const ref of item.order_refs || []) {
        if (ref) refs.add(String(ref).trim());
      }
    }
    for (const order of data.bling_orders_data || []) {
      const ref = order?.numeroLoja;
      if (ref) refs.add(String(ref).trim());
    }
    return [...refs].filter(Boolean);
  };

  const conferirContraBase = async (platformKey) => {
    const refs = refsDoResultado(platformKey);
    if (refs.length === 0) {
      toast.error('O arquivo não trouxe nenhum ID de pedido para conferir.');
      return;
    }
    setConferindo(true);
    try {
      const response = await fetch('/api/v2/consolidar/casar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refs }),
      });
      const data = await response.json();
      if (!data.success) throw new Error(data.error || 'Não foi possível conferir o arquivo.');
      setConferencia(data.data);
    } catch (error) {
      toast.error(error.message);
    } finally {
      setConferindo(false);
    }
  };

  // Abre o no na Torre de Despacho. A tela nao manda a lista de pedidos: manda
  // a CHAVE do no (marketplace + modalidade), que e o que a torre entende. O
  // escopo que ela vai montar e o do no inteiro, nao o recorte do arquivo — e
  // isso e proposital: consolidar so o que estava na planilha deixaria de fora
  // os pedidos que entraram depois da exportacao e sairiam na mesma coleta.
  const abrirNaTorre = (no) => {
    const params = new URLSearchParams();
    if (no.integration_id !== null && no.integration_id !== undefined) {
      params.set('integration_id', no.integration_id);
    }
    if (no.modalidade_id !== null && no.modalidade_id !== undefined) {
      params.append('modalidade_ids', no.modalidade_id);
      params.set('modalidade_id', no.modalidade_id);
    }
    params.set('marketplace_nome', no.marketplace_nome || '');
    params.set('modalidade_nome', no.modalidade_nome || '');
    params.set('aba', 'hoje');
    navigate(`/despacho/escopo?${params.toString()}`);
  };

  // Async processing functions
  const startAsyncProcessing = async (e) => {
    e.preventDefault();
    if (!file || !selectedPlatform) {
      toast.error('Selecione o arquivo e a plataforma.');
      return;
    }

    setLoading(true);
    const formData = new FormData();
    const platformOption = PLATFORM_OPTIONS.find((item) => item.label === selectedPlatform);
    formData.append('file', file);
    formData.append('platform', selectedPlatform);
    formData.append('module_id', platformOption?.moduleId || '');
    if (selectedMarketplaceIntegrationId) formData.append('marketplace_integration_id', selectedMarketplaceIntegrationId);
    if (selectedBlingAccountId) formData.append('bling_integration_id', selectedBlingAccountId);
    if (startDate) formData.append('start_date', startDate);
    if (endDate) formData.append('end_datetime', endDate);
    formData.append('print-orders', printOrders);
    formData.append('is_flex', isFlex);
    formData.append('persist_new_orders', persistNewOrders);
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
          setConferencia(null);
          setAsyncProcessing(null);
          const firstPlatformKey = Object.keys(processedResult)[0];
          const resolvedBlingId = processedResult[firstPlatformKey]?.options?.bling_integration_id;
          if (resolvedBlingId) setSelectedBlingAccountId(String(resolvedBlingId));
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
            <h1 className="text-2xl font-bold tracking-tight">Consolidar arquivo</h1>
            <p className="text-muted-foreground">
              Confira uma planilha do marketplace contra a base. O lote é consolidado na Torre de Despacho.
            </p>
        </div>
        <div className="flex gap-2">
            <Link to="/despacho">
              <Button variant="outline" className="gap-2">
                <TowerControl className="h-4 w-4" /> Torre de Despacho
              </Button>
            </Link>
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
                          <Label>Plataforma</Label>
                          <Select value={selectedPlatform} onValueChange={setSelectedPlatform}>
                            <SelectTrigger className="bg-white"><SelectValue placeholder="Selecione a plataforma" /></SelectTrigger>
                            <SelectContent>{PLATFORM_OPTIONS.map((platform) => <SelectItem key={platform.moduleId} value={platform.label}>{platform.label}</SelectItem>)}</SelectContent>
                          </Select>
                        </div>
                        <div className="space-y-2">
                          <Label>Integracao Marketplace</Label>
                          <Select value={selectedMarketplaceIntegrationId} onValueChange={setSelectedMarketplaceIntegrationId} disabled={!selectedPlatform || marketplaceIntegrations.length === 0}>
                            <SelectTrigger className="bg-white"><SelectValue placeholder={selectedPlatform ? 'Selecione a integracao' : 'Escolha a plataforma primeiro'} /></SelectTrigger>
                            <SelectContent>
                              {marketplaceIntegrations.length === 0 ? (
                                <SelectItem value="__empty" disabled>Nenhuma integracao ativa</SelectItem>
                              ) : (
                                marketplaceIntegrations.map((integration) => (
                                  <SelectItem key={integration.id} value={String(integration.id)}>{integration.instance_name}</SelectItem>
                                ))
                              )}
                            </SelectContent>
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
                        <div className="space-y-1">
                          <div className="flex items-center space-x-2">
                            <Checkbox id="print_orders" checked={printOrders} onCheckedChange={setPrintOrders} />
                            <Label htmlFor="print_orders" className="cursor-pointer">Preparar folhas de impressao</Label>
                          </div>
                          <p className="text-xs text-muted-foreground">A montagem usa primeiro os pedidos locais e so consulta o Bling para o que faltar.</p>
                        </div>
                        <div className="flex items-center space-x-2">
                          <Checkbox id="is_flex" checked={isFlex} onCheckedChange={setIsFlex} />
                          <Label htmlFor="is_flex" className="text-blue-600 font-bold cursor-pointer">Apenas Pedidos FLEX</Label>
                        </div>
                        <div className="flex items-center space-x-2">
                          <Checkbox id="persist_new_orders" checked={persistNewOrders} onCheckedChange={setPersistNewOrders} />
                          <Label htmlFor="persist_new_orders" className="cursor-pointer">Persistir novos pedidos</Label>
                        </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6 border-t border-b py-4">
                        <div className="space-y-2">
                          <Label>Conta Bling (Opcional)</Label>
                          <Select value={selectedBlingAccountId || 'auto'} onValueChange={(value) => setSelectedBlingAccountId(value === 'auto' ? '' : value)}>
                            <SelectTrigger className="bg-white"><SelectValue placeholder="Resolver automaticamente" /></SelectTrigger>
                            <SelectContent>
                              <SelectItem value="auto">Resolver automaticamente</SelectItem>
                              {blingAccounts.map((account) => (
                                <SelectItem key={account.id} value={String(account.id)}>
                                  {account.instance_name || `Conta ${account.id}`}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
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
              <Button variant="outline" onClick={() => { setResults(null); setConferencia(null); }}>Voltar / Novo</Button>
              <Button
                className="bg-green-600 hover:bg-green-700"
                disabled={conferindo}
                onClick={() => conferirContraBase(Object.keys(results)[0])}
              >
                {conferindo ? <Loader2 className="animate-spin mr-2 h-4 w-4" /> : null}
                Conferir contra a base
              </Button>
            </div>
          </div>

          {conferencia && (
            <ConferenciaCard conferencia={conferencia} onAbrirNaTorre={abrirNaTorre} />
          )}

          {Object.entries(results).map(([key, data]) => (
            <Card key={key}>
              <CardHeader className="flex flex-row items-center justify-between border-b bg-muted/20 py-3">
                <CardTitle className="text-lg">{key} ({data.total_pedidos_plataforma} pedidos)</CardTitle>
                <div className="flex gap-2">
                  {data.print_order_resolution && (
                    <div className="flex items-center gap-2 rounded-md border bg-white px-3 py-1 text-xs text-muted-foreground">
                      <span>Local: {data.print_order_resolution.local}</span>
                      <span>Bling: {data.print_order_resolution.bling}</span>
                      {data.print_order_resolution.not_found > 0 && <span>Faltando: {data.print_order_resolution.not_found}</span>}
                    </div>
                  )}
                  {data.options?.print_orders && data.bling_orders_data && data.bling_orders_data.length > 0 && (
                    <>
                      <Button variant="outline" size="sm" onClick={() => printBlingData(key)} disabled={nfeGenerating}>
                        <Printer className="h-4 w-4 mr-2" /> Imprimir {data.bling_orders_data.length} pedidos
                      </Button>
                      <Select value={selectedBlingAccountId || 'auto'} onValueChange={(value) => setSelectedBlingAccountId(value === 'auto' ? '' : value)}>
                        <SelectTrigger className="w-[200px]">
                          <SelectValue placeholder="Conta Bling" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="auto">Automatica</SelectItem>
                          {blingAccounts.length === 0 ? (
                            <SelectItem value="__no-account" disabled>Nenhuma conta</SelectItem>
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
