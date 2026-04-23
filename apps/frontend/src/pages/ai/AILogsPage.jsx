import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { personalizadosService } from '@/services/personalizadosService'
import { format } from 'date-fns'
import { ptBR } from 'date-fns/locale'
import { Loader2, Search, RefreshCw, ChevronDown, ChevronRight, AlertTriangle, CheckCircle, XCircle, Terminal, FileText, Brain } from 'lucide-react'
import { toast } from 'sonner'

const STATUS_CONFIG = {
  success: { label: 'Sucesso', icon: CheckCircle, color: 'bg-green-100 text-green-800 border-green-300' },
  error: { label: 'Erro', icon: XCircle, color: 'bg-red-100 text-red-800 border-red-300' },
  db_error: { label: 'Erro DB', icon: AlertTriangle, color: 'bg-orange-100 text-orange-800 border-orange-300' },
  no_response: { label: 'Sem Resposta', icon: AlertTriangle, color: 'bg-yellow-100 text-yellow-800 border-yellow-300' },
}

export function AILogsPage() {
  const [logs, setLogs] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [expandedLogs, setExpandedLogs] = useState(new Set())
  const [page, setPage] = useState(1)
  const limit = 50

  // Filtros
  const [filterOrderSn, setFilterOrderSn] = useState('')
  const [filterStatus, setFilterStatus] = useState('all')

  useEffect(() => {
    loadLogs()
  }, [page])

  const loadLogs = async () => {
    setLoading(true)
    try {
      const params = { limit, offset: (page - 1) * limit }
      if (filterOrderSn) params.order_sn = filterOrderSn
      if (filterStatus !== 'all') params.status = filterStatus

      const data = await personalizadosService.getAllLogs(params)
      if (data.success) {
        setLogs(data.data.logs || [])
        setTotal(data.data.total || 0)
      } else {
        toast.error('Erro ao carregar logs')
      }
    } catch (err) {
      toast.error(`Erro: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  const handleSearch = () => {
    setPage(1)
    loadLogs()
  }

  const toggleExpand = (logId) => {
    setExpandedLogs(prev => {
      const next = new Set(prev)
      if (next.has(logId)) next.delete(logId)
      else next.add(logId)
      return next
    })
  }

  const CollapsibleSection = ({ icon: Icon, title, content, defaultOpen = false }) => {
    const sectionKey = `${title}-${Math.random()}`
    const [open, setOpen] = useState(defaultOpen)

    return (
      <div className="border rounded overflow-hidden">
        <button
          onClick={() => setOpen(!open)}
          className="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 hover:bg-gray-100 transition-colors text-sm font-medium"
        >
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          <Icon className="h-4 w-4 text-muted-foreground" />
          {title}
        </button>
        {open && content && (
          <pre className="text-xs bg-white p-3 overflow-x-auto max-h-96 whitespace-pre-wrap border-t">
            {typeof content === 'string' ? content : JSON.stringify(content, null, 2)}
          </pre>
        )}
      </div>
    )
  }

  const totalPages = Math.ceil(total / limit)

  return (
    <div className="container mx-auto py-6 px-4 max-w-7xl">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Logs de Execução IA</h1>
        <Button variant="outline" size="sm" onClick={() => { setPage(1); loadLogs(); }}>
          <RefreshCw className="h-4 w-4 mr-2" /> Atualizar
        </Button>
      </div>

      {/* Filtros */}
      <Card className="mb-6">
        <CardContent className="pt-4">
          <div className="flex gap-3 items-end">
            <div className="flex-1">
              <label className="text-sm font-medium mb-1 block">Pedido (order_sn)</label>
              <Input
                value={filterOrderSn}
                onChange={(e) => setFilterOrderSn(e.target.value)}
                placeholder="Ex: 260101ABCDEF"
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              />
            </div>
            <div className="w-48">
              <label className="text-sm font-medium mb-1 block">Status</label>
              <Select value={filterStatus} onValueChange={setFilterStatus}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todos</SelectItem>
                  {Object.entries(STATUS_CONFIG).map(([key, cfg]) => (
                    <SelectItem key={key} value={key}>{cfg.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button onClick={handleSearch} disabled={loading}>
              <Search className="h-4 w-4 mr-2" /> Buscar
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Tabela de Logs */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-normal text-muted-foreground">
            {total} log{total !== 1 ? 's' : ''} encontrado{total !== 1 ? 's' : ''}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : logs.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              Nenhum log encontrado
            </div>
          ) : (
            <div className="divide-y">
              {logs.map((log) => {
                const statusCfg = STATUS_CONFIG[log.status] || { label: log.status, icon: AlertTriangle, color: 'bg-gray-100 text-gray-800 border-gray-300' }
                const StatusIcon = statusCfg.icon
                const isExpanded = expandedLogs.has(log.id)

                return (
                  <div key={log.id} className="hover:bg-gray-50/50 transition-colors">
                    <div
                      className="flex items-center gap-4 px-4 py-3 cursor-pointer"
                      onClick={() => toggleExpand(log.id)}
                    >
                      {/* Expand toggle */}
                      <button className="text-muted-foreground hover:text-foreground">
                        {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      </button>

                      {/* Status */}
                      <Badge variant="outline" className={statusCfg.color}>
                        <StatusIcon className="h-3 w-3 mr-1" />
                        {statusCfg.label}
                      </Badge>

                      {/* Order SN */}
                      <code className="text-sm font-mono bg-gray-100 px-2 py-0.5 rounded">
                        {log.order_sn}
                      </code>

                      {/* Data */}
                      <span className="text-sm text-muted-foreground ml-auto">
                        {log.executed_at ? format(new Date(log.executed_at), 'dd/MM/yyyy HH:mm:ss', { locale: ptBR }) : '-'}
                      </span>
                    </div>

                    {/* Detalhes expandidos */}
                    {isExpanded && (
                      <div className="px-4 pb-4 space-y-3">
                        {log.error_message && (
                          <div className="bg-red-50 border border-red-200 rounded p-3">
                            <p className="text-sm font-medium text-red-800">Erro:</p>
                            <pre className="text-xs text-red-700 mt-1 whitespace-pre-wrap">{log.error_message}</pre>
                          </div>
                        )}

                        {/* Prompt Template (Input Data) */}
                        <CollapsibleSection
                          icon={Terminal}
                          title="Prompt enviado à IA"
                          content={log.input_data}
                          defaultOpen={false}
                        />

                        {/* Resultado da IA */}
                        {log.model_result && (
                          <CollapsibleSection
                            icon={Brain}
                            title="Resposta da IA (JSON)"
                            content={log.model_result}
                            defaultOpen={false}
                          />
                        )}

                        {/* Personalizações extraídas */}
                        {log.extracted_personalization && (
                          <CollapsibleSection
                            icon={FileText}
                            title="Personalizações extraídas"
                            content={log.extracted_personalization}
                            defaultOpen={false}
                          />
                        )}

                        {log.metadata && (
                          <CollapsibleSection
                            icon={Terminal}
                            title="Metadata"
                            content={log.metadata}
                            defaultOpen={false}
                          />
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Paginação */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <p className="text-sm text-muted-foreground">
            Página {page} de {totalPages} ({total} total)
          </p>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage(p => p - 1)}
            >
              Anterior
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => setPage(p => p + 1)}
            >
              Próxima
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
