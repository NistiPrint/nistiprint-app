import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { PlusCircle, Edit, Trash2, Scale } from 'lucide-react';
import { toast } from 'sonner';
import UnitService from '@/services/UnitService';
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

function UnidadeMedidaListPage() {
  const [unidades, setUnidades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchUnidades = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await UnitService.getAll();
      setUnidades(data || []);
    } catch (e) {
      setError(e.message);
      toast.error(`Erro ao carregar unidades de medida: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUnidades();
  }, []);

  const handleDeleteUnidade = async (id) => {
    try {
      await UnitService.delete(id);
      toast.success('Unidade de medida deletada com sucesso!');
      fetchUnidades();
    } catch (e) {
      toast.error(`Erro ao deletar unidade de medida: ${e.message}`);
    }
  };

  if (loading) return <div className="text-center py-4">Carregando Unidades de Medida...</div>;
  if (error) return <div className="text-center py-4 text-red-500">Erro: {error}</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Unidades de Medida</h1>
        <Button asChild size="sm">
          <Link to="novo">
            <PlusCircle className="h-4 w-4 mr-2" /> Nova Unidade
          </Link>
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2">
            <Scale className="h-5 w-5" /> Lista de Unidades de Medida
          </CardTitle>
        </CardHeader>
        <CardContent>
          {unidades.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              Nenhuma unidade de medida encontrada.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Nome</TableHead>
                    <TableHead>Símbolo</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {unidades.map((unidade) => (
                    <TableRow key={unidade.id}>
                      <TableCell className="font-medium">{unidade.name}</TableCell>
                      <TableCell>{unidade.symbol}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button variant="outline" size="sm" asChild>
                            <Link to={`${unidade.id}/editar`}>
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
                                  Tem certeza que deseja deletar a unidade "{unidade.name}"?
                                  Esta ação não pode ser desfeita.
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel>Cancelar</AlertDialogCancel>
                                <AlertDialogAction
                                  onClick={() => handleDeleteUnidade(unidade.id)}
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

export default UnidadeMedidaListPage;