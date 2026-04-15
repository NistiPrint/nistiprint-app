import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useRascunhos } from '@/lib/hooks/useRascunhos';
import { ArrowRight, Bot, Edit, PlayCircle, RefreshCw, Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export default function RascunhosListPage() {
  const navigate = useNavigate();
  const {
    rascunhos,
    loading,
    error,
    refresh,
    publicarRascunho,
    deletarRascunho,
  } = useRascunhos();

  const handlePublicar = async (id) => {
    await publicarRascunho(id);
  };

  const handleEditar = (id) => {
    navigate(`/producao/demanda/${id}/editar`);
  };

  const handleDeletar = async (id) => {
    await deletarRascunho(id);
  };

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] gap-4">
        <Bot className="h-12 w-12 text-red-500" />
        <div className="text-center">
          <h2 className="text-lg font-bold text-gray-900">Erro ao carregar rascunhos</h2>
          <p className="text-gray-500">{error}</p>
        </div>
        <Button onClick={refresh}>
          <RefreshCw className="h-4 w-4 mr-2" />
          Tentar Novamente
        </Button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <RefreshCw className="h-8 w-8 animate-spin text-gray-400" />
      </div>
    );
  }

  return (
    <div className="container mx-auto py-8">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold">Rascunhos de Demandas</h1>
          <p className="text-muted-foreground">Demandas com status Rascunho</p>
        </div>
        <Button onClick={refresh} variant="outline" className="gap-2">
          <RefreshCw className="h-4 w-4" /> Atualizar
        </Button>
      </div>

      {rascunhos.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Bot className="h-16 w-16 text-gray-300 mb-4" />
            <h3 className="text-lg font-semibold text-gray-900 mb-2">
              Nenhum rascunho encontrado
            </h3>
            <p className="text-gray-500 text-center max-w-md">
              Não há demandas com status "Rascunho" no momento.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {rascunhos.map((rascunho) => (
            <Card key={rascunho.id}>
              <CardHeader>
                <div className="flex justify-between items-start">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <CardTitle className="text-lg">{rascunho.nome}</CardTitle>
                      <Badge variant="outline">{rascunho.status}</Badge>
                      {rascunho.canal_nome && (
                        <Badge 
                          variant="outline" 
                          style={{ 
                            borderColor: rascunho.canal_color,
                            color: rascunho.canal_color 
                          }}
                        >
                          {rascunho.canal_nome}
                        </Badge>
                      )}
                    </div>
                    <div className="text-sm text-muted-foreground">
                      Data de entrega: {new Date(rascunho.data_entrega).toLocaleDateString('pt-BR')}
                      {rascunho.total_pedidos > 0 && (
                        <span className="ml-4">Total de pedidos: {rascunho.total_pedidos}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => navigate(`/producao/demanda/${rascunho.id}/dashboard`)}
                      className="gap-2"
                    >
                      <ArrowRight className="h-4 w-4" /> Ver Dashboard
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleEditar(rascunho.id)}
                      className="gap-2"
                    >
                      <Edit className="h-4 w-4" /> Editar
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => handlePublicar(rascunho.id)}
                      className="gap-2 bg-green-600 hover:bg-green-700"
                    >
                      <PlayCircle className="h-4 w-4" /> Publicar
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => handleDeletar(rascunho.id)}
                      className="gap-2"
                    >
                      <Trash2 className="h-4 w-4" /> Deletar
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="text-sm text-muted-foreground">
                  Total de itens: {rascunho.total_itens || 0}
                  {rascunho.pedidos_apos_edicao_qtd > 0 && (
                    <span className="ml-4 text-orange-600 font-medium">
                      {rascunho.pedidos_apos_edicao_qtd} pedidos novos após edição
                    </span>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
