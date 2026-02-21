import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Play, Pause, RotateCcw, AlertCircle, CheckCircle, HardDrive } from 'lucide-react';
import { toast } from 'sonner';
import PrintService from '@/services/PrintService';
import LocalFileMapping from './LocalFileMapping';

const PrintManager = ({ productId, artworks = [] }) => {
  const [printJobs, setPrintJobs] = useState([]);
  const [activeJob, setActiveJob] = useState(null);
  const [loading, setLoading] = useState(false);

  // Load print jobs for the product
  useEffect(() => {
    if (productId) {
      loadPrintJobs();
    }
  }, [productId]);

  const loadPrintJobs = async () => {
    try {
      const response = await PrintService.getProductPrintJobs(productId);
      setPrintJobs(response.print_jobs || []);
    } catch (error) {
      console.error('Error loading print jobs:', error);
      toast.error(`Erro ao carregar trabalhos de impressão: ${error.message}`);
    }
  };

  const handleSendToPrint = async (artworkId = null) => {
    if (!productId) {
      toast.error('Produto não identificado');
      return;
    }

    setLoading(true);
    try {
      const response = await PrintService.sendToPrint(productId, artworkId);
      if (response.success) {
        toast.success(response.message);
        // Add the new job to the list
        const newJob = response.print_job;
        setPrintJobs(prev => [newJob, ...prev]);
        setActiveJob(newJob);
        
        // Start monitoring the job status
        monitorJobStatus(newJob.job_id);
      } else {
        throw new Error(response.message || 'Erro desconhecido');
      }
    } catch (error) {
      console.error('Error sending to print:', error);
      toast.error(`Erro ao enviar para impressão: ${error.response?.data?.error || error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const monitorJobStatus = async (jobId) => {
    // In a real implementation, we would poll the status endpoint
    // For demo purposes, we'll just update the status after a delay
    const interval = setInterval(async () => {
      try {
        const status = await PrintService.getPrintJobStatus(jobId);
        setPrintJobs(prev => prev.map(job => 
          job.job_id === jobId ? { ...job, ...status } : job
        ));
        
        // Update active job if it's the one being monitored
        if (activeJob && activeJob.job_id === jobId) {
          setActiveJob({ ...activeJob, ...status });
        }
        
        // Stop polling if job is completed or cancelled
        if (status.status === 'completed' || status.status === 'cancelled') {
          clearInterval(interval);
        }
      } catch (error) {
        console.error('Error getting job status:', error);
        clearInterval(interval);
      }
    }, 5000); // Poll every 5 seconds
  };

  const getStatusColor = (status) => {
    switch (status) {
      case 'completed': return 'bg-green-500';
      case 'printing': return 'bg-blue-500';
      case 'processing': return 'bg-yellow-500';
      case 'queued': return 'bg-purple-500';
      case 'cancelled': return 'bg-gray-500';
      default: return 'bg-gray-300';
    }
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'completed': return <CheckCircle className="h-4 w-4 text-green-500" />;
      case 'cancelled': return <AlertCircle className="h-4 w-4 text-gray-500" />;
      default: return null;
    }
  };

  const getLatestArtwork = () => {
    if (!artworks || artworks.length === 0) return null;
    // Sort by upload date to get the most recent
    return artworks.slice().sort((a, b) => 
      new Date(b.upload_date) - new Date(a.upload_date)
    )[0];
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex justify-between items-center">
          <span>Impressão de Artes</span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {/* Local File Mapping Section */}
        <div className="mb-8">
          <div className="flex items-center gap-2 mb-4">
            <HardDrive className="h-5 w-5" />
            <h3 className="text-lg font-medium">Impressão Local Híbrida</h3>
          </div>
          <LocalFileMapping productId={productId} />
        </div>

        {/* Original Cloud Printing Section */}
        <div className="mb-6">
          <h3 className="text-lg font-medium mb-3">Impressão na Nuvem</h3>
          <div className="flex flex-col sm:flex-row gap-3">
            <Button
              onClick={() => handleSendToPrint()}
              disabled={loading || !productId || artworks.length === 0}
            >
              {loading ? (
                <>
                  <RotateCcw className="mr-2 h-4 w-4 animate-spin" />
                  Enviando...
                </>
              ) : (
                <>
                  <Play className="mr-2 h-4 w-4" />
                  Imprimir Arte Mais Recente
                </>
              )}
            </Button>

            {artworks.length > 0 && (
              <div className="flex-1">
                <p className="text-sm text-muted-foreground">
                  Última arte: {getLatestArtwork()?.original_filename || 'Nenhuma'}
                </p>
              </div>
            )}
          </div>

          {artworks.length === 0 && (
            <p className="text-sm text-muted-foreground mt-2">
              Nenhuma arte disponível para impressão. Faça upload de uma arte primeiro.
            </p>
          )}
        </div>

        {printJobs.length > 0 && (
          <div>
            <h3 className="text-lg font-medium mb-3">Trabalhos de Impressão na Nuvem</h3>
            <div className="space-y-4">
              {printJobs.map((job) => (
                <div key={job.job_id} className="border rounded-lg p-4 bg-card">
                  <div className="flex justify-between items-start">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium">#{job.job_id}</span>
                        {getStatusIcon(job.status)}
                      </div>
                      <p className="text-sm text-muted-foreground">
                        Criado em: {new Date(job.created_at).toLocaleString()}
                      </p>
                    </div>
                    <Badge className={`${getStatusColor(job.status)} text-white`}>
                      {job.status}
                    </Badge>
                  </div>

                  {job.progress && (
                    <div className="mt-3">
                      <div className="flex justify-between text-sm mb-1">
                        <span>Progresso</span>
                        <span>{job.progress}%</span>
                      </div>
                      <Progress value={job.progress} className="w-full" />
                    </div>
                  )}

                  {job.estimated_completion && (
                    <p className="text-sm text-muted-foreground mt-2">
                      Previsão de conclusão: {new Date(job.estimated_completion).toLocaleString()}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export default PrintManager;