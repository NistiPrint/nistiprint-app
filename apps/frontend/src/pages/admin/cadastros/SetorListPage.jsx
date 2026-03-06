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
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import PageHeader from '@/components/ui/PageHeader';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import SectorService from '@/services/SectorService';
import { Building, Edit, PlusCircle, Trash2, Shield } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

function SetorListPage() {
  const [setores, setSetores] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchSetores();
  }, []);

  const fetchSetores = async () => {
    try {
      const data = await SectorService.getAll();
      setSetores(data);
    } catch (error) {
      toast.error('Erro ao carregar setores');
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id) => {
    try {
      await SectorService.delete(id);
      toast.success('Setor deletado com sucesso');
      fetchSetores(); // Refresh the list
    } catch (error) {
      toast.error('Erro ao deletar setor');
    }
  };

  if (loading) {
    return <div className="text-center py-4">Carregando setores...</div>;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Setores"
        icon={Building}
        actions={
          <Button asChild>
            <Link to="/sistema/setores/novo">
              <PlusCircle className="mr-2 h-4 w-4" />
              Novo Setor
            </Link>
          </Button>
        }
      />
      <Card>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nome</TableHead>
                <TableHead>Descrição</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Ações</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {setores.map((setor) => (
                <TableRow key={setor.id}>
                  <TableCell className="font-medium">{setor.nome}</TableCell>
                  <TableCell>{setor.descricao || 'N/A'}</TableCell>
                  <TableCell>
                    <Badge variant={setor.ativo ? 'default' : 'secondary'}>
                      {setor.ativo ? 'Ativo' : 'Inativo'}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                       <Button variant="outline" size="sm" asChild>
                        <Link to={`/sistema/setores/${setor.id}/permissoes`}>
                          <Shield className="h-4 w-4 mr-2" />
                          Permissões
                        </Link>
                      </Button>
                      <Button variant="outline" size="sm" asChild>
                        <Link to={`/sistema/setores/${setor.id}/editar`}>
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
                              Tem certeza que deseja deletar o setor "{setor.nome}"?
                              Esta ação não pode ser desfeita.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Cancelar</AlertDialogCancel>
                            <AlertDialogAction
                              onClick={() => handleDelete(setor.id)}
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

          {setores.length === 0 && (
            <div className="text-center py-8 text-muted-foreground">
              Nenhum setor cadastrado.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default SetorListPage;
