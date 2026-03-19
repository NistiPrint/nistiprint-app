import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { PlusCircle, Edit, Trash2, Share2 } from 'lucide-react';
import { toast } from 'sonner';
import PlataformaService from '@/services/PlataformaService';
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

function PlataformaListPage() {
  const [plataformas, setPlataformas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchPlataformas = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await PlataformaService.getAll();
      setPlataformas(data || []);
    } catch (e) {
      setError(e.message);
      toast.error(`Erro ao carregar plataformas: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPlataformas();
  }, []);

  const handleDelete = async (id) => {
    try {
      await PlataformaService.delete(id);
      toast.success('Plataforma deletada com sucesso!');
      fetchPlataformas();
    } catch (e) {
      toast.error(`Erro ao deletar plataforma: ${e.message}`);
    }
  };

  if (loading) return <div className="text-center py-4 text-muted-foreground">Carregando Plataformas...</div>;
  if (error) return <div className="text-center py-4 text-red-500">Erro: {error}</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Plataformas</h1>
        <Button asChild size="sm">
          <Link to="novo">
            <PlusCircle className="h-4 w-4 mr-2" /> Nova Plataforma
          </Link>
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2">
            <Share2 className="h-5 w-5" /> Lista de Plataformas
          </CardTitle>
        </CardHeader>
        <CardContent>
          {plataformas.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              Nenhuma plataforma encontrada.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Nome</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {plataformas.map((plataforma) => (
                    <TableRow key={plataforma.id}>
                      <TableCell className="font-medium">{plataforma.nome}</TableCell>
                      <TableCell>
                        <Badge variant={plataforma.ativo ? 'default' : 'secondary'}>
                          {plataforma.ativo ? 'Ativa' : 'Inativa'}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button variant="outline" size="sm" asChild>
                            <Link to={`${plataforma.id}/editar`}>
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
                                  Tem certeza que deseja deletar a plataforma "{plataforma.nome}"?
                                  Esta ação não pode ser desfeita.
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel>Cancelar</AlertDialogCancel>
                                <AlertDialogAction
                                  onClick={() => handleDelete(plataforma.id)}
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

export default PlataformaListPage;
