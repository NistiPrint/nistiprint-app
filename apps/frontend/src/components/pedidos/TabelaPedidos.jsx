import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { ChevronLeft, ChevronRight, Loader2, Zap } from 'lucide-react';
import { Link } from 'react-router-dom';

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
  canaisProximosIds = [],  // IDs dos canais com coleta próxima para highlight
}) {
  const totalPages = Math.ceil(total / limit);
  const todosSelecionados = pedidos.length > 0 && pedidosSelecionados.length === pedidos.length;

  // Formatador de data
  const formatarData = (dataStr) => {
    if (!dataStr) return '-';
    const date = new Date(dataStr);
    if (isNaN(date.getTime())) return '-';
    return date.toLocaleDateString('pt-BR');
  };

  // Formatador de data/hora para "Enviar Até"
  const formatarDataHora = (dataStr) => {
    if (!dataStr) return '-';
    try {
      const date = new Date(dataStr);
      if (isNaN(date.getTime())) return '-';
      return date.toLocaleDateString('pt-BR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return '-';
    }
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
                <TableHead className="w-[50px]">Flex</TableHead>
                <TableHead>Pedido</TableHead>
                <TableHead>Enviar Até</TableHead>
                <TableHead>Data</TableHead>
                <TableHead>Cliente</TableHead>
                <TableHead>Canal</TableHead>
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
                  ? 'bg-orange-50/50 hover:bg-orange-50' 
                  : isCanalProximo 
                    ? 'bg-blue-50/30 hover:bg-blue-50' 
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
                    {pedido.is_flex && (
                      <Tooltip>
                        <TooltipTrigger>
                          <Badge variant="secondary" className="bg-orange-500 text-white h-6 w-6 p-0 flex items-center justify-center">
                            <Zap className="h-3 w-3" />
                          </Badge>
                        </TooltipTrigger>
                        <TooltipContent>
                          <span>Pedido Flex</span>
                        </TooltipContent>
                      </Tooltip>
                    )}
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
                    <CanalIcon canalNome={pedido.canal_venda_nome} />
                  </TableCell>
                  <TableCell>
                    <StatusBadge
                      statusId={pedido.situacao_pedido_id}
                      statusNome={pedido.status?.nome}
                      statusCor={pedido.status?.cor}
                    />
                  </TableCell>
                  <TableCell className="text-center">
                    {pedido.tem_demanda ? (
                      <Badge className="bg-green-600">
                        ✅ Gerada
                      </Badge>
                    ) : (
                      <Badge variant="secondary">
                        ❌ Pendente
                      </Badge>
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

// Componente de Ícone do Canal com fallback para nome
function CanalIcon({ canalNome }) {
  const canalSlug = canalNome?.toLowerCase().replace(/\s+/g, '') || '';

  // URLs dos ícones (mesmos usados em IntegracaoCard.jsx)
  const iconUrls = {
    shopee: 'https://app.nistiprint.com.br/assets/img/shopee.svg',
    amazon: 'https://app.nistiprint.com.br/assets/img/amazon.svg',
    mercadolivre: 'https://app.nistiprint.com.br/assets/img/mercadolivre.svg',
    shein: 'https://app.nistiprint.com.br/assets/img/shein.svg',
  };

  // Cores de fallback
  const colorMap = {
    shopee: 'bg-orange-500',
    amazon: 'bg-blue-600',
    mercadolivre: 'bg-blue-400',
    shein: 'bg-black',
  };

  // Verificar se há ícone disponível para este canal
  const iconUrl = Object.entries(iconUrls).find(([slug]) => 
    canalSlug.includes(slug)
  )?.[1];

  if (iconUrl) {
    return (
      <Tooltip>
        <TooltipTrigger>
          <img
            src={iconUrl}
            alt={canalNome || 'Canal'}
            className="w-6 h-6 object-contain"
          />
        </TooltipTrigger>
        <TooltipContent>
          <span>{canalNome || 'Canal'}</span>
        </TooltipContent>
      </Tooltip>
    );
  }

  // Fallback: exibir nome do canal
  return (
    <Tooltip>
      <TooltipTrigger>
        <Badge variant="outline" className={`text-xs ${!canalNome ? 'border-red-300 text-red-500' : ''}`}>
          {canalNome || 'Unknown'}
        </Badge>
      </TooltipTrigger>
      {!canalNome && (
        <TooltipContent>
          <p>Canal não identificado. Verifique o mapeamento do "ID da Loja" em Configurações {'>'} Canais.</p>
        </TooltipContent>
      )}
    </Tooltip>
  );
}
