import React, { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Checkbox } from '@/components/ui/checkbox';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { usePermissions } from '@/contexts/PermissionsContext';
import { toast } from 'sonner';
import { Loader2 } from 'lucide-react';

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

export function DemandaPermissionsConfig({ open, onOpenChange }) {
  const { permissions, updatePermissions, refreshPermissions } = usePermissions();
  const [sectors, setSectors] = useState([]);
  const [localPermissions, setLocalPermissions] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      fetchSectors();
      setLocalPermissions(JSON.parse(JSON.stringify(permissions)));
    }
  }, [open, permissions]);

  const fetchSectors = async () => {
    setLoading(true);
    try {
      // Trying to fetch from the endpoint I know exists, handling potential auth issues or errors gracefully
      const response = await fetch('/api/v2/usuarios-setores/setor');
      if (response.ok) {
        const data = await response.json();
        if (data.setores) {
            setSectors(data.setores);
        }
      } else {
        // Fallback: use sectors present in current permissions
        const knownSectors = new Set([
            ...Object.keys(permissions.fields || {}),
            ...Object.keys(permissions.actions || {})
        ]);
        setSectors(Array.from(knownSectors).map(name => ({ nome: name })));
      }
    } catch (e) {
      console.error("Error fetching sectors", e);
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
    const success = await updatePermissions(localPermissions);
    if (success) {
      toast.success('Permissões atualizadas!');
      onOpenChange(false);
    } else {
      toast.error('Erro ao salvar permissões.');
    }
    setSaving(false);
  };

  if (!localPermissions) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Configuração de Permissões - Dashboard de Demanda</DialogTitle>
          <DialogDescription>
            Defina quais setores podem visualizar/editar campos e executar ações.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
            <div className="flex justify-center py-8"><Loader2 className="h-8 w-8 animate-spin" /></div>
        ) : (
            <Tabs defaultValue="fields" className="w-full">
            <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="fields">Campos Editáveis</TabsTrigger>
                <TabsTrigger value="actions">Ações Permitidas</TabsTrigger>
            </TabsList>

            <TabsContent value="fields" className="mt-4">
                <div className="border rounded-md">
                <Table>
                    <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">Setor</TableHead>
                        {AVAILABLE_FIELDS.map(field => (
                        <TableHead key={field.id} className="text-center text-xs px-1">{field.label}</TableHead>
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

            <TabsContent value="actions" className="mt-4">
                <div className="border rounded-md">
                <Table>
                    <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">Setor</TableHead>
                        {AVAILABLE_ACTIONS.map(action => (
                        <TableHead key={action.id} className="text-center text-xs px-1">{action.label}</TableHead>
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
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancelar</Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? 'Salvando...' : 'Salvar Alterações'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
