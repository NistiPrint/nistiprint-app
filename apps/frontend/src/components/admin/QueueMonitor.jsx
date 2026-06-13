import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Play, Repeat, ServerCrash, Trash2, RefreshCcw, CheckCircle, List } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

const QueueService = {
  getStats: async () => {
    const response = await fetch('/api/v2/webhooks/queue/stats');
    if (!response.ok) throw new Error('Falha ao buscar estatísticas');
    return response.json();
  },
  getItems: async (queue, limit = 20) => {
    const response = await fetch(`/api/v2/webhooks/queue/items?queue=${queue}&limit=${limit}`);
    if (!response.ok) throw new Error('Falha ao buscar itens da fila');
    return response.json();
  },
  reprocess: async (source) => {
    const response = await fetch('/api/v2/webhooks/queue/reprocess', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source }),
    });
    if (!response.ok) throw new Error('Falha ao reprocessar fila');
    return response.json();
  },
  clear: async (queue) => {
    const response = await fetch(`/api/v2/webhooks/queue/clear?queue=${queue}`, {
      method: 'DELETE',
    });
    if (!response.ok) throw new Error('Falha ao limpar fila');
    return response.json();
  }
};

export default function QueueMonitor({ embed = false }) {
  const [stats, setStats] = useState({ pendentes: 0, processados: 0, dead_letter: 0, falhas: 0 });
  const [items, setItems] = useState([]);
  const [activeQueue, setActiveQueue] = useState('pendentes');
  const [loading, setLoading] = useState(true);

  const fetchStats = async () => {
    try {
      const data = await QueueService.getStats();
      setStats(data);
    } catch (error) {
      console.error(error);
    }
  };

  const fetchItems = async (queue) => {
    setLoading(true);
    try {
      const data = await QueueService.getItems(queue);
      setItems(data.items || []);
      setActiveQueue(queue);
    } catch (error) {
      toast.error('Erro ao carregar itens da fila.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
    fetchItems('pendentes');
    const interval = setInterval(fetchStats, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleReprocess = async (source) => {
    toast.info(`Reprocessando fila "${source}"...`);
    try {
      const result = await QueueService.reprocess(source);
      toast.success(`${result.reprocessed} itens movidos para a fila de pendentes.`);
      fetchStats();
      fetchItems(activeQueue);
    } catch (error) {
      toast.error(`Erro ao reprocessar fila "${source}".`);
    }
  };

  const handleClear = async (queue) => {
    if (!confirm(`Tem certeza que deseja limpar a fila "${queue}"?`)) return;
    try {
      await QueueService.clear(queue);
      toast.success(`Fila "${queue}" limpa com sucesso.`);
      fetchStats();
      if (activeQueue === queue) setItems([]);
    } catch (error) {
      toast.error(`Erro ao limpar fila "${queue}".`);
    }
  };

  const queueGroups = [
    {
      title: 'Bling',
      queues: [
        ['Bling Pendentes', 'pendentes', 'pending'],
        ['Bling Processados', 'processados', 'processed'],
        ['Bling Falhas', 'falhas', 'failed'],
        ['Bling Dead Letter', 'dead_letter', 'dead'],
      ],
    },
    {
      title: 'Shopee',
      queues: [
        ['Shopee Pendentes', 'shopee_pendentes', 'pending'],
        ['Shopee Falhas', 'shopee_falhas', 'failed'],
        ['Shopee Dead Letter', 'shopee_dead_letter', 'dead'],
      ],
    },
    {
      title: 'Mercado Livre',
      queues: [
        ['Mercado Livre Pendentes', 'mercadolivre_pendentes', 'pending'],
        ['Mercado Livre Falhas', 'mercadolivre_falhas', 'failed'],
        ['Mercado Livre Dead Letter', 'mercadolivre_dead_letter', 'dead'],
      ],
    },
  ];

  return (
    <div className="space-y-6">
      {!embed && (
        <div className="flex justify-between items-center">
          <h2 className="text-3xl font-bold tracking-tight">Monitor de Fila (Bling)</h2>
          <Button onClick={() => { fetchStats(); fetchItems(activeQueue); }} variant="outline" size="sm">
            <RefreshCcw className="mr-2 h-4 w-4" /> Atualizar
          </Button>
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {queueGroups.map((group) => (
          <Card key={group.title}>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">{group.title}</CardTitle>
              <CardDescription>Filas vivas de webhook</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-2">
              {group.queues.map(([label, key, type]) => (
                <QueueRow
                  key={key}
                  title={label}
                  value={stats[key] || 0}
                  type={type}
                  active={activeQueue === key}
                  onClick={() => fetchItems(key)}
                  onReprocess={['failed', 'dead'].includes(type) ? () => handleReprocess(key) : undefined}
                  onClear={key === 'processados' ? undefined : () => handleClear(key)}
                />
              ))}
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>Conteúdo da Fila: {activeQueue.toUpperCase()}</CardTitle>
            <CardDescription>Visualização dos últimos 20 itens na fila do Redis.</CardDescription>
          </div>
          <Badge variant="outline" className="capitalize">{activeQueue}</Badge>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex justify-center p-8">Carregando itens...</div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center justify-center p-8 text-muted-foreground">
              <List className="h-12 w-12 mb-2 opacity-20" />
              <p>Nenhum item encontrado nesta fila.</p>
            </div>
          ) : (
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[100px]">Evento</TableHead>
                    <TableHead>Payload</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item, idx) => (
                    <TableRow key={idx}>
                      <TableCell className="font-medium">
                        <Badge variant="secondary">{item.event || 'N/A'}</Badge>
                      </TableCell>
                      <TableCell>
                        <pre className="text-xs max-w-2xl overflow-hidden text-ellipsis bg-muted p-2 rounded">
                          {JSON.stringify(item, null, 2)}
                        </pre>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="sm" onClick={() => {
                          navigator.clipboard.writeText(JSON.stringify(item, null, 2));
                          toast.success('Copiado para o clipboard');
                        }}>Copiar</Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function QueueRow({ title, value, type, active, onClick, onReprocess, onClear }) {
  const icon = {
    pending: <Play className="h-4 w-4 text-blue-500" />,
    processed: <CheckCircle className="h-4 w-4 text-green-500" />,
    failed: <ServerCrash className="h-4 w-4 text-red-500" />,
    dead: <ServerCrash className="h-4 w-4 text-yellow-500" />,
  }[type] || <Play className="h-4 w-4 text-blue-500" />;

  const handleKeyDown = (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onClick();
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      className={`flex w-full items-center justify-between rounded-md border px-3 py-2 text-left transition-colors ${
        active ? 'border-primary bg-primary/5 ring-1 ring-primary' : 'hover:bg-muted/50'
      }`}
      onClick={onClick}
      onKeyDown={handleKeyDown}
    >
      <span className="flex min-w-0 items-center gap-2">
        {icon}
        <span className="truncate text-sm font-medium">{title}</span>
      </span>
      <span className="flex items-center gap-2">
        <Badge variant="outline" className="min-w-8 justify-center">{value}</Badge>
        <span className="flex gap-1">
          {onReprocess && value > 0 && (
            <Button variant="ghost" size="icon" className="h-7 w-7 text-blue-500" onClick={(e) => { e.stopPropagation(); onReprocess(); }}>
              <Repeat className="h-4 w-4" />
            </Button>
          )}
          {onClear && (
            <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={(e) => { e.stopPropagation(); onClear(); }}>
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
        </span>
      </span>
    </div>
  );
}
