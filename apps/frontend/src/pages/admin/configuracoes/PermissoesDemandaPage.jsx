import React, { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Checkbox } from '@/components/ui/checkbox';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { usePermissions } from '@/contexts/PermissionsContext';
import { toast } from 'sonner';
import { Loader2, Save, ShieldCheck } from 'lucide-react';

const AVAILABLE_FIELDS = [
  { id: 'capas_impressas_qtd', label: 'Capas Impressas' },
  { id: 'capas_produzidas_qtd', label: 'Capas Produzidas' },
  { id: 'capas_prontas_retirada_qtd', label: 'Capas Prontas (Retirada)' },
  { id: 'miolos_prontos_retirada_qtd', label: 'Miolos Prontos (Retirada)' },
  { id: 'expedicao_capas_retiradas_qtd', label: 'Expedição Capas' },
  { id: 'expedicao_miolos_retirados_qtd', label: 'Expedição Miolos' }
];

const AVAILABLE_ACTIONS = [
  { id: 'delete_demand', label: 'Excluir Demanda' },
  { id: 'finalize_item', label: 'Finalizar Item' },
  { id: 'collect_demand', label: 'Coletar Demanda' }
];

export default function PermissoesDemandaPage() {
  const { permissions, updatePermissions } = usePermissions();
  const [sectors, setSectors] = useState([]);
  const [localPermissions, setLocalPermissions] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchSectors();
  }, []);

  useEffect(() => {
    if (permissions) {
        setLocalPermissions(JSON.parse(JSON.stringify(permissions)));
    }
  }, [permissions]);

  const fetchSectors = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/v2/usuarios-setores/setor');
      if (response.ok) {
        const data = await response.json();
        if (data.setores) {
            setSectors(data.setores);
        }
      }
    } catch (e) {
      console.error("Error fetching sectors", e);
      toast.error("Erro ao carregar setores.");
    } finally {
      setLoading(false);
    }
  };

  const handleToggleField = (sectorName, fieldId) => {
    setLocalPermissions(prev => {
      const currentFields = prev.fields[sectorName] || [];
      const newFields = currentFields.includes(fieldId)
        ? currentFields.filter(f => f !== fieldId)
        : [...currentFields, fieldId];
      
      return {
        ...prev,
        fields: {
          ...prev.fields,
          [sectorName]: newFields
        }
      };
    });
  };

  const handleToggleAction = (sectorName, actionId) => {
    setLocalPermissions(prev => {
      const currentActions = prev.actions[sectorName] || [];
      const newActions = currentActions.includes(actionId)
        ? currentActions.filter(a => a !== actionId)
        : [...currentActions, actionId];
      
      return {
        ...prev,
        actions: {
          ...prev.actions,
          [sectorName]: newActions
        }
      };
    });
  };

  const handleSave = async () => {
    setSaving(true);
    try {
        const success = await updatePermissions(localPermissions);
        if (success) {
            toast.success('Permissões atualizadas com sucesso!');
        } else {
            toast.error('Erro ao salvar permissões.');
        }
    } catch (e) {
        toast.error('Ocorreu um erro ao salvar.');
    } finally {
        setSaving(false);
    }
  };

  if (loading || !localPermissions) {
      return <div className="flex justify-center items-center h-64"><Loader2 className="h-8 w-8 animate-spin" /></div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Permissões de Demanda</h2>
          <p className="text-muted-foreground">Gerencie globalmente quais setores podem acessar campos e ações do dashboard de demandas.</p>
        </div>
        <Button onClick={handleSave} disabled={saving}>
          {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
          Salvar Alterações
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-primary">
            <ShieldCheck className="h-5 w-5" />
            Configurações de Acesso
          </CardTitle>
          <CardDescription>
            Defina a visibilidade e editabilidade dos campos por setor.
          </CardDescription>
        </CardHeader>
        <CardContent>
            <Tabs defaultValue="fields" className="w-full">
            <TabsList className="grid w-full grid-cols-2 mb-4">
                <TabsTrigger value="fields">Campos Editáveis</TabsTrigger>
                <TabsTrigger value="actions">Ações Permitidas</TabsTrigger>
            </TabsList>

            <TabsContent value="fields">
                <div className="border rounded-md overflow-x-auto">
                <Table>
                    <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">Setor</TableHead>
                        {AVAILABLE_FIELDS.map(field => (
                        <TableHead key={field.id} className="text-center text-xs px-1 min-w-[100px]">{field.label}</TableHead>
                        ))}
                    </TableRow>
                    </TableHeader>
                    <TableBody>
                    {sectors.map(sector => (
                        <TableRow key={sector.nome}>
                        <TableCell className="font-medium">{sector.nome}</TableCell>
                        {AVAILABLE_FIELDS.map(field => (
                            <TableCell key={field.id} className="text-center">
                            <Checkbox 
                                checked={(localPermissions.fields[sector.nome] || []).includes(field.id)}
                                onCheckedChange={() => handleToggleField(sector.nome, field.id)}
                            />
                            </TableCell>
                        ))}
                        </TableRow>
                    ))}
                    </TableBody>
                </Table>
                </div>
            </TabsContent>

            <TabsContent value="actions">
                <div className="border rounded-md overflow-x-auto">
                <Table>
                    <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">Setor</TableHead>
                        {AVAILABLE_ACTIONS.map(action => (
                        <TableHead key={action.id} className="text-center text-xs px-1 min-w-[100px]">{action.label}</TableHead>
                        ))}
                    </TableRow>
                    </TableHeader>
                    <TableBody>
                    {sectors.map(sector => (
                        <TableRow key={sector.nome}>
                        <TableCell className="font-medium">{sector.nome}</TableCell>
                        {AVAILABLE_ACTIONS.map(action => (
                            <TableCell key={action.id} className="text-center">
                            <Checkbox 
                                checked={(localPermissions.actions[sector.nome] || []).includes(action.id)}
                                onCheckedChange={() => handleToggleAction(sector.nome, action.id)}
                            />
                            </TableCell>
                        ))}
                        </TableRow>
                    ))}
                    </TableBody>
                </Table>
                </div>
            </TabsContent>
            </Tabs>
        </CardContent>
      </Card>
    </div>
  );
}
