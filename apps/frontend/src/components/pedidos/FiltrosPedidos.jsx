import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Building2, CalendarRange, ChevronDown, ChevronUp, Filter, Loader2, Search, Sparkles, Store, Truck, X, Zap } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import FiltrosContextuais from './FiltrosContextuais';

const toISODate = (date) => {
  const copy = new Date(date);
  copy.setMinutes(copy.getMinutes() - copy.getTimezoneOffset());
  return copy.toISOString().slice(0, 10);
};

const addDays = (days) => {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return toISODate(date);
};

function DateRangeFilter({ title, description, icon, startValue, endValue, onChange, presets }) {
  const updateStart = (value) => {
    onChange({
      start: value,
      end: endValue && value && value > endValue ? value : endValue,
    });
  };

  const updateEnd = (value) => {
    onChange({
      start: startValue && value && value < startValue ? value : startValue,
      end: value,
    });
  };

  return (
    <div className="rounded-md border bg-background p-3 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          {icon}
          <div>
            <div className="text-sm font-medium">{title}</div>
            <div className="text-xs text-muted-foreground">{description}</div>
          </div>
        </div>
        {(startValue || endValue) && (
          <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => onChange({ start: '', end: '' })}>
            Limpar
          </Button>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label className="text-xs">Inicio</Label>
          <Input type="date" value={startValue || ''} onChange={(e) => updateStart(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs">Fim</Label>
          <Input type="date" value={endValue || ''} onChange={(e) => updateEnd(e.target.value)} />
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {presets.map((preset) => (
          <Button
            key={preset.label}
            variant="outline"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => onChange({ start: preset.start, end: preset.end })}
          >
            {preset.label}
          </Button>
        ))}
      </div>
    </div>
  );
}

export default function FiltrosPedidos({ filtros, onFiltroChange, onLimparFiltros }) {
  const [origens, setOrigens] = useState([]);
  const [statusList, setStatusList] = useState([]);
  const [blingIntegrations, setBlingIntegrations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filtrosAbertos, setFiltrosAbertos] = useState(false);

  useEffect(() => {
    const carregarDados = async () => {
      try {
        const [origensRes, statusRes, integracoesRes] = await Promise.all([
          fetch('/api/v2/pedidos/origens'),
          fetch('/api/v2/pedidos/status-opcoes'),
          fetch('/api/v2/integracao-canais/integracoes')
        ]);

        const origensData = await origensRes.json();
        const statusData = await statusRes.json();
        const integracoesData = await integracoesRes.json();

        if (origensData.success) {
          setOrigens(origensData.data.origens || []);
        }
        if (statusData.success) {
          setStatusList(statusData.data.status || []);
        }
        if (integracoesData.success) {
          const integracoes = Array.isArray(integracoesData.data) ? integracoesData.data : [];
          setBlingIntegrations(integracoes.filter((item) => item.module_id === 'bling' && item.is_active !== false));
        }
      } catch (error) {
        console.error('Erro ao carregar filtros:', error);
      } finally {
        setLoading(false);
      }
    };

    carregarDados();
  }, []);

  const activeFilters = useMemo(() => {
    const active = [];
    if (filtros.search) active.push('Busca');
    if (filtros.status_id) active.push('Status');
    if (filtros.bling_integration_id) active.push('Conta Bling');
    if (filtros.origem_pedido_key || filtros.canal_venda_id) active.push('Origem');
    if (filtros.has_demanda !== null) active.push('Demanda');
    if (filtros.delivery_start || filtros.delivery_end) active.push('Prazo de envio');
    if (filtros.pedido_date_start || filtros.pedido_date_end) active.push('Data do pedido');
    if (filtros.is_flex) active.push('Entrega rapida');
    if (filtros.is_personalizado) active.push('Personalizados');
    return active;
  }, [filtros]);

  const hasFiltros = activeFilters.length > 0;

  const pedidoDatePresets = [
    { label: 'Hoje', start: toISODate(new Date()), end: toISODate(new Date()) },
    { label: 'Ultimos 7 dias', start: addDays(-6), end: toISODate(new Date()) },
    { label: 'Ultimos 30 dias', start: addDays(-29), end: toISODate(new Date()) },
  ];

  const deliveryPresets = [
    { label: 'Hoje', start: toISODate(new Date()), end: toISODate(new Date()) },
    { label: 'Proximos 7 dias', start: toISODate(new Date()), end: addDays(7) },
    { label: 'Atrasados', start: '', end: addDays(-1) },
  ];

  const handleFiltroContextual = (filtroContextual) => {
    const novosFiltros = {};

    switch (filtroContextual.tipo) {
      case 'canal':
        novosFiltros.canal_venda_id = filtroContextual.canal_venda_id;
        novosFiltros.origem_pedido_key = `canal:${filtroContextual.canal_venda_id}`;
        break;
      case 'flex':
        novosFiltros.canal_venda_id = filtroContextual.canal_venda_id;
        novosFiltros.origem_pedido_key = `canal:${filtroContextual.canal_venda_id}`;
        novosFiltros.is_flex = true;
        break;
      case 'sem_demanda':
        novosFiltros.canal_venda_id = filtroContextual.canal_venda_id;
        novosFiltros.origem_pedido_key = `canal:${filtroContextual.canal_venda_id}`;
        novosFiltros.has_demanda = false;
        break;
      default:
        break;
    }

    onFiltroChange(novosFiltros);
  };

  return (
    <>
      <FiltrosContextuais onFiltroContextual={handleFiltroContextual} />

      <Card className="mb-4">
        <div className="p-4 border-b space-y-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-2">
              <Filter className="h-4 w-4 text-muted-foreground" />
              <span className="font-medium text-sm">Filtros</span>
              {hasFiltros && (
                <Badge variant="secondary" className="text-xs">
                  {activeFilters.length} ativo{activeFilters.length > 1 ? 's' : ''}
                </Badge>
              )}
            </div>

            <div className="flex items-center gap-2">
              {hasFiltros && (
                <Button variant="ghost" size="sm" onClick={onLimparFiltros} className="gap-2 h-8">
                  <X className="h-4 w-4" />
                  Limpar
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                className="gap-2 h-8"
                onClick={() => setFiltrosAbertos(!filtrosAbertos)}
              >
                Mais filtros
                {filtrosAbertos ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
            <div className="space-y-2">
              <Label>Busca</Label>
              <div className="relative">
                <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  value={filtros.search}
                  onChange={(e) => onFiltroChange({ search: e.target.value })}
                  placeholder="Pedido, cliente ou documento..."
                  className="pl-9"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label>Status</Label>
              <Select
                value={filtros.status_id?.toString() || 'all'}
                onValueChange={(value) =>
                  onFiltroChange({ status_id: value === 'all' ? null : parseInt(value) })
                }
                disabled={loading}
              >
                <SelectTrigger>
                  <SelectValue placeholder={loading ? 'Carregando...' : 'Todos os status'} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todos os status</SelectItem>
                  {loading ? (
                    <div className="flex items-center justify-center py-2">
                      <Loader2 className="h-4 w-4 animate-spin" />
                    </div>
                  ) : (
                    statusList.map((status) => (
                      <SelectItem key={status.id} value={status.id.toString()}>
                        <div className="flex items-center gap-2">
                          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: status.cor_status }} />
                          {status.nome}
                        </div>
                      </SelectItem>
                    ))
                  )}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Conta Bling/ERP</Label>
              <Select
                value={filtros.bling_integration_id?.toString() || 'all'}
                onValueChange={(value) =>
                  onFiltroChange({ bling_integration_id: value === 'all' ? null : parseInt(value) })
                }
                disabled={loading}
              >
                <SelectTrigger>
                  <SelectValue placeholder={loading ? 'Carregando...' : 'Todas as contas'} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todas as contas</SelectItem>
                  {loading ? (
                    <div className="flex items-center justify-center py-2">
                      <Loader2 className="h-4 w-4 animate-spin" />
                    </div>
                  ) : (
                    blingIntegrations.map((integration) => (
                      <SelectItem key={integration.id} value={integration.id.toString()}>
                        <div className="flex items-center gap-2">
                          <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
                          <span>{integration.instance_name || integration.name || `Bling ${integration.id}`}</span>
                        </div>
                      </SelectItem>
                    ))
                  )}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Origem da venda</Label>
              <Select
                value={filtros.origem_pedido_key || 'all'}
                onValueChange={(value) =>
                  onFiltroChange({
                    origem_pedido_key: value === 'all' ? null : value,
                    canal_venda_id: null
                  })
                }
                disabled={loading}
              >
                <SelectTrigger>
                  <SelectValue placeholder={loading ? 'Carregando...' : 'Todas as origens'} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todas as origens</SelectItem>
                  {loading ? (
                    <div className="flex items-center justify-center py-2">
                      <Loader2 className="h-4 w-4 animate-spin" />
                    </div>
                  ) : (
                    origens.map((origem) => (
                      <SelectItem key={origem.key} value={origem.key}>
                        <div className="flex items-center justify-between gap-3">
                          <span>{origem.nome}</span>
                          {origem.total !== undefined && origem.total !== null && (
                            <span className="text-xs text-muted-foreground">{origem.total}</span>
                          )}
                        </div>
                      </SelectItem>
                    ))
                  )}
                </SelectContent>
              </Select>
            </div>
          </div>

          {hasFiltros && (
            <div className="flex flex-wrap gap-2">
              {activeFilters.map((filter) => (
                <Badge key={filter} variant="outline" className="bg-muted/40">
                  {filter}
                </Badge>
              ))}
            </div>
          )}
        </div>

        {filtrosAbertos && (
          <CardContent className="pt-4 space-y-4">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <DateRangeFilter
                title="Data do pedido"
                description="Quando o pedido foi registrado ou importado."
                icon={<CalendarRange className="h-4 w-4 mt-0.5 text-muted-foreground" />}
                startValue={filtros.pedido_date_start}
                endValue={filtros.pedido_date_end}
                presets={pedidoDatePresets}
                onChange={({ start, end }) =>
                  onFiltroChange({ pedido_date_start: start, pedido_date_end: end })
                }
              />

              <DateRangeFilter
                title="Prazo de envio"
                description="Filtra pelo limite de envio ou coleta."
                icon={<Truck className="h-4 w-4 mt-0.5 text-muted-foreground" />}
                startValue={filtros.delivery_start}
                endValue={filtros.delivery_end}
                presets={deliveryPresets}
                onChange={({ start, end }) =>
                  onFiltroChange({ delivery_start: start, delivery_end: end })
                }
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {[
                {
                  label: 'Demanda',
                  key: 'has_demanda',
                  options: [{ val: false, text: 'Sem Demanda' }, { val: true, text: 'Com Demanda' }]
                },
                {
                  label: 'Flex',
                  key: 'is_flex',
                  options: [{ val: false, text: 'Normal' }, { val: true, text: 'Flex' }]
                },
                {
                  label: 'Personalizados',
                  key: 'is_personalizado',
                  options: [{ val: false, text: 'Comum' }, { val: true, text: 'Personalizado' }]
                }
              ].map((f) => (
                <div key={f.key} className="space-y-2">
                  <Label>{f.label}</Label>
                  <div className="flex gap-1 p-1 bg-muted/50 rounded-lg">
                    {f.options.map((opt) => (
                      <button
                        key={String(opt.val)}
                        onClick={() => onFiltroChange({ [f.key]: filtros[f.key] === opt.val ? null : opt.val })}
                        className={`flex-1 px-3 py-1.5 text-sm rounded-md transition-all ${
                          filtros[f.key] === opt.val
                            ? 'bg-primary text-primary-foreground shadow-sm'
                            : 'hover:bg-background hover:shadow-sm text-muted-foreground'
                        }`}
                      >
                        {opt.text}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            <div className="rounded-md bg-muted/40 p-3 flex items-start gap-2 text-xs text-muted-foreground">
              <Store className="h-4 w-4 mt-0.5" />
              <span>
                Use <strong>Origem da venda</strong> para filtrar por marketplace, loja ou canal interno mapeado para o pedido.
              </span>
            </div>
          </CardContent>
        )}
      </Card>
    </>
  );
}
