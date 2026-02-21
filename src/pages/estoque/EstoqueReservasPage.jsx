import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { estoqueService } from '@/services/EstoqueService';
import { AlarmCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

function EstoqueReservasPage() {
  const [reservasData, setReservasData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchReservas = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await estoqueService.getReservas();
      setReservasData(data);
    } catch (e) {
      setError(e.message);
      toast.error(`Erro ao carregar reservas: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchReservas();
  }, []);

  const handleLiberarReserva = async (produto_id, deposito_id, ordem_id) => {
    if (!window.confirm('Tem certeza que deseja liberar esta reserva? Esta ação não pode ser desfeita.')) {
      return;
    }

    try {
      const result = await estoqueService.liberarReserva({ produto_id, deposito_id, ordem_id });
      if (result.success !== false) {
        toast.success(result.message || 'Reserva liberada com sucesso!');
        fetchReservas(); // Re-fetch reservations to update the list
      } else {
        toast.error(result.error || 'Falha ao liberar reserva.');
      }
    } catch (e) {
      toast.error(`Erro: ${e.message}`);
    }
  };


  if (loading) return <div className="text-center py-4">Carregando Reservas de Estoque...</div>;
  if (error) return <div className="text-center py-4 text-red-500">Erro ao carregar reservas: {error}</div>;

  return (
    <div className="container mx-auto py-8">
      <h1 className="text-3xl font-bold mb-6">Reservas de Estoque</h1>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlarmCheck className="h-5 w-5" /> Reservas Ativas
          </CardTitle>
        </CardHeader>
        <CardContent>
          {reservasData.reservas.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              Nenhuma reserva de estoque ativa encontrada.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Produto</TableHead>
                  <TableHead>Setor Responsável</TableHead>
                  <TableHead>Depósito</TableHead>
                  <TableHead className="text-right">Qtd Reservada</TableHead>
                  <TableHead className="text-right">Qtd Disponível</TableHead>
                  <TableHead>Tipo Ordem</TableHead>
                  <TableHead>Data Reserva</TableHead>
                  <TableHead className="text-right">Ações</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {reservasData.reservas.map((reserva, index) => {
                  // Formatação da data
                  let dataFormatada = 'N/A';
                  try {
                    if (reserva.data_reserva) {
                      const data = reserva.data_reserva.toDate ? reserva.data_reserva.toDate() : new Date(reserva.data_reserva);
                      dataFormatada = data.toLocaleString('pt-BR', {
                        day: '2-digit',
                        month: '2-digit',
                        year: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit'
                      });
                    }
                  } catch (e) {
                    dataFormatada = 'Data inválida';
                  }

                  // Badge para tipo de ordem
                  const getTipoOrdemBadge = (tipo) => {
                    const tipos = {
                      'producao': 'bg-blue-100 text-blue-800',
                      'venda': 'bg-green-100 text-green-800',
                      'ordem_compra': 'bg-purple-100 text-purple-800'
                    };
                    return tipos[tipo] || 'bg-gray-100 text-gray-800';
                  };

                  return (
                    <TableRow key={index}>
                      <TableCell>
                        <div className="font-medium">
                          {reservasData.prefetched_products?.[reserva.produto_id]?.name || `Produto ID: ${reserva.produto_id}`}
                        </div>
                        <div className="text-sm text-muted-foreground">
                          ID: {reserva.produto_id}
                        </div>
                      </TableCell>
                      <TableCell>
                        {reservasData.prefetched_products?.[reserva.produto_id]?.setor_responsavel_nome || '-'}
                      </TableCell>
                      <TableCell>
                        {reservasData.prefetched_depositos?.[reserva.deposito_id]?.name || reserva.deposito_id}
                      </TableCell>
                      <TableCell className="text-right font-medium">
                        {reserva.quantidade_original?.toLocaleString('pt-BR') || reserva.quantidade}
                      </TableCell>
                      <TableCell className="text-right">
                        {reserva.quantidade_disponivel?.toLocaleString('pt-BR') || reserva.quantidade}
                      </TableCell>
                      <TableCell>
                        <span className={`px-2 py-1 rounded-full text-xs font-medium ${getTipoOrdemBadge(reserva.tipo_ordem)}`}>
                          {reserva.tipo_ordem || 'N/A'}
                        </span>
                      </TableCell>
                      <TableCell className="text-sm">{dataFormatada}</TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => handleLiberarReserva(reserva.produto_id, reserva.deposito_id, reserva.ordem_id)}
                        >
                          Liberar Reserva
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default EstoqueReservasPage;
