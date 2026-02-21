import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { RotateCcw, Upload, Printer, Wifi, WifiOff, MapPin } from 'lucide-react';
import { toast } from 'sonner';
import useLocalAgent from '@/hooks/useLocalAgent';

const LocalFileMapping = ({ productId }) => {
  const {
    isAgentOnline,
    checkingAgent,
    checkAgentStatus,
    mapFileToProduct,
    getMappedFileForProduct,
    printMappedFile
  } = useLocalAgent();

  const [mappedFile, setMappedFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [printCopies, setPrintCopies] = useState(1);

  // Load mapped file when component mounts or agent status changes
  useEffect(() => {
    if (productId && isAgentOnline) {
      loadMappedFile();
    }
  }, [productId, isAgentOnline]);

  const loadMappedFile = async () => {
    if (!productId) return;

    try {
      const result = await getMappedFileForProduct(productId);
      setMappedFile(result);
    } catch (error) {
      console.error('Error loading mapped file:', error);
    }
  };

  const handleMapFile = async () => {
    if (!productId) {
      toast.error('Produto não identificado');
      return;
    }

    setLoading(true);
    try {
      const result = await mapFileToProduct(productId);
      toast.success(result.message || 'Janela de seleção de arquivo aberta. Por favor, selecione um arquivo.');

      // Wait a bit and reload the mapped file
      setTimeout(() => {
        loadMappedFile();
        setLoading(false);
      }, 2000);
    } catch (error) {
      console.error('Error mapping file:', error);
      toast.error(`Erro ao mapear arquivo: ${error.message}`);
      setLoading(false);
    }
  };

  const handlePrint = async () => {
    if (!productId) {
      toast.error('Produto não identificado');
      return;
    }

    if (!mappedFile) {
      toast.error('Nenhum arquivo mapeado para este produto');
      return;
    }

    setLoading(true);
    try {
      const result = await printMappedFile(productId, parseInt(printCopies));
      toast.success(result.message || `Enviado para impressão: ${result.file_path}`);
      setLoading(false);
    } catch (error) {
      console.error('Error printing file:', error);
      toast.error(`Erro ao imprimir: ${error.message}`);
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    setLoading(true);
    await checkAgentStatus();
    await loadMappedFile();
    setLoading(false);
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex justify-between items-center">
          <div>
            <CardTitle className="flex items-center gap-2">
              <MapPin className="h-5 w-5" />
              Impressão Local Híbrida
            </CardTitle>
            <CardDescription>
              Imprima arquivos diretamente da sua máquina local
            </CardDescription>
          </div>
          
          <div className="flex items-center gap-2">
            <Badge variant={isAgentOnline ? "default" : "secondary"}>
              {checkingAgent ? (
                <RotateCcw className="mr-1 h-3 w-3 animate-spin" />
              ) : isAgentOnline ? (
                <Wifi className="mr-1 h-3 w-3" />
              ) : (
                <WifiOff className="mr-1 h-3 w-3" />
              )}
              {isAgentOnline ? 'Online' : 'Offline'}
            </Badge>
            <Button
              variant="outline"
              size="sm"
              onClick={handleRefresh}
              disabled={loading}
            >
              <RotateCcw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </div>
      </CardHeader>
      
      <CardContent>
        {!isAgentOnline ? (
          <Alert>
            <AlertDescription>
              O agente local não está em execução. Por favor, inicie o serviço do agente local em sua máquina para usar esta funcionalidade.
            </AlertDescription>
          </Alert>
        ) : (
          <div className="space-y-4">
            <div className="flex flex-col sm:flex-row gap-3">
              <Button
                onClick={handleMapFile}
                disabled={loading}
                className="flex-1"
              >
                <Upload className="mr-2 h-4 w-4" />
                Vincular Arquivo Local
              </Button>
              
              <div className="flex-1 min-w-[150px]">
                <Label htmlFor="copies">Cópias</Label>
                <Input
                  id="copies"
                  type="number"
                  min="1"
                  value={printCopies}
                  onChange={(e) => setPrintCopies(Math.max(1, parseInt(e.target.value) || 1))}
                  disabled={loading || !mappedFile}
                />
              </div>
              
              <Button
                onClick={handlePrint}
                disabled={loading || !mappedFile}
                className="flex-1"
              >
                <Printer className="mr-2 h-4 w-4" />
                Imprimir Local
              </Button>
            </div>

            {mappedFile && (
              <div className="p-3 border rounded-md bg-secondary">
                <p className="text-sm font-medium">Arquivo mapeado:</p>
                <p className="text-xs text-muted-foreground truncate" title={mappedFile.file_path}>
                  {mappedFile.file_path}
                </p>
                <p className="text-xs text-muted-foreground">
                  Atualizado em: {new Date(mappedFile.updated_at).toLocaleString()}
                </p>
              </div>
            )}
            
            {!mappedFile && (
              <p className="text-sm text-muted-foreground">
                Nenhum arquivo local vinculado a este produto. Clique em "Vincular Arquivo Local" para selecionar um arquivo em sua máquina.
              </p>
            )}
          </div>
        )}
      </CardContent>
      
      <CardFooter className="text-xs text-muted-foreground">
        Esta funcionalidade permite imprimir arquivos diretamente da sua máquina local sem fazer upload para a nuvem.
      </CardFooter>
    </Card>
  );
};

export default LocalFileMapping;