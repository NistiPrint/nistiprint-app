import React, { useState, useEffect } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';

function StockHistoryViewer({ itemId, onClose }) {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const response = await fetch(`/api/v2/demanda_producao/item/${itemId}/stock-history`);
        const data = await response.json();
        if (data.success) {
          setHistory(data.history);
        } else {
          toast.error('Erro ao carregar histórico de estoque');
        }
      } catch (e) {
        toast.error('Erro de conexão ao buscar histórico');
      } finally {
        setLoading(false);
      }
    };
    fetchHistory();
  }, [itemId]);

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex justify-end">
      <div className="bg-white w-full max-w-2xl h-full shadow-xl p-6 overflow-y-auto">
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-xl font-bold">Histórico de Estoque (Reconciliação)</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-black">Fechar</button>
        </div>
        
        {loading ? (
          <p>Carregando...</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Estágio</TableHead>
                <TableHead>Data</TableHead>
                <TableHead>Qtd Efetivada</TableHead>
                <TableHead>ID Correlação</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {history.map((entry) => (
                <TableRow key={entry.id}>
                  <TableCell className="font-medium">{entry.estagio}</TableCell>
                  <TableCell>{new Date(entry.created_at).toLocaleString()}</TableCell>
                  <TableCell>
                    <Badge variant={entry.quantidade >= 0 ? "default" : "destructive"}>
                      {entry.quantidade > 0 ? '+' : ''}{entry.quantidade}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{entry.correlation_id}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}

export default StockHistoryViewer;
