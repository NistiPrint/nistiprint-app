import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { format } from 'date-fns';
import { AlertTriangle, History, Loader2, Truck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

export default function PartialCollectionModal({ isOpen, onClose, demandaId, onConfirm }) {
  const [loading, setLoading] = useState(false);
  const [demanda, setDemanda] = useState(null);
  const [quantityToCollect, setQuantityToCollect] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [coletasHistory, setColetasHistory] = useState([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);

  useEffect(() => {
    if (isOpen && demandaId) {
      fetchDemandaDetails();
      fetchColetasHistory();
    } else {
      setDemanda(null);
      setQuantityToCollect('');
      setColetasHistory([]);
    }
  }, [isOpen, demandaId]);

  const fetchDemandaDetails = async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/v2/demanda_producao/${demandaId}`);
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          setDemanda(data.demanda);
          
          // Sugestão padrão: O que está pronto na fábrica menos o que já saiu
          // (Consolidado total de itens montados vs total coletado)
          const totalReady = (data.demanda.itens || []).reduce((acc, item) => 
            acc + Number(item.expedicao_capas_retiradas_qtd || 0), 0);
          const alreadyCollected = Number(data.demanda.quantidade_coletada_total || 0);
          
          const suggested = Math.max(0, totalReady - alreadyCollected);
          setQuantityToCollect(suggested > 0 ? String(suggested) : '');
        } else {
          toast.error(data.message || 'Erro ao carregar detalhes.');
          onClose();
        }
      } else {
        toast.error('Erro ao carregar detalhes da demanda.');
        onClose();
      }
    } catch (e) {
      console.error(e);
      toast.error('Erro de conexão.');
      onClose();
    } finally {
      setLoading(false);
    }
  };

  const fetchColetasHistory = async () => {
    setIsLoadingHistory(true);
    try {
      const res = await fetch(`/api/v2/demanda_producao/${demandaId}/coletas`);
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          setColetasHistory(data.coletas);
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      setIsLoadingHistory(false);
    }
  };

  const handleConfirm = async () => {
    const numQty = parseInt(quantityToCollect, 10);
    if (isNaN(numQty) || numQty <= 0) {
        toast.error("Informe uma quantidade válida para coleta.");
        return;
    }

    const totalOrder = demanda.total_itens || demanda.total_quantidade || 0;
    const alreadyCollected = Number(demanda.quantidade_coletada_total || 0);
    const remainingBalance = totalOrder - alreadyCollected;

    if (numQty > remainingBalance) {
        toast.error(`A quantidade (${numQty}) não pode exceder o saldo do pedido (${remainingBalance}).`);
        return;
    }

    setSubmitting(true);
    try {
        // Envia apenas o número consolidado para o backend refatorado
        await onConfirm(demandaId, numQty);
        onClose();
    } catch (e) {
        toast.error("Erro ao registrar coleta consolidada.");
    } finally {
        setSubmitting(false);
    }
  };

  const totalItems = demanda?.total_itens || demanda?.total_quantidade || 0;
  const alreadyCollected = Number(demanda?.quantidade_coletada_total || 0);
  const totalProducedReady = (demanda?.itens || []).reduce((acc, item) => acc + Number(item.expedicao_capas_retiradas_qtd || 0), 0);
  
  const remainingInOrder = totalItems - alreadyCollected;
  const readyOnShelf = Math.max(0, totalProducedReady - alreadyCollected);

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && !submitting && onClose()}>
      <DialogContent className="max-w-md overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Truck className="h-5 w-5" /> 
            Registro de Coleta Consolidada
          </DialogTitle>
        </DialogHeader>
        
        <div className="flex-1 py-6">
            {loading ? (
                <div className="flex flex-col items-center justify-center py-10 gap-3">
                    <Loader2 className="h-10 w-10 animate-spin text-primary" />
                    <p className="text-sm text-gray-500 text-center px-4">Carregando dados da demanda...</p>
                </div>
            ) : demanda ? (
                <div className="space-y-6">
                    <div className="text-center space-y-1">
                        <h3 className="font-bold text-lg leading-tight">{demanda.nome}</h3>
                        <p className="text-sm text-gray-500">{demanda.canal_venda_nome} - {demanda.pedido_numero || demanda.id}</p>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        <div className="bg-gray-50 p-3 rounded-lg border text-center">
                            <p className="text-[10px] text-gray-500 uppercase font-bold mb-1">Total do Pedido</p>
                            <p className="text-2xl font-black text-gray-900">{totalItems}</p>
                        </div>
                        <div className="bg-blue-50 p-3 rounded-lg border border-blue-100 text-center">
                            <p className="text-[10px] text-blue-600 uppercase font-bold mb-1">Já Entregue</p>
                            <p className="text-2xl font-black text-blue-700">{alreadyCollected}</p>
                        </div>
                    </div>

                    {coletasHistory.length > 0 && (
                      <div className="space-y-2 pt-2">
                        <h4 className="text-sm font-bold text-gray-700 flex items-center gap-2">
                          <History className="h-4 w-4" />
                          Histórico de Coletas
                        </h4>
                        {isLoadingHistory ? (
                          <p className="text-sm text-gray-500">Carregando...</p>
                        ) : (
                          <ul className="space-y-1">
                            {coletasHistory.map(coleta => (
                              <li key={coleta.id} className="text-sm p-2 bg-gray-50 rounded">
                                - {coleta.quantidade} unidades coletadas em {format(new Date(coleta.created_at), 'dd/MM/yyyy HH:mm')}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}

                    <div className="space-y-4 pt-2">
                        <div className="flex items-center justify-between px-1">
                            <label className="text-sm font-bold text-gray-700">Quantidade sendo coletada agora:</label>
                            <Badge variant="secondary" className="font-mono">{remainingInOrder} restante(s)</Badge>
                        </div>
                        
                        <div className="relative">
                            <Input 
                                type="number" 
                                className="h-14 text-2xl text-center font-black border-2 border-primary/20 focus:border-primary"
                                placeholder="0"
                                value={quantityToCollect}
                                onChange={(e) => setQuantityToCollect(e.target.value)}
                                autoFocus
                            />
                            <div className="absolute right-2 top-1/2 -translate-y-1/2 flex gap-1">
                                {readyOnShelf > 0 && readyOnShelf !== remainingInOrder && (
                                    <Button 
                                        variant="outline" 
                                        size="sm" 
                                        className="h-8 text-[10px] bg-amber-50 text-amber-700 border-amber-200"
                                        onClick={() => setQuantityToCollect(String(readyOnShelf))}
                                    >
                                        Pronto ({readyOnShelf})
                                    </Button>
                                )}
                                <Button 
                                    variant="outline" 
                                    size="sm" 
                                    className="h-8 text-[10px] bg-green-50 text-green-700 border-green-200"
                                    onClick={() => setQuantityToCollect(String(remainingInOrder))}
                                >
                                    Total ({remainingInOrder})
                                </Button>
                            </div>
                        </div>

                        {readyOnShelf > 0 && (
                            <div className="flex items-center gap-2 text-[11px] text-amber-600 bg-amber-50/50 p-2 rounded border border-amber-100">
                                <AlertTriangle className="h-3 w-3 shrink-0" />
                                <span>A produção indica que existem <b>{readyOnShelf}</b> itens prontos para envio.</span>
                            </div>
                        )}
                    </div>
                </div>
            ) : (
                <div className="text-center py-8 text-red-500">Falha ao carregar demanda.</div>
            )}
        </div>

        <DialogFooter className="border-t pt-4 bg-white">
            <div className="flex gap-2 w-full">
                <Button variant="outline" className="flex-1" onClick={onClose} disabled={submitting}>Cancelar</Button>
                <Button 
                    onClick={handleConfirm} 
                    disabled={submitting || !quantityToCollect || Number(quantityToCollect) <= 0}
                    className="flex-1 bg-green-600 hover:bg-green-700"
                >
                    {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Truck className="mr-2 h-4 w-4" />}
                    Confirmar Coleta
                </Button>
            </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
