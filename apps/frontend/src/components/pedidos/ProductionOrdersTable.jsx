import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { formatAppDateTime } from '@/lib/dateTime'
import { getOrderTimestamps } from '@/lib/orderTimestamps'
import MarketplaceService from '@/services/MarketplaceService'
import { ArrowUpRight, ChevronLeft, ChevronRight, Loader2 } from 'lucide-react'

function normalizeModalidade(order) {
  const raw = String(order.modalidade_logistica || '').trim().toUpperCase()
  if (raw === 'FLEX') return 'EXPRESS'
  if (raw) return raw
  if (order.is_flex) return 'EXPRESS'
  if (order.is_fulfillment) return 'FULFILLMENT'
  return 'STANDARD'
}

function buildSuggestionKey(order) {
  if (!order.marketplace_integration_id || !order.regra_logistica_integracao_id || !order.data_coleta) return null
  return `mp=${order.marketplace_integration_id}|mod=${normalizeModalidade(order)}|rule=${order.regra_logistica_integracao_id}|collect=${order.data_coleta}`
}

function getSuggestionHref(order) {
  const key = buildSuggestionKey(order)
  if (!key) return null
  return `/producao/demanda?tab=planning&suggestion=${encodeURIComponent(key)}`
}

function formatarDataHora(dataStr) {
  return formatAppDateTime(dataStr, { fallback: dataStr || '-' })
}

function StatusBadge({ statusId, statusNome, statusCor }) {
  if (statusCor) {
    return (
      <Badge style={{ backgroundColor: statusCor, color: '#fff' }}>
        {statusNome || `Status ${statusId}`}
      </Badge>
    )
  }

  return (
    <Badge variant='outline'>
      {statusNome || `Status ${statusId}`}
    </Badge>
  )
}

function getDemandaStatusColor(status) {
  const normalized = String(status || '').toUpperCase()
  const statusColors = {
    AGUARDANDO: 'bg-amber-100 text-amber-800 border-amber-300',
    EM_PRODUCAO: 'bg-blue-100 text-blue-800 border-blue-300',
    COLETA_PARCIAL: 'bg-violet-100 text-violet-800 border-violet-300',
    CONCLUIDO: 'bg-slate-100 text-slate-800 border-slate-300',
    COLETADO: 'bg-emerald-100 text-emerald-800 border-emerald-300',
  }
  return statusColors[normalized] || 'bg-gray-100 text-gray-800 border-gray-300'
}

function CanalIcon({ canalNome, marketplaceSlug, marketplaceColor, moduleIcons }) {
  const canalSlug = marketplaceSlug || (canalNome ? canalNome.toLowerCase().replace(/\s+/g, '') : '')
  const legacyIconUrls = {
    shopee: 'https://app.nistiprint.com.br/assets/img/shopee.svg',
    amazon: 'https://app.nistiprint.com.br/assets/img/amazon.svg',
    mercadolivre: 'https://app.nistiprint.com.br/assets/img/mercadolivre.svg',
    shein: 'https://app.nistiprint.com.br/assets/img/shein.svg',
    magazineluiza: 'https://app.nistiprint.com.br/assets/img/magazineluiza.svg',
    kwai: 'https://app.nistiprint.com.br/assets/img/kwai.svg',
    tiktokshop: 'https://app.nistiprint.com.br/assets/img/tiktok.svg',
    lojaintegrada: 'https://app.nistiprint.com.br/assets/img/lojaintegrada.svg',
  }

  const iconUrl =
    moduleIcons?.[canalSlug] ||
    legacyIconUrls[canalSlug] ||
    Object.entries(moduleIcons || {}).find(([slug]) => canalSlug.includes(slug))?.[1] ||
    Object.entries(legacyIconUrls).find(([slug]) => canalSlug.includes(slug))?.[1]

  const [imgError, setImgError] = useState(false)

  if (iconUrl && !imgError) {
    return (
      <Tooltip>
        <TooltipTrigger>
          <img
            src={iconUrl}
            alt={canalNome || 'Origem'}
            className='h-6 w-6 object-contain'
            onError={() => setImgError(true)}
          />
        </TooltipTrigger>
        <TooltipContent>{canalNome || 'Origem'}</TooltipContent>
      </Tooltip>
    )
  }

  return (
    <Badge variant='outline' style={marketplaceColor ? { backgroundColor: marketplaceColor, color: '#fff' } : undefined}>
      {canalNome || 'Origem indefinida'}
    </Badge>
  )
}

export default function ProductionOrdersTable({
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
}) {
  const [moduleIcons, setModuleIcons] = useState({})

  useEffect(() => {
    async function fetchIcons() {
      try {
        const modules = await MarketplaceService.getAvailableModules()
        const icons = {}
        modules.forEach((module) => {
          icons[module.slug] = module.icon_url
        })
        setModuleIcons(icons)
      } catch (error) {
        console.error(error)
      }
    }
    fetchIcons()
  }, [])

  const totalPages = Math.ceil(total / limit)
  const todosSelecionados = pedidos.length > 0 && pedidosSelecionados.length === pedidos.length

  if (loading) {
    return (
      <Card>
        <CardContent className='flex flex-col items-center justify-center py-12'>
          <Loader2 className='mb-4 h-8 w-8 animate-spin text-primary' />
          <p className='text-muted-foreground'>Carregando pedidos...</p>
        </CardContent>
      </Card>
    )
  }

  if (pedidos.length === 0) {
    return (
      <Card>
        <CardContent className='py-12 text-center text-muted-foreground'>
          Nenhum pedido encontrado
        </CardContent>
      </Card>
    )
  }

  return (
    <div className='space-y-4'>
      <Card>
        <CardContent className='p-0'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className='w-[50px]'>
                  <Checkbox checked={todosSelecionados} onCheckedChange={onSelecionarTodos} />
                </TableHead>
                <TableHead>Origem</TableHead>
                <TableHead>Pagamento</TableHead>
                <TableHead>Enviar ate</TableHead>
                <TableHead>Lote previsto</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Demanda</TableHead>
                <TableHead className='text-right'>Acao</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pedidos.map((pedido) => {
                const timestamps = getOrderTimestamps(pedido)
                const suggestionHref = getSuggestionHref(pedido)
                const demandaHref = pedido.demanda_id
                  ? `/producao/demanda/${pedido.demanda_id}/dashboard`
                  : suggestionHref

                return (
                  <TableRow key={pedido.id}>
                    <TableCell>
                      <Checkbox
                        checked={pedidosSelecionados.includes(pedido.id)}
                        onCheckedChange={() => onSelecionarPedido(pedido.id)}
                      />
                    </TableCell>
                    <TableCell>
                      <CanalIcon
                        canalNome={pedido.canal_venda_nome}
                        marketplaceSlug={pedido.marketplace_slug}
                        marketplaceColor={pedido.marketplace_color}
                        moduleIcons={moduleIcons}
                      />
                    </TableCell>
                    <TableCell>
                      {timestamps.pagamento ? formatarDataHora(timestamps.pagamento) : 'Pagamento nao informado'}
                    </TableCell>
                    <TableCell>{formatarDataHora(timestamps.limite)}</TableCell>
                    <TableCell>
                      {pedido.data_coleta ? (
                        <div className='space-y-1'>
                          <div className='font-medium text-slate-900'>{formatarDataHora(pedido.data_coleta)}</div>
                          <div className='text-xs text-slate-500'>
                            {normalizeModalidade(pedido) === 'EXPRESS' ? 'Flex' : 'Normal'}
                          </div>
                        </div>
                      ) : (
                        <Badge variant='outline' className='border-amber-200 bg-amber-50 text-amber-800'>
                          Sem janela
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <StatusBadge
                        statusId={pedido.situacao_pedido_id}
                        statusNome={pedido.status?.nome}
                        statusCor={pedido.status?.cor}
                      />
                    </TableCell>
                    <TableCell>
                      {pedido.demanda_id ? (
                        <Button variant='ghost' size='sm' asChild>
                          <Link to={demandaHref}>
                            <ArrowUpRight className='mr-2 h-3 w-3' />
                            <Badge variant='outline' className={getDemandaStatusColor(pedido.demanda_status)}>
                              {pedido.demanda_status || 'Demanda'}
                            </Badge>
                          </Link>
                        </Button>
                      ) : suggestionHref ? (
                        <Button variant='ghost' size='sm' asChild>
                          <Link to={suggestionHref}>
                            <ArrowUpRight className='mr-2 h-3 w-3' />
                            Ver lote
                          </Link>
                        </Button>
                      ) : (
                        <span className='text-xs text-muted-foreground'>Sem lote</span>
                      )}
                    </TableCell>
                    <TableCell className='text-right'>
                      <Button variant='ghost' size='sm' asChild>
                        <Link to={`/vendas/pedidos/${pedido.id}`}>Ver</Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <div className='flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between'>
        <div className='text-sm text-muted-foreground'>
          Mostrando <strong>{pedidos.length}</strong> de <strong>{total}</strong> pedidos
          {totalPages > 0 && ` (Pagina ${page} de ${totalPages})`}
        </div>

        <div className='flex items-center gap-4'>
          <div className='flex items-center gap-2'>
            <Label className='text-sm'>Por pagina:</Label>
            <Select
              value={limit.toString()}
              onValueChange={(value) => {
                onLimitChange(parseInt(value, 10))
                onPageChange(1)
              }}
            >
              <SelectTrigger className='w-[80px]'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value='25'>25</SelectItem>
                <SelectItem value='50'>50</SelectItem>
                <SelectItem value='100'>100</SelectItem>
                <SelectItem value='200'>200</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className='flex items-center gap-2'>
            <Button
              variant='outline'
              size='sm'
              onClick={() => onPageChange(page - 1)}
              disabled={page === 1}
            >
              <ChevronLeft className='h-4 w-4' />
            </Button>
            <span className='text-sm font-medium'>
              {page} / {totalPages || 1}
            </span>
            <Button
              variant='outline'
              size='sm'
              onClick={() => onPageChange(page + 1)}
              disabled={page >= totalPages}
            >
              <ChevronRight className='h-4 w-4' />
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
