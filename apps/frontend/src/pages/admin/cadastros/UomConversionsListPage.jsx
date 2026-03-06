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
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import UomConversionService from '@/services/UomConversionService';
import { Edit, PlusCircle, Scale, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

function UomConversionsListPage() {
  const [conversions, setConversions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchConversions = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await UomConversionService.getAll();
      setConversions(data || []);
    } catch (e) {
      setError(e.message);
      toast.error(`Erro ao carregar proporções de unidade: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConversions();
  }, []);

  const handleDeleteConversion = async (id) => {
    try {
      await UomConversionService.delete(id);
      toast.success('Proporção deletada com sucesso!');
      fetchConversions();
    } catch (e) {
      toast.error(`Erro ao deletar proporção: ${e.message}`);
    }
  };

  if (loading) return <div className="text-center py-4 text-muted-foreground">Carregando Proporções de Unidade...</div>;
  if (error) return <div className="text-center py-4 text-red-500">Erro: {error}</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Proporções de Unidade</h1>
        <Button asChild size="sm">
          <Link to="new">
            <PlusCircle className="h-4 w-4 mr-2" /> Nova Proporção
          </Link>
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2">
            <Scale className="h-5 w-5" /> Proporções de Unidade por Produto
          </CardTitle>
        </CardHeader>
        <CardContent>
          {conversions.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              Nenhuma proporção de unidade encontrada.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Produto</TableHead>
                    <TableHead>Conversão (De / Para)</TableHead>
                    <TableHead className="text-right">Fator</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {conversions.map((conversion) => (
                    <TableRow key={conversion.id}>
                      <TableCell className="font-medium">{conversion.productName || conversion.productId}</TableCell>
                      <TableCell>
                        {conversion.fromUnitName && conversion.toUnitName 
                          ? `${conversion.fromUnitName} (${conversion.fromUnitSymbol}) -> ${conversion.toUnitName} (${conversion.toUnitSymbol})`
                          : conversion.unitName || 'N/A'}
                      </TableCell>
                      <TableCell className="text-right">{conversion.conversionFactor}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button variant="outline" size="sm" asChild>
                            <Link to={`${conversion.id}/edit`}>
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
                                  Tem certeza que deseja deletar esta proporção?
                                  Esta ação não pode ser desfeita.
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel>Cancelar</AlertDialogCancel>
                                <AlertDialogAction
                                  onClick={() => handleDeleteConversion(conversion.id)}
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

export default UomConversionsListPage;
