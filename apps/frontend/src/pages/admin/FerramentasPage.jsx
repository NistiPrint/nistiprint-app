import React, { useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Loader2, Upload, Wand2, RefreshCw, Activity } from 'lucide-react';
import { toast } from 'sonner';
import QueueMonitor from '@/components/admin/QueueMonitor';

function FerramentasPage() {
  const [loadingImport, setLoadingImport] = useState(false);
  const [loadingAI, setLoadingAI] = useState(false);
  const [numeroLoja, setNumeroLoja] = useState('');
  const [aiLimit, setAiLimit] = useState('');
  const [aiOrderSn, setAiOrderSn] = useState('');

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

  const handleProcessAINames = async (e) => {
    e.preventDefault();
    setLoadingAI(true);
    try {
      const response = await fetch('/api/v2/ferramentas/processar_nomes_ia', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify({
          limit: aiLimit,
          shopee_order_sn: aiOrderSn,
        }),
      });

      const data = await response.json();
      if (data.success) {
        toast.success(data.message);
      } else {
        toast.error(data.message || 'Erro ao processar nomes com IA.');
      }
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingAI(false);
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
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="import">Importação Manual</TabsTrigger>
          <TabsTrigger value="ai">Processamento IA</TabsTrigger>
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
        </TabsContent>

        <TabsContent value="ai">
          <Card>
            <CardHeader>
              <CardTitle>Identificação de Nomes via IA</CardTitle>
              <CardDescription>
                Processe pedidos para identificar nomes para personalização utilizando Inteligência Artificial.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleProcessAINames} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="limit">Limite de Pedidos (Opcional)</Label>
                    <Input
                      id="limit"
                      type="number"
                      placeholder="Ex: 10"
                      value={aiLimit}
                      onChange={(e) => setAiLimit(e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="shopee_order_sn">ID Específico (Opcional)</Label>
                    <Input
                      id="shopee_order_sn"
                      placeholder="Ex: 230815ABC123"
                      value={aiOrderSn}
                      onChange={(e) => setAiOrderSn(e.target.value)}
                    />
                  </div>
                </div>
                <Button type="submit" disabled={loadingAI}>
                  {loadingAI && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  <Wand2 className="mr-2 h-4 w-4" /> Processar com IA
                </Button>
              </form>
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
