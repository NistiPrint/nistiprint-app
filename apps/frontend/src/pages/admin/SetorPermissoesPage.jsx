import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SectorService from '@/services/SectorService';
import { ArrowLeft, Loader2, Save } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';

const SetorPermissoesPage = () => {
  const { id } = useParams();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [setor, setSetor] = useState(null);
  const [recursos, setRecursos] = useState([]);
  const [permissoes, setPermissoes] = useState({});

  useEffect(() => {
    fetchData();
  }, [id]);

  const fetchData = async () => {
    try {
      setLoading(true);
      const [setorData, recursosData, permissoesData] = await Promise.all([
        SectorService.getById(id),
        SectorService.getResources(),
        SectorService.getPermissions(id)
      ]);
      
      setSetor(setorData);
      setRecursos(recursosData);
      setPermissoes(permissoesData);
    } catch (error) {
      console.error('Erro ao carregar dados:', error);
      toast.error("Não foi possível carregar os dados do setor.");
      navigate('/sistema/setores');
    } finally {
      setLoading(false);
    }
  };

  const handlePermissionChange = (recursoNome, tipo, value) => {
    setPermissoes(prev => {
      const existing = prev[recursoNome] || { ler: false, criar: false, editar: false, excluir: false };
      return {
        ...prev,
        [recursoNome]: {
          ...existing,
          [tipo]: value
        }
      };
    });
  };

  const handleColumnToggle = (tipo, value) => {
    const updatedPermissoes = { ...permissoes };

    recursos.forEach(recurso => {
      if (!updatedPermissoes[recurso.nome]) {
        updatedPermissoes[recurso.nome] = { ler: false, criar: false, editar: false, excluir: false };
      }
      updatedPermissoes[recurso.nome] = {
        ...updatedPermissoes[recurso.nome],
        [tipo]: value
      };
    });

    setPermissoes(updatedPermissoes);
  };

  const handleSalvarTudo = async () => {
    try {
      setSaving(true);
      
      // Criamos uma lista de promises para salvar cada recurso
      const updatePromises = recursos.map(recurso => {
        const p = permissoes[recurso.nome] || { ler: false, criar: false, editar: false, excluir: false };
        return SectorService.updatePermission(id, {
          recurso: recurso.nome,
          ler: p.ler,
          criar: p.criar,
          editar: p.editar,
          excluir: p.excluir
        });
      });

      await Promise.all(updatePromises);
      toast.success("Todas as permissões foram salvas com sucesso!");
    } catch (error) {
      console.error('Erro ao salvar permissões:', error);
      toast.error("Ocorreu um erro ao salvar algumas permissões.");
    } finally {
      setSaving(false);
    }
  };

  const getColumnCheckedState = (tipo) => {
    if (recursos.length === 0) return false;
    return recursos.every(recurso => {
      const permissao = permissoes[recurso.nome] || { ler: false, criar: false, editar: false, excluir: false };
      return permissao[tipo];
    });
  };

  const getTooltip = (recurso, tipo) => {
    const nome = recurso.descricao || recurso.nome;
    const acoes = {
      ler: `Permite visualizar e listar ${nome.toLowerCase()}.`,
      criar: `Permite cadastrar novos itens em ${nome.toLowerCase()}.`,
      editar: `Permite alterar dados existentes em ${nome.toLowerCase()}.`,
      excluir: `Permite remover registros de ${nome.toLowerCase()} do sistema.`
    };
    return acoes[tipo];
  };

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="container mx-auto py-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => navigate('/sistema/setores')}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Permissões de Acesso</h1>
            <p className="text-muted-foreground">
              Gerenciando permissões para o setor: <span className="font-semibold text-foreground">{setor?.nome}</span>
            </p>
          </div>
        </div>
        
        <Button 
          onClick={handleSalvarTudo} 
          disabled={saving}
          className="bg-green-600 hover:bg-green-700 text-white gap-2"
        >
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Salvar Alterações
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Matriz de Permissões</CardTitle>
          <CardDescription>
            Defina o que os usuários deste setor podem fazer em cada módulo do sistema. Passe o mouse sobre as caixas para ver detalhes.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[300px]">Módulo / Recurso</TableHead>
                <TableHead className="text-center w-[120px]">
                  <div className="flex flex-col items-center gap-1">
                    <span className="text-xs uppercase font-bold">Ler</span>
                    <Checkbox
                      checked={getColumnCheckedState('ler')}
                      onCheckedChange={(checked) => handleColumnToggle('ler', checked)}
                      title="Marcar/Desmarcar todos para Leitura"
                    />
                  </div>
                </TableHead>
                <TableHead className="text-center w-[120px]">
                  <div className="flex flex-col items-center gap-1">
                    <span className="text-xs uppercase font-bold">Criar</span>
                    <Checkbox
                      checked={getColumnCheckedState('criar')}
                      onCheckedChange={(checked) => handleColumnToggle('criar', checked)}
                      title="Marcar/Desmarcar todos para Criação"
                    />
                  </div>
                </TableHead>
                <TableHead className="text-center w-[120px]">
                  <div className="flex flex-col items-center gap-1">
                    <span className="text-xs uppercase font-bold">Editar</span>
                    <Checkbox
                      checked={getColumnCheckedState('editar')}
                      onCheckedChange={(checked) => handleColumnToggle('editar', checked)}
                      title="Marcar/Desmarcar todos para Edição"
                    />
                  </div>
                </TableHead>
                <TableHead className="text-center w-[120px]">
                  <div className="flex flex-col items-center gap-1">
                    <span className="text-xs uppercase font-bold">Excluir</span>
                    <Checkbox
                      checked={getColumnCheckedState('excluir')}
                      onCheckedChange={(checked) => handleColumnToggle('excluir', checked)}
                      title="Marcar/Desmarcar todos para Exclusão"
                    />
                  </div>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recursos.map((recurso) => {
                const permissao = permissoes[recurso.nome] || { ler: false, criar: false, editar: false, excluir: false };
                
                return (
                  <TableRow key={recurso.id} className="hover:bg-muted/50">
                    <TableCell>
                      <div className="font-medium capitalize">{recurso.nome.replace('_', ' ')}</div>
                      <div className="text-sm text-muted-foreground">{recurso.descricao}</div>
                    </TableCell>
                    <TableCell className="text-center">
                      <Checkbox 
                        checked={permissao.ler}
                        onCheckedChange={(checked) => handlePermissionChange(recurso.nome, 'ler', checked)}
                        title={getTooltip(recurso, 'ler')}
                      />
                    </TableCell>
                    <TableCell className="text-center">
                      <Checkbox 
                        checked={permissao.criar}
                        onCheckedChange={(checked) => handlePermissionChange(recurso.nome, 'criar', checked)}
                        title={getTooltip(recurso, 'criar')}
                      />
                    </TableCell>
                    <TableCell className="text-center">
                      <Checkbox 
                        checked={permissao.editar}
                        onCheckedChange={(checked) => handlePermissionChange(recurso.nome, 'editar', checked)}
                        title={getTooltip(recurso, 'editar')}
                      />
                    </TableCell>
                    <TableCell className="text-center">
                      <Checkbox 
                        checked={permissao.excluir}
                        onCheckedChange={(checked) => handlePermissionChange(recurso.nome, 'excluir', checked)}
                        title={getTooltip(recurso, 'excluir')}
                      />
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
};

export default SetorPermissoesPage;