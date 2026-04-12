import QueueMonitor from '@/components/admin/QueueMonitor';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Activity, Brain, Loader2, RefreshCw, Upload } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

function FerramentasPage() {
  const navigate = useNavigate();
  const [loadingImport, setLoadingImport] = useState(false);
  const [numeroLoja, setNumeroLoja] = useState('');

  const handleImportBlingOrder = async (e) => {
    e.preventDefault();
    if (!numeroLoja) {
      toast.warning('Número do pedido é obrigatório.');
      return;
    }

    setLoadingImport(true);
    try {
      const response = await fetch('/api/v2/ferramentas/importar_pedido_bling', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify({ numero_loja: numeroLoja }),
      });

      const data = await response.json();
      if (data.success) {
        toast.success(data.message);
        setNumeroLoja('');
      } else {
        toast.error(data.message || 'Erro ao importar pedido.');
      }
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingImport(false);
    }
  };

  const handleUpdateProductStatus = async () => {
      if (!confirm('Isso atualizará o status de TODOS os produtos para "ativo". Continuar?')) return;

      try {
          const response = await fetch('/api/v2/ferramentas/update_product_status', {
              headers: { 'Accept': 'application/json'}
          });
          const data = await response.json();
          if (data.success) {
              toast.success(data.message);
          } else {
              toast.error(data.message);
          }
      } catch (error) {
          toast.error(`Erro: ${error.message}`);
      }
  }

  return (
    <div className="container mx-auto py-8">
      <h1 className="text-3xl font-bold mb-6">Ferramentas Administrativas</h1>

      <Tabs defaultValue="import" className="w-full">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="import">Importação Manual</TabsTrigger>
          <TabsTrigger value="queue">
            <Activity className="w-4 h-4 mr-2" /> Monitor de Fila
          </TabsTrigger>
          <TabsTrigger value="maintenance">Manutenção</TabsTrigger>
        </TabsList>

        <TabsContent value="import">
          <Card>
            <CardHeader>
              <CardTitle>Importar Pedido do Bling</CardTitle>
              <CardDescription>
                Importe manualmente um pedido específico do Bling usando o número da loja (Shopee ID).
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleImportBlingOrder} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="numero_loja">Número do Pedido na Loja</Label>
                  <Input
                    id="numero_loja"
                    placeholder="Ex: 230815ABC123"
                    value={numeroLoja}
                    onChange={(e) => setNumeroLoja(e.target.value)}
                  />
                </div>
                <Button type="submit" disabled={loadingImport}>
                  {loadingImport && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  <Upload className="mr-2 h-4 w-4" /> Importar Pedido
                </Button>
              </form>
            </CardContent>
          </Card>

          <Card className="mt-6">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Brain className="h-5 w-5" />
                IA - Inteligência Artificial
              </CardTitle>
              <CardDescription>
                Gerenciamento de processamento de IA para personalizações
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button onClick={() => navigate('/ferramentas/ia')} className="w-full">
                <Brain className="mr-2 h-4 w-4" />
                Acessar Painel de IA
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="queue">
          <QueueMonitor />
        </TabsContent>

        <TabsContent value="maintenance">
            <Card>
                <CardHeader>
                    <CardTitle>Manutenção de Produtos</CardTitle>
                    <CardDescription>Ações em massa para correção de dados.</CardDescription>
                </CardHeader>
                <CardContent>
                    <Button
                        onClick={handleUpdateProductStatus}
                        variant="outline"
                    >
                        <RefreshCw className="mr-2 h-4 w-4" />
                        Atualizar Status de Todos os Produtos para 'Ativo'
                    </Button>
                </CardContent>
            </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default FerramentasPage;
