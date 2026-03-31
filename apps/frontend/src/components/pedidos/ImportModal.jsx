import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Database, FileSpreadsheet, Loader2, Upload, Calendar, Clock } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

export default function ImportModal({
  open,
  onOpenChange,
  onImportarBling,
  onUploadPlanilha,
  importando,
}) {
  const [activeTab, setActiveTab] = useState('planilha');
  const [channels, setChannels] = useState([]);

  // Estado para Bling
  const [configId, setConfigId] = useState('');
  const [blingConfigs, setBlingConfigs] = useState([]);
  const [dias, setDias] = useState(7);
  const [useDateRange, setUseDateRange] = useState(false);
  const [blingStartDate, setBlingStartDate] = useState('');
  const [blingEndDate, setBlingEndDate] = useState('');
  const [situacaoId, setSituacaoId] = useState(15);

  // Estado para Planilha (igual ao Consolidar)
  const [file, setFile] = useState(null);
  const [canal, setCanal] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [printOrders, setPrintOrders] = useState(false);
  const [isFlex, setIsFlex] = useState(false);

  // Carregar canais e configurações ao abrir o modal
  useEffect(() => {
    if (open) {
      // Carregar canais para aba Planilha
      fetch('/api/v2/cadastros/canal-venda?active_only=true')
        .then((res) => res.json())
        .then((data) => {
          if (data.canais) {
            setChannels(data.canais);
            if (data.canais.length > 0 && !canal) {
              setCanal(data.canais[0].slug || data.canais[0].nome);
            }
          }
        });

      // Carregar configurações de vínculo para aba Bling
      fetch('/api/v2/integracao-canais/configuracoes')
        .then((res) => res.json())
        .then((data) => {
          if (data.success && data.data) {
            setBlingConfigs(data.data);
          }
        });
    }
  }, [open]);

  const handleBlingSubmit = () => {
    const payload = { 
      config_id: configId || null, 
      situacao_id: situacaoId 
    };

    if (useDateRange) {
      payload.data_inicial = blingStartDate;
      payload.data_final = blingEndDate;
    } else {
      payload.dias = dias;
    }

    onImportarBling(payload);
  };

  const handlePlanilhaSubmit = () => {
    if (!file || !canal) return;
    onUploadPlanilha(file, {
      canal,
      startDate,
      endDate,
      printOrders,
      isFlex,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Importar Pedidos</DialogTitle>
          <DialogDescription>
            Selecione a origem dos pedidos para importação e geração de demanda
          </DialogDescription>
        </DialogHeader>

        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="planilha" className="gap-2">
              <FileSpreadsheet className="h-4 w-4" />
              Planilha ERP/Marketplace
            </TabsTrigger>
            <TabsTrigger value="bling" className="gap-2">
              <Database className="h-4 w-4" />
              Bling (API)
            </TabsTrigger>
          </TabsList>

          {/* Tab Planilha (igual ao Consolidar) */}
          <TabsContent value="planilha" className="space-y-4 mt-4">
            <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center gap-2">
                  <Upload className="h-5 w-5 text-primary" />
                  <h3 className="font-semibold">Arquivo de Pedidos</h3>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="file">Arquivo</Label>
                    <Input
                      id="file"
                      type="file"
                      accept=".xlsx,.csv"
                      onChange={(e) => setFile(e.target.files?.[0] || null)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Formatos: .xlsx, .csv (Shopee, ML, Amazon)
                    </p>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="canal">Canal de Venda</Label>
                    <Select value={canal} onValueChange={setCanal}>
                      <SelectTrigger>
                        <SelectValue placeholder="Selecione o canal" />
                      </SelectTrigger>
                      <SelectContent>
                        {channels.map((c) => (
                          <SelectItem key={c.id} value={c.slug || c.nome}>
                            {c.nome}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-muted-foreground">
                      {channels.length === 0 ? 'Carregando canais...' : `${channels.length} canal(is) disponível(is)`}
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="start-date">
                      <Calendar className="h-4 w-4 inline mr-1" />
                      Data Envio (Início)
                    </Label>
                    <Input
                      id="start-date"
                      type="date"
                      value={startDate}
                      onChange={(e) => setStartDate(e.target.value)}
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="end-date">
                      <Calendar className="h-4 w-4 inline mr-1" />
                      Data Envio (Fim - Opcional)
                    </Label>
                    <Input
                      id="end-date"
                      type="datetime-local"
                      value={endDate}
                      onChange={(e) => setEndDate(e.target.value)}
                    />
                  </div>
                </div>

                <div className="flex flex-wrap gap-4 items-center pt-2 border-t">
                  <div className="flex items-center space-x-2">
                    <Input
                      type="checkbox"
                      id="print-orders"
                      checked={printOrders}
                      onChange={(e) => setPrintOrders(e.target.checked)}
                      className="w-4 h-4"
                    />
                    <Label htmlFor="print-orders" className="cursor-pointer font-medium">
                      Imprimir pedidos e gerar notas
                    </Label>
                  </div>

                  <div className="flex items-center space-x-2">
                    <Input
                      type="checkbox"
                      id="is-flex"
                      checked={isFlex}
                      onChange={(e) => setIsFlex(e.target.checked)}
                      className="w-4 h-4"
                    />
                    <Label htmlFor="is-flex" className="cursor-pointer font-medium text-blue-600">
                      <Clock className="h-4 w-4 inline mr-1" />
                      Apenas Pedidos FLEX
                    </Label>
                  </div>
                </div>

                <div className="flex gap-3 pt-4">
                  <Button
                    onClick={handlePlanilhaSubmit}
                    disabled={importando || !file || !canal}
                    className="flex-1 h-12"
                  >
                    {importando ? (
                      <>
                        <Loader2 className="animate-spin mr-2" />
                        Processando...
                      </>
                    ) : (
                      <>
                        <Upload className="mr-2" />
                        Processar Planilha
                      </>
                    )}
                  </Button>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Tab Bling */}
          <TabsContent value="bling" className="space-y-4 mt-4">
            <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center gap-2">
                  <Database className="h-5 w-5 text-primary" />
                  <h3 className="font-semibold">Sincronizar do Bling</h3>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                  <p className="text-sm text-blue-700">
                    Busca pedidos diretamente da API do Bling por situação e período.
                  </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="config-id">Loja/Vínculo</Label>
                    <Select value={configId} onValueChange={setConfigId}>
                      <SelectTrigger>
                        <SelectValue placeholder="Todas as lojas ativas" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">Todas as lojas ativas</SelectItem>
                        {blingConfigs.map((cfg) => (
                          <SelectItem key={cfg.id} value={cfg.id}>
                            {cfg.plataforma_nome} - {cfg.canal_nome || 'Sem nome'} ({cfg.bling_loja_id})
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="situacao-id">ID Situação Bling</Label>
                    <Input
                      id="situacao-id"
                      type="number"
                      value={situacaoId}
                      onChange={(e) => setSituacaoId(parseInt(e.target.value) || 15)}
                    />
                    <p className="text-[10px] text-muted-foreground">
                      6: Em Aberto, 15: Em Andamento, 9: Atendido, 24: Verificado
                    </p>
                  </div>
                </div>

                <div className="flex items-center space-x-2 pt-2">
                  <Input
                    type="checkbox"
                    id="use-date-range"
                    checked={useDateRange}
                    onChange={(e) => setUseDateRange(e.target.checked)}
                    className="w-4 h-4"
                  />
                  <Label htmlFor="use-date-range" className="cursor-pointer font-medium">
                    Usar intervalo de datas explícito
                  </Label>
                </div>

                {useDateRange ? (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 animate-in fade-in slide-in-from-top-1">
                    <div className="space-y-2">
                      <Label htmlFor="bling-start-date">Data Inicial</Label>
                      <Input
                        id="bling-start-date"
                        type="date"
                        value={blingStartDate}
                        onChange={(e) => setBlingStartDate(e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="bling-end-date">Data Final</Label>
                      <Input
                        id="bling-end-date"
                        type="date"
                        value={blingEndDate}
                        onChange={(e) => setBlingEndDate(e.target.value)}
                      />
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <Label htmlFor="dias">
                      <Clock className="h-4 w-4 inline mr-1" />
                      Período (últimos X dias)
                    </Label>
                    <Input
                      id="dias"
                      type="number"
                      min="1"
                      max="90"
                      value={dias}
                      onChange={(e) => setDias(parseInt(e.target.value) || 7)}
                    />
                  </div>
                )}

                <div className="flex gap-3 pt-4">
                  <Button
                    onClick={handleBlingSubmit}
                    disabled={importando}
                    className="flex-1 h-12"
                  >
                    {importando ? (
                      <>
                        <Loader2 className="animate-spin mr-2" />
                        Sincronizando...
                      </>
                    ) : (
                      <>
                        <Database className="mr-2" />
                        Sincronizar Pedidos
                      </>
                    )}
                  </Button>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
