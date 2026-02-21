import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { PlusCircle, Edit, Trash2, Warehouse } from 'lucide-react';
import { toast } from 'sonner';
import DepositoService from '@/services/DepositoService';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';

function DepositoListPage() {
  const [depositos, setDepositos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchDepositos = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await DepositoService.getAll();
      setDepositos(data || []);
    } catch (e) {
      setError(e.message);
      toast.error(`Erro ao carregar depósitos: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDepositos();
  }, []);

  const handleDeleteDeposito = async (id) => {
    try {
      await DepositoService.delete(id);
      toast.success('Depósito deletado com sucesso!');
      fetchDepositos();
    } catch (e) {
      toast.error(`Erro ao deletar depósito: ${e.message}`);
    }
  };

  if (loading) return <div className="text-center py-4 text-muted-foreground">Carregando Depósitos...</div>;
  if (error) return <div className="text-center py-4 text-red-500">Erro: {error}</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Depósitos</h1>
        <Button asChild size="sm">
          <Link to="novo">
            <PlusCircle className="h-4 w-4 mr-2" /> Novo Depósito
          </Link>
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2">
            <Warehouse className="h-5 w-5" /> Lista de Depósitos
          </CardTitle>
        </CardHeader>
        <CardContent>
          {depositos.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              Nenhum depósito encontrado.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Nome</TableHead>
                    <TableHead>Tipo</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {depositos.map((deposito) => (
                    <TableRow key={deposito.id}>
                      <TableCell className="font-medium">{deposito.nome}</TableCell>
                      <TableCell>{deposito.tipo}</TableCell>
                      <TableCell>
                        <Badge variant={deposito.ativo ? 'default' : 'secondary'}>
                          {deposito.ativo ? 'Ativo' : 'Inativo'}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button variant="outline" size="sm" asChild>
                            <Link to={`${deposito.id}/editar`}>
                              <Edit className="h-4 w-4" />
                            </Link>
                          </Button>

                          <AlertDialog>
                            <AlertDialogTrigger asChild>
                              <Button variant="outline" size="sm">
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </AlertDialogTrigger>
                            <AlertDialogContent>
                              <AlertDialogHeader>
                                <AlertDialogTitle>Confirmar exclusão</AlertDialogTitle>
                                <AlertDialogDescription>
                                  Tem certeza que deseja deletar o depósito "{deposito.nome}"?
                                  Esta ação não pode ser desfeita.
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel>Cancelar</AlertDialogCancel>
                                <AlertDialogAction
                                  onClick={() => handleDeleteDeposito(deposito.id)}
                                  className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                                >
                                  Deletar
                                </AlertDialogAction>
                              </AlertDialogFooter>
                            </AlertDialogContent>
                          </AlertDialog>
                        </div>
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

export default DepositoListPage;
