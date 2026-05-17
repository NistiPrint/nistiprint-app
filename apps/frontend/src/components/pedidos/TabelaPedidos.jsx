import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { ArrowUpRight, ChevronLeft, ChevronRight, Loader2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { formatAppDate, formatAppDateTime } from '@/lib/dateTime';
import { useEffect, useState } from 'react';
import MarketplaceService from '@/services/MarketplaceService';

export default function TabelaPedidos({
  pedidos,
  loading,
  pedidosSelecionados,
  onSelecionarPedido,
  onSelecionarTodos,
  page,
  limit,
  total,
  onPageChange,
  onLimitChange,
  canaisProximosIds = [],
}) {
  const [moduleIcons, setModuleIcons] = useState({});

  useEffect(() => {
    const fetchIcons = async () => {
      try {
        const modules = await MarketplaceService.getAvailableModules();
        const icons = {};
        modules.forEach(m => {
          icons[m.slug] = m.icon_url;
        });
        setModuleIcons(icons);
      } catch (error) {
        console.error('Erro ao carregar ícones:', error);
      }
    };
    fetchIcons();
  }, []);
  const totalPages = Math.ceil(total / limit);
  const todosSelecionados = pedidos.length > 0 && pedidosSelecionados.length === pedidos.length;

  // Formatador de data
  const formatarData = (dataStr) => {
    return formatAppDate(dataStr);
  };

  // Formatador de data/hora para "Enviar Até"
  const formatarDataHora = (dataStr) => {
    return formatAppDateTime(dataStr);
  };

  if (loading) {
    return (
      <Card>
        <CardContent className="py-12 flex flex-col items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary mb-4" />
          <p className="text-muted-foreground">Carregando pedidos...</p>
        </CardContent>
      </Card>
    );
  }

  if (pedidos.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 flex flex-col items-center justify-center">
          <p className="text-muted-foreground">Nenhum pedido encontrado</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* Tabela */}
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[50px]">
                  <Checkbox
                    checked={todosSelecionados}
                    onCheckedChange={onSelecionarTodos}
                  />
                </TableHead>
                <TableHead className="w-[80px]">
                  <span className="text-xs">Flags</span>
                </TableHead>
                <TableHead>Pedido</TableHead>
                <TableHead>Enviar Até</TableHead>
                <TableHead>Data</TableHead>
                <TableHead>Cliente</TableHead>
                <TableHead>Origem</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-center">Demanda</TableHead>
                <TableHead className="text-right">Ações</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pedidos.map((pedido) => {
                // Verificar se pedido é de canal com coleta próxima
                const isCanalProximo = canaisProximosIds.length > 0 && 
                  pedido.canal_venda_id && 
                  canaisProximosIds.includes(pedido.canal_venda_id);
                
                // Determinar classe da linha
                const rowClass = pedido.is_flex
                  ? 'bg-orange-50/30 hover:bg-orange-50'
                  : pedido.is_personalizado
                    ? 'bg-purple-50/20 hover:bg-purple-50'
                    : isCanalProximo
                      ? 'bg-blue-50/20 hover:bg-blue-50'
                      : '';

                return (
                <TableRow key={pedido.id} className={rowClass}>
                  <TableCell>
                    <Checkbox
                      checked={pedidosSelecionados.includes(pedido.id)}
                      onCheckedChange={() => onSelecionarPedido(pedido.id)}
                    />
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      {/* Flex indicator - subtle dot */}
                      {pedido.is_flex && (
                        <Tooltip>
                          <TooltipTrigger>
                            <div className="h-2 w-2 rounded-full bg-orange-400" />
                          </TooltipTrigger>
                          <TooltipContent>
                            <span>Entrega Rápida (Flex)</span>
                          </TooltipContent>
                        </Tooltip>
                      )}
                      {/* Personalizado indicator - subtle dot */}
                      {pedido.is_personalizado && (
                        <Tooltip>
                          <TooltipTrigger>
                            <div className="h-2 w-2 rounded-full bg-purple-400" />
                          </TooltipTrigger>
                          <TooltipContent>
                            <span>Pedido personalizado</span>
                          </TooltipContent>
                        </Tooltip>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-col gap-1">
                      {isCanalProximo && (
                        <Badge variant="outline" className="w-fit bg-blue-100 text-blue-700 border-blue-300 text-xs">
                          🕐 Coleta Próxima
                        </Badge>
                      )}
                      <span className="font-medium">#{pedido.numero_pedido}</span>
                      {pedido.codigo_pedido_externo && (
                        <span className="text-xs text-muted-foreground font-mono">
                          {pedido.codigo_pedido_externo}
                        </span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className={pedido.is_flex ? 'font-semibold text-orange-700' : ''}>
                      {formatarDataHora(pedido.data_limite_envio || pedido.enviar_ate_formatado)}
                    </div>
                  </TableCell>
                  <TableCell>{formatarData(pedido.data_venda)}</TableCell>
                  <TableCell>
                    <div className="flex flex-col">
                      <span className="font-medium">{pedido.cliente_nome || 'N/A'}</span>
                      {pedido.cliente_documento && (
                        <span className="text-xs text-muted-foreground">
                          {pedido.cliente_documento}
                        </span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <CanalIcon 
                      canalNome={pedido.canal_venda_nome}
                      marketplaceSlug={pedido.marketplace_slug}
                      marketplaceColor={pedido.marketplace_color}
                    />
                  </TableCell>
                  <TableCell>
                    <StatusBadge
                      statusId={pedido.situacao_pedido_id}
                      statusNome={pedido.status?.nome}
                      statusCor={pedido.status?.cor}
                    />
                  </TableCell>
                  <TableCell className="text-center">
                    {pedido.demanda_id ? (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 px-2 text-xs text-green-700 hover:text-green-800 hover:bg-green-50 gap-1"
                            asChild
                          >
                            <Link to={`/producao/demanda/${pedido.demanda_id}/dashboard`}>
                              <ArrowUpRight className="h-3 w-3" />
                              {pedido.demanda_status && (
                                <Badge variant="outline" className={`text-xs px-1.5 py-0.5 ${getDemandaStatusColor(pedido.demanda_status)}`}>
                                  {pedido.demanda_status}
                                </Badge>
                              )}
                              {pedido.total_demandas > 1 && (
                                <span className="ml-1 text-xs text-muted-foreground">+{pedido.total_demandas - 1}</span>
                              )}
                            </Link>
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>
                          <span>
                            Ir para demanda {pedido.demanda_numero ? `#${pedido.demanda_numero}` : ''}
                            {pedido.total_demandas > 1 && ` (+${pedido.total_demandas - 1} outras)`}
                          </span>
                        </TooltipContent>
                      </Tooltip>
                    ) : pedido.tem_demanda ? (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 px-2 text-xs text-amber-600 hover:text-amber-700 hover:bg-amber-50 gap-1"
                            asChild
                          >
                            <Link to={`/producao/demanda/rascunhos?pedido=${pedido.numero_pedido}`}>
                              <ArrowUpRight className="h-3 w-3" />
                              <Badge variant="outline" className={`text-xs px-1.5 py-0.5 ${getDemandaStatusColor(pedido.demanda_status || 'Rascunho')}`}>
                                {pedido.demanda_status || 'Rascunho'}
                              </Badge>
                              {pedido.total_demandas > 1 && (
                                <span className="ml-1 text-xs text-muted-foreground">+{pedido.total_demandas - 1}</span>
                              )}
                            </Link>
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>
                          <span>
                            Ver rascunhos vinculados
                            {pedido.total_demandas > 1 && ` (${pedido.total_demandas} demandas)`}
                          </span>
                        </TooltipContent>
                      </Tooltip>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      asChild
                    >
                      <Link to={`/pedidos/${pedido.id}`}>
                        Ver
                      </Link>
                    </Button>
                  </TableCell>
                </TableRow>
              );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Paginação */}
      <div className="flex flex-col sm:flex-row justify-between items-center gap-4">
        <div className="text-sm text-muted-foreground">
          Mostrando <strong>{pedidos.length}</strong> de <strong>{total}</strong> pedidos
          {totalPages > 0 && ` (Página ${page} de ${totalPages})`}
        </div>
        
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Label className="text-sm">Por página:</Label>
            <Select
              value={limit.toString()}
              onValueChange={(value) => {
                onLimitChange(parseInt(value));
                onPageChange(1);
              }}
            >
              <SelectTrigger className="w-[80px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="25">25</SelectItem>
                <SelectItem value="50">50</SelectItem>
                <SelectItem value="100">100</SelectItem>
                <SelectItem value="200">200</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => onPageChange(page - 1)}
              disabled={page === 1}
              className="gap-1"
            >
              <ChevronLeft className="h-4 w-4" />
              <span className="hidden sm:inline">Anterior</span>
            </Button>
            
            <div className="flex items-center gap-1">
              <span className="text-sm font-medium">
                {page} / {totalPages || 1}
              </span>
            </div>
            
            <Button
              variant="outline"
              size="sm"
              onClick={() => onPageChange(page + 1)}
              disabled={page >= totalPages}
              className="gap-1"
            >
              <span className="hidden sm:inline">Próxima</span>
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// Componente de Badge de Status com cores dinâmicas
function StatusBadge({ statusId, statusNome, statusCor }) {
  // Mapeamento fallback para IDs conhecidos (caso a API não retorne cor)
  const statusMap = {
    1: { label: 'Em Aberto', color: 'bg-yellow-100 text-yellow-800' },
    2: { label: 'Em Andamento', color: 'bg-blue-100 text-blue-800' },
    3: { label: 'Produzido', color: 'bg-purple-100 text-purple-800' },
    4: { label: 'Pronto p/ Envio', color: 'bg-cyan-100 text-cyan-800' },
    5: { label: 'Enviado', color: 'bg-green-100 text-green-800' },
    6: { label: 'Entregue', color: 'bg-emerald-100 text-emerald-800' },
    7: { label: 'Cancelado', color: 'bg-red-100 text-red-800' },
  };

  // Se tiver cor dinâmica da API, usa inline style
  if (statusCor) {
    return (
      <Badge style={{ backgroundColor: statusCor, color: '#fff' }}>
        {statusNome || `Status ${statusId}`}
      </Badge>
    );
  }

  // Fallback para mapeamento por ID
  const status = statusMap[statusId] || { label: statusNome || `Status ${statusId}`, color: 'bg-gray-100 text-gray-800' };

  return (
    <Badge className={status.color}>
      {status.label}
    </Badge>
  );
}

// Função para obter cor baseada no status da demanda
function getDemandaStatusColor(status) {
  const statusColors = {
    'Rascunho': 'bg-amber-100 text-amber-800 border-amber-300',
    'RASCUNHO': 'bg-amber-100 text-amber-800 border-amber-300',
    'Ativa': 'bg-green-100 text-green-800 border-green-300',
    'ATIVA': 'bg-green-100 text-green-800 border-green-300',
    'Em Andamento': 'bg-blue-100 text-blue-800 border-blue-300',
    'EM_ANDAMENTO': 'bg-blue-100 text-blue-800 border-blue-300',
    'Concluída': 'bg-purple-100 text-purple-800 border-purple-300',
    'CONCLUIDA': 'bg-purple-100 text-purple-800 border-purple-300',
    'Cancelada': 'bg-red-100 text-red-800 border-red-300',
    'CANCELADA': 'bg-red-100 text-red-800 border-red-300',
    'Pausada': 'bg-gray-100 text-gray-800 border-gray-300',
    'PAUSADA': 'bg-gray-100 text-gray-800 border-gray-300',
  };
  
  return statusColors[status] || 'bg-gray-100 text-gray-800 border-gray-300';
}

// Componente de Ícone do Canal com fallback para nome
function CanalIcon({ canalNome, marketplaceSlug, marketplaceColor, moduleIcons }) {
  // Priorizar marketplace_slug se disponível (nova arquitetura), tratando canalNome como opcional
  const canalSlug = marketplaceSlug || (canalNome ? canalNome.toLowerCase().replace(/\s+/g, '') : '');

  // URLs fixas para ícones legados
  const legacyIconUrls = {
    shopee: 'https://app.nistiprint.com.br/assets/img/shopee.svg',
    amazon: 'https://app.nistiprint.com.br/assets/img/amazon.svg',
    mercadolivre: 'https://app.nistiprint.com.br/assets/img/mercadolivre.svg',
    shein: 'https://app.nistiprint.com.br/assets/img/shein.svg',
    magazineluiza: 'https://app.nistiprint.com.br/assets/img/magazineluiza.svg',
    kwai: 'https://app.nistiprint.com.br/assets/img/kwai.svg',
    tiktokshop: 'https://app.nistiprint.com.br/assets/img/tiktok.svg',
    lojaintegrada: 'https://app.nistiprint.com.br/assets/img/lojaintegrada.svg',
  };

  // Buscar ícone no mapeamento dinâmico ou no legado
  const iconUrl = moduleIcons?.[canalSlug] || 
                  legacyIconUrls[canalSlug] || 
                  Object.entries(moduleIcons || {}).find(([slug]) => canalSlug.includes(slug))?.[1];

  const [imgError, setImgError] = useState(false);

  if (iconUrl && !imgError) {
    return (
      <Tooltip>
        <TooltipTrigger>
          <img
            src={iconUrl}
            alt={canalNome || 'Origem'}
            className="w-6 h-6 object-contain"
            onError={() => setImgError(true)}
          />
        </TooltipTrigger>
        <TooltipContent>
          <span>{canalNome || 'Origem'}</span>
        </TooltipContent>
      </Tooltip>
    );
  }

  // Fallback: exibir nome do canal com cor do marketplace se disponível
  const badgeColor = marketplaceColor ? { 
    backgroundColor: marketplaceColor, 
    color: '#fff' 
  } : undefined;

  return (
    <Tooltip>
      <TooltipTrigger>
        <Badge 
          variant="outline" 
          className={`text-xs ${!canalNome ? 'border-red-300 text-red-500' : ''}`}
          style={badgeColor}
        >
          {canalNome || 'Origem indefinida'}
        </Badge>
      </TooltipTrigger>
      {!canalNome && (
        <TooltipContent>
          <p>Origem nao identificada. Verifique o mapeamento do "ID da Loja" nas configuracoes de integracao.</p>
        </TooltipContent>
      )}
    </Tooltip>
  );
}

