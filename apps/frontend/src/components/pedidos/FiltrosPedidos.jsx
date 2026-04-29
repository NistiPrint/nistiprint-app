import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { ChevronDown, ChevronUp, Filter, Loader2, Sparkles, X, Zap } from 'lucide-react';
import { useEffect, useState } from 'react';

import FiltrosContextuais from './FiltrosContextuais';

export default function FiltrosPedidos({ filtros, onFiltroChange, onLimparFiltros }) {
  const [canais, setCanais] = useState([]);
  const [statusList, setStatusList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filtrosAbertos, setFiltrosAbertos] = useState(false);

  // Buscar marketplaces (nova arquitetura) e status ao montar o componente
  useEffect(() => {
    const carregarDados = async () => {
      try {
        const [marketplacesRes, statusRes] = await Promise.all([
          fetch('/api/v2/pedidos/marketplaces?ativos=true'),
          fetch('/api/v2/pedidos/status-opcoes')
        ]);
        
        const marketplacesData = await marketplacesRes.json();
        const statusData = await statusRes.json();
        
        if (marketplacesData.success) {
          setCanais(marketplacesData.data.marketplaces || []);
        }
        if (statusData.success) {
          setStatusList(statusData.data.status || []);
        }
      } catch (error) {
        console.error('Erro ao carregar filtros:', error);
      } finally {
        setLoading(false);
      }
    };
    
    carregarDados();
  }, []);

  const hasFiltros =
    filtros.search ||
    filtros.status_id ||
    filtros.canal_venda_id ||
    filtros.has_demanda !== null ||
    filtros.delivery_start ||
    filtros.delivery_end ||
    filtros.pedido_date_start ||
    filtros.pedido_date_end ||
    filtros.is_flex ||
    filtros.is_personalizado;

  // Handler para filtros contextuais
  const handleFiltroContextual = (filtroContextual) => {
    const novosFiltros = {};
    
    switch (filtroContextual.tipo) {
      case 'canal':
        novosFiltros.canal_venda_id = filtroContextual.canal_venda_id;
        break;
      case 'flex':
        novosFiltros.canal_venda_id = filtroContextual.canal_venda_id;
        novosFiltros.is_flex = true;
        break;
      case 'sem_demanda':
        novosFiltros.canal_venda_id = filtroContextual.canal_venda_id;
        novosFiltros.has_demanda = false;
        break;
    }
    
    onFiltroChange(novosFiltros);
  };

  return (
    <>
      {/* Filtros Contextuais (baseados em horário de coleta) */}
      <FiltrosContextuais onFiltroContextual={handleFiltroContextual} />

      {/* Filtros Manuais (colapsável) */}
      <Card className="mb-4">
        <div className="flex items-center justify-between p-4 border-b cursor-pointer" onClick={() => setFiltrosAbertos(!filtrosAbertos)}>
          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <span className="font-medium text-sm">Filtros Manuais</span>
            {hasFiltros && (
              <Badge variant="secondary" className="text-xs">
                Ativos
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            {hasFiltros && (
              <Button
                variant="ghost"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onLimparFiltros();
                }}
                className="gap-2 h-8"
              >
                <X className="h-4 w-4" />
                Limpar
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              className="h-8 w-8 p-0"
              onClick={(e) => {
                e.stopPropagation();
                setFiltrosAbertos(!filtrosAbertos);
              }}
            >
              {filtrosAbertos ? (
                <ChevronUp className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>
        
        {filtrosAbertos && (
          <CardContent className="pt-6">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {/* Busca */}
          <div className="space-y-2">
            <Label>Busca</Label>
            <div className="relative">
              <Input
                value={filtros.search}
                onChange={(e) => onFiltroChange({ search: e.target.value })}
                placeholder="Pedido, cliente, SKU..."
                className="pl-9"
              />
            </div>
          </div>

          {/* Status */}
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
                        <div 
                          className="w-3 h-3 rounded-full" 
                          style={{ backgroundColor: status.cor_status }}
                        />
                        {status.nome}
                      </div>
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
          </div>

          {/* Canal */}
          <div className="space-y-2">
            <Label>Canal de Venda</Label>
            <Select
              value={filtros.canal_venda_id?.toString() || 'all'}
              onValueChange={(value) =>
                onFiltroChange({ canal_venda_id: value === 'all' ? null : parseInt(value) })
              }
              disabled={loading}
            >
              <SelectTrigger>
                <SelectValue placeholder={loading ? 'Carregando...' : 'Todos os canais'} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Todos os canais</SelectItem>
                {loading ? (
                  <div className="flex items-center justify-center py-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                  </div>
                ) : (
                  canais.map((canal) => (
                    <SelectItem key={canal.id} value={canal.id.toString()}>
                      {canal.nome}
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
          </div>

          {/* Demanda */}
          <div className="space-y-2">
            <Label>Demanda</Label>
            <Select
              value={
                filtros.has_demanda === null ? 'all' :
                filtros.has_demanda ? 'com' : 'sem'
              }
              onValueChange={(value) =>
                onFiltroChange({
                  has_demanda: value === 'all' ? null : value === 'com'
                })
              }
            >
              <SelectTrigger>
                <SelectValue placeholder="Todos" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Todos</SelectItem>
                <SelectItem value="com">Com demanda</SelectItem>
                <SelectItem value="sem">Sem demanda</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Período de Envio - De */}
          <div className="space-y-2">
            <Label>Período de Envio - De</Label>
            <Input
              type="date"
              value={filtros.delivery_start}
              onChange={(e) => onFiltroChange({ delivery_start: e.target.value })}
            />
          </div>

          {/* Período de Envio - Até */}
          <div className="space-y-2">
            <Label>Período de Envio - Até</Label>
            <Input
              type="date"
              value={filtros.delivery_end}
              onChange={(e) => onFiltroChange({ delivery_end: e.target.value })}
            />
          </div>

          {/* Data do Pedido - De */}
          <div className="space-y-2">
            <Label>Data do Pedido - De</Label>
            <Input
              type="date"
              value={filtros.pedido_date_start}
              onChange={(e) => onFiltroChange({ pedido_date_start: e.target.value })}
            />
          </div>

          {/* Data do Pedido - Até */}
          <div className="space-y-2">
            <Label>Data do Pedido - Até</Label>
            <Input
              type="date"
              value={filtros.pedido_date_end}
              onChange={(e) => onFiltroChange({ pedido_date_end: e.target.value })}
            />
          </div>

          {/* Filtro Flex (Entrega Rápida) */}
          <div className="space-y-2 flex items-end">
            <div className="flex items-center space-x-3 pb-2">
              <Switch
                id="filtro-flex"
                checked={filtros.is_flex === true}
                onCheckedChange={(checked) =>
                  onFiltroChange({ is_flex: checked ? true : null })
                }
              />
              <Label htmlFor="filtro-flex" className="flex items-center gap-2 cursor-pointer">
                <Zap className="h-4 w-4 text-orange-500" />
                <div>
                  <div className="font-medium">Apenas Entrega Rápida</div>
                  <div className="text-xs text-muted-foreground">Pedidos Flex (prioritários)</div>
                </div>
              </Label>
            </div>
          </div>

          {/* Filtro Personalizado */}
          <div className="space-y-2 flex items-end">
            <div className="flex items-center space-x-3 pb-2">
              <Switch
                id="filtro-personalizado"
                checked={filtros.is_personalizado === true}
                onCheckedChange={(checked) =>
                  onFiltroChange({ is_personalizado: checked ? true : null })
                }
              />
              <Label htmlFor="filtro-personalizado" className="flex items-center gap-2 cursor-pointer">
                <Sparkles className="h-4 w-4 text-purple-500" />
                <div>
                  <div className="font-medium">Apenas Personalizados</div>
                  <div className="text-xs text-muted-foreground">Pedidos com personalização</div>
                </div>
              </Label>
            </div>
          </div>
        </div>

        {/* Botão Limpar Filtros */}
        {hasFiltros && (
          <div className="flex justify-end mt-4 pt-4 border-t">
            <Button
              variant="ghost"
              size="sm"
              onClick={onLimparFiltros}
              className="gap-2"
            >
              <X className="h-4 w-4" />
              Limpar Filtros
            </Button>
          </div>
        )}
          </CardContent>
        )}
      </Card>
    </>
  );
}
