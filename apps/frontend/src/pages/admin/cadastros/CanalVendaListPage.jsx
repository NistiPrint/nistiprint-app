import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { PlusCircle, Edit, Trash2, Store, BadgeCheck, BadgeAlert } from 'lucide-react';
import { toast } from 'sonner';
import CanalVendaService from '@/services/CanalVendaService';
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

function CanalVendaListPage() {
  const [canais, setCanais] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchCanais = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await CanalVendaService.getAll(false); // Obter todos os canais (ativos e inativos)
      setCanais(data || []);
    } catch (e) {
      setError(e.message);
      toast.error(`Erro ao carregar canais de venda: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCanais();
  }, []);

  const handleDeleteCanal = async (id) => {
    try {
      await CanalVendaService.delete(id);
      toast.success('Canal de venda deletado com sucesso!');
      fetchCanais();
    } catch (e) {
      toast.error(`Erro ao deletar canal de venda: ${e.message}`);
    }
  };

  if (loading) return <div className="text-center py-4 text-muted-foreground">Carregando Canais de Venda...</div>;
  if (error) return <div className="text-center py-4 text-red-500">Erro: {error}</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Canais de Venda</h1>
        <Button asChild size="sm">
          <Link to="novo">
            <PlusCircle className="h-4 w-4 mr-2" /> Novo Canal
          </Link>
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2">
            <Store className="h-5 w-5" /> Lista de Canais de Venda
          </CardTitle>
        </CardHeader>
        <CardContent>
          {canais.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              Nenhum canal de venda encontrado.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Nome</TableHead>
                    <TableHead>Plataforma</TableHead>
                    <TableHead>Bling ID</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {canais.map((canal) => (
                    <TableRow key={canal.id}>
                      <TableCell className="font-medium">
                        <div className="flex items-center gap-2">
                          <div 
                            className="w-3 h-3 rounded-full" 
                            style={{ backgroundColor: canal.color || '#007bff' }}
                          />
                          {canal.nome}
                        </div>
                      </TableCell>
                      <TableCell>{canal.plataforma || '-'}</TableCell>
                      <TableCell>{canal.conta_bling_id || '-'}</TableCell>
                      <TableCell>
                        <Badge variant={canal.ativo ? 'default' : 'secondary'}>
                          {canal.ativo ? 'Ativo' : 'Inativo'}
                        </Badge>
                        {canal.fulfillment && <Badge variant="outline" className="ml-1 border-orange-500 text-orange-500">Full</Badge>}
                        {canal.flex && <Badge variant="outline" className="ml-1 border-blue-500 text-blue-500">Flex</Badge>}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button variant="outline" size="sm" asChild>
                            <Link to={`${canal.id}/editar`}>
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
                                  Tem certeza que deseja deletar o canal "{canal.nome}"?
                                  Esta ação não pode ser desfeita.
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel>Cancelar</AlertDialogCancel>
                                <AlertDialogAction
                                  onClick={() => handleDeleteCanal(canal.id)}
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

export default CanalVendaListPage;