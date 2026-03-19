import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Code, Copy, FileJson, Loader2, Search, Terminal } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

const LiveOrderConsultation = ({ integrationId, moduleName, moduleId }) => {
  const [orderSn, setOrderSn] = useState('');
  const [loading, setLoading] = useState(false);
  const [rawData, setRawData] = useState(null);
  const [open, setOpen] = useState(false);
  const [viewMode, setViewMode] = useState('formatted');

  const handleConsult = async () => {
    if (!orderSn.trim()) {
      toast.error('Informe o ID do pedido');
      return;
    }

    setLoading(true);
    setRawData(null);
    try {
      const response = await fetch('/api/v2/order/get_order_detail', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          order_sn_list: orderSn.trim(),
          instance_id: integrationId,
          module_id: moduleId
        }),
      });

      const result = await response.json();
      console.log('DEBUG: Live Consultation Result:', result);

      if (result.success && result.data) {
        setRawData(result.data);
        toast.success('Consulta realizada com sucesso!');
      } else {
        toast.error(result.message || 'Erro na consulta externa.');
      }
    } catch (error) {
      console.error('Error consulting live order:', error);
      toast.error('Erro ao conectar com a API de consulta.');
    } finally {
      setLoading(false);
    }
  };

  const copyToClipboard = () => {
    if (!rawData) return;
    const text = JSON.stringify(rawData, null, 2);
    navigator.clipboard.writeText(text);
    toast.success('JSON copiado!');
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="flex items-center gap-2">
          <Terminal className="h-4 w-4" />
          Debug
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-4xl w-[95vw] h-[85vh] flex flex-col p-0 overflow-hidden bg-slate-950 text-slate-50 border-slate-800">
        <DialogHeader className="p-6 pb-2 border-b border-slate-800">
          <DialogTitle className="flex items-center gap-2 text-slate-50">
            <Terminal className="h-5 w-5 text-green-400" />
            Console de Inspeção: {moduleName}
          </DialogTitle>
          <DialogDescription className="text-slate-400">
            Visualização direta dos dados retornados pela API da plataforma ({moduleId}).
          </DialogDescription>
        </DialogHeader>

        <div className="px-6 py-4 flex items-end gap-3 bg-slate-900/50">
          <div className="grid flex-1 gap-1.5">
            <Label htmlFor="orderSn" className="text-xs uppercase text-slate-500 font-bold">Order SN / ID</Label>
            <Input
              id="orderSn"
              placeholder="Digite o código do pedido..."
              value={orderSn}
              onChange={(e) => setOrderSn(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleConsult()}
              className="bg-slate-950 border-slate-700 text-green-400 font-mono focus-visible:ring-green-500"
            />
          </div>
          <Button 
            onClick={handleConsult} 
            disabled={loading}
            className="bg-green-600 hover:bg-green-700 text-white min-w-[120px]"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Search className="h-4 w-4 mr-2" />}
            Consultar
          </Button>
        </div>

        <div className="flex-1 overflow-hidden flex flex-col bg-slate-950">
          <div className="flex items-center justify-between px-6 py-2 border-y border-slate-800 bg-slate-900/30">
            <Tabs value={viewMode} onValueChange={setViewMode} className="w-auto">
              <TabsList className="bg-slate-800 text-slate-400 h-8 p-0.5">
                <TabsTrigger value="formatted" className="text-xs data-[state=active]:bg-slate-950 data-[state=active]:text-green-400">
                  <FileJson className="h-3 w-3 mr-1.5" /> JSON Formatado
                </TabsTrigger>
                <TabsTrigger value="raw" className="text-xs data-[state=active]:bg-slate-950 data-[state=active]:text-green-400">
                  <Code className="h-3 w-3 mr-1.5" /> Raw String
                </TabsTrigger>
              </TabsList>
            </Tabs>

            {rawData && (
              <Button variant="ghost" size="sm" onClick={copyToClipboard} className="text-slate-400 hover:text-white hover:bg-slate-800 h-8 text-xs">
                <Copy className="h-3.5 w-3.5 mr-1.5" /> Copiar JSON
              </Button>
            )}
          </div>

          <ScrollArea className="flex-1 p-0">
            {rawData ? (
              <div className="p-4 font-mono text-[13px] leading-relaxed selection:bg-green-500/30">
                <pre className="text-green-400/90 whitespace-pre-wrap">
                  {viewMode === 'formatted' 
                    ? JSON.stringify(rawData, null, 2) 
                    : JSON.stringify(rawData)
                  }
                </pre>
              </div>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-slate-600 py-20">
                <Terminal className="h-16 w-16 mb-4 opacity-20" />
                <p className="font-mono text-sm uppercase tracking-widest opacity-40">Aguardando comando de consulta...</p>
              </div>
            )}
          </ScrollArea>
        </div>

        <DialogFooter className="p-4 border-t border-slate-800 bg-slate-900/50">
          <div className="flex-1 flex items-center text-[10px] font-mono text-slate-500 uppercase tracking-tighter">
            {rawData ? `Request ID: ${rawData.request_id || 'N/A'}` : 'Pronto para inspeção'}
          </div>
          <Button variant="outline" onClick={() => setOpen(false)} className="border-slate-700 text-slate-300 hover:bg-slate-800 hover:text-white">
            Fechar Console
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default LiveOrderConsultation;
