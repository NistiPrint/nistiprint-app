import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { useRealtimePrintJobs } from '@/lib/hooks/useRealtimePrintJobs';
import { Loader2, Printer, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import React from 'react';

export default function FilaImpressao() {
  const { jobs, loading, refresh } = useRealtimePrintJobs();

  const handleRetry = async (jobId) => {
    try {
      const res = await fetch(`/api/v2/printing/job/${jobId}/retry`, { method: 'POST' });
      if (res.ok) {
        toast.success('Job reiniciado');
        refresh();
      } else {
        toast.error('Erro ao reiniciar job');
      }
    } catch (e) {
      toast.error('Erro de conexão');
    }
  };

  if (loading && jobs.length === 0) {
    return (
      <div className="flex justify-center items-center h-screen">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  return (
    <div className="container mx-auto py-8">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Printer className="h-8 w-8" /> Fila de Impressão
        </h1>
        <Button onClick={() => refresh()} variant="outline">
          <RefreshCw className="h-4 w-4 mr-2" /> Atualizar
        </Button>
      </div>

      <div className="grid gap-4">
        {jobs.length === 0 ? (
          <div className="text-center py-12 text-muted-foreground">
            <Printer className="mx-auto h-12 w-12 text-muted-foreground/50 mb-4" />
            <p className="text-lg">Nenhum job na fila.</p>
          </div>
        ) : (
          jobs.map((job) => (
            <Card key={job.id} className="flex flex-row justify-between items-center p-4">
               <div>
                  <h3 className="font-bold">Job #{job.id} - {job.tipo_arquivo}</h3>
                  <p className="text-sm text-gray-500">Criado em: {new Date(job.created_at).toLocaleString()}</p>
                  <p className="text-sm text-gray-500">Impressora: {job.impressora_alvo || 'Qualquer'}</p>
                  <p className="text-xs text-gray-400">Demanda Item ID: {job.demanda_item_id}</p>
               </div>
               <div className="flex items-center gap-4">
                  <Badge variant={job.status === 'concluido' ? 'success' : job.status === 'erro' ? 'destructive' : 'default'}>
                    {job.status}
                  </Badge>
                  {job.status === 'erro' && (
                    <Button size="sm" onClick={() => handleRetry(job.id)}>
                      Re-tentar
                    </Button>
                  )}
               </div>
            </Card>
          ))
        )}
      </div>
    </div>
  );
}
