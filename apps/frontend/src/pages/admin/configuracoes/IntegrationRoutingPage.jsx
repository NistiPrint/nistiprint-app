import React, { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { PlusCircle, Trash2, ShieldCheck, MapPin, Globe, Store } from 'lucide-react';
import { toast } from 'sonner';

function IntegrationRoutingPage() {
  const [data, setData] = useState({
    routing: [],
    accounts: [],
    channels: [],
    platforms: [],
    functions: []
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [newRule, setNewRule] = useState({
    function_name: 'ORDER_IMPORT',
    scope_type: 'GLOBAL',
    scope_id: '',
    account_id: ''
  });

  const fetchData = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/v2/integracoes/routing');
      if (!response.ok) throw new Error('Erro ao carregar dados de roteamento');
      const result = await response.json();
      setData(result);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleSaveRule = async () => {
    if (!newRule.account_id) {
      toast.error('Selecione uma conta de destino');
      return;
    }
    if (newRule.scope_type !== 'GLOBAL' && !newRule.scope_id) {
      toast.error('Selecione o alvo do escopo (Plataforma ou Canal)');
      return;
    }

    setSaving(true);
    try {
      const response = await fetch('/api/v2/integracoes/routing', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newRule)
      });

      if (!response.ok) throw new Error('Erro ao salvar regra');
      
      toast.success('Regra de roteamento salva com sucesso!');
      fetchData();
      setNewRule({ ...newRule, scope_id: '', account_id: '' });
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteRule = async (id) => {
    if (!confirm('Deseja remover esta regra de roteamento?')) return;

    try {
      const response = await fetch(`/api/v2/integracoes/routing/${id}`, {
        method: 'DELETE'
      });
      if (!response.ok) throw new Error('Erro ao remover regra');
      toast.success('Regra removida');
      fetchData();
    } catch (e) {
      toast.error(e.message);
    }
  };

  const getAccountName = (id) => {
    const acc = data.accounts.find(a => String(a.id) === String(id));
    return acc ? acc.instance_name : id;
  };

  const getScopeName = (type, id) => {
    if (type === 'GLOBAL') return 'Todas as operações';
    if (type === 'PLATFORM') {
      return data.platforms.find(p => p.nome === id)?.nome || id;
    }
    if (type === 'CHANNEL') {
      return data.channels.find(c => String(c.id) === String(id))?.nome || id;
    }
    return id;
  };

  const getFunctionName = (id) => {
    return data.functions.find(f => f.id === id)?.name || id;
  };

  if (loading) return <div className="p-8 text-center text-muted-foreground font-medium animate-pulse">Carregando configurações de roteamento...</div>;

  return (
    <div className="container mx-auto py-8 space-y-8 max-w-6xl">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-tight">Roteamento de Integrações</h1>
        <p className="text-muted-foreground">Defina qual conta ERP (Bling) deve ser usada para cada operação e canal.</p>
      </div>

      <Card className="border-primary/20 shadow-md">
        <CardHeader className="bg-primary/5">
          <CardTitle className="text-lg flex items-center gap-2">
            <PlusCircle className="h-5 w-5 text-primary" /> Nova Regra de Roteamento
          </CardTitle>
          <CardDescription>Configure um novo mapeamento de função para uma conta específica.</CardDescription>
        </CardHeader>
        <CardContent className="pt-6">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-6 items-end">
            <div className="space-y-2">
              <Label>Função</Label>
              <Select 
                value={newRule.function_name} 
                onValueChange={(val) => setNewRule({...newRule, function_name: val})}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {data.functions.map(f => (
                    <SelectItem key={f.id} value={f.id}>{f.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Escopo</Label>
              <Select 
                value={newRule.scope_type} 
                onValueChange={(val) => setNewRule({...newRule, scope_type: val, scope_id: ''})}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="GLOBAL">Global (Padrão)</SelectItem>
                  <SelectItem value="PLATFORM">Por Plataforma</SelectItem>
                  <SelectItem value="CHANNEL">Por Canal de Venda</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {newRule.scope_type !== 'GLOBAL' && (
              <div className="space-y-2">
                <Label>{newRule.scope_type === 'PLATFORM' ? 'Selecionar Plataforma' : 'Selecionar Canal'}</Label>
                <Select 
                  value={newRule.scope_id} 
                  onValueChange={(val) => setNewRule({...newRule, scope_id: val})}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Selecione..." />
                  </SelectTrigger>
                  <SelectContent>
                    {newRule.scope_type === 'PLATFORM' ? 
                      data.platforms.map(p => <SelectItem key={p.id} value={p.nome}>{p.nome}</SelectItem>) :
                      data.channels.map(c => <SelectItem key={c.id} value={String(c.id)}>{c.nome}</SelectItem>)
                    }
                  </SelectContent>
                </Select>
              </div>
            )}

            <div className="space-y-2">
              <Label>Conta Bling Destino</Label>
              <Select 
                value={newRule.account_id} 
                onValueChange={(val) => setNewRule({...newRule, account_id: val})}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Selecione a conta..." />
                </SelectTrigger>
                <SelectContent>
                  {data.accounts.map(acc => (
                    <SelectItem key={acc.id} value={String(acc.id)}>{acc.instance_name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="md:col-start-4">
              <Button 
                onClick={handleSaveRule} 
                disabled={saving} 
                className="w-full shadow-sm"
              >
                {saving ? 'Salvando...' : 'Adicionar Regra'}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="text-xl flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-muted-foreground" /> Regras Ativas
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border overflow-hidden">
            <Table>
              <TableHeader className="bg-muted/50">
                <TableRow>
                  <TableHead className="w-[250px]">Função</TableHead>
                  <TableHead>Escopo</TableHead>
                  <TableHead>Alvo</TableHead>
                  <TableHead>Conta Destino</TableHead>
                  <TableHead className="text-right w-[100px]">Ações</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.routing.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="h-32 text-center text-muted-foreground">
                      Nenhuma regra de roteamento configurada. O sistema usará os fallbacks padrões.
                    </TableCell>
                  </TableRow>
                ) : (
                  data.routing.map((rule) => (
                    <TableRow key={rule.id} className="hover:bg-muted/30 transition-colors">
                      <TableCell className="font-medium">
                        {getFunctionName(rule.function_name)}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          {rule.scope_type === 'GLOBAL' && <Globe className="h-4 w-4 text-blue-500" />}
                          {rule.scope_type === 'PLATFORM' && <MapPin className="h-4 w-4 text-orange-500" />}
                          {rule.scope_type === 'CHANNEL' && <Store className="h-4 w-4 text-green-500" />}
                          <span className="capitalize">{rule.scope_type.toLowerCase()}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <span className="px-2 py-1 bg-secondary text-secondary-foreground rounded text-xs font-semibold">
                          {getScopeName(rule.scope_type, rule.scope_id)}
                        </span>
                      </TableCell>
                      <TableCell className="font-semibold text-primary">
                        {getAccountName(rule.account_id)}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button 
                          variant="ghost" 
                          size="icon" 
                          onClick={() => handleDeleteRule(rule.id)}
                          className="hover:text-destructive hover:bg-destructive/10"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
      
      <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg text-amber-800 text-sm">
        <strong>Nota Importante:</strong> O roteamento por Canal tem prioridade sobre o de Plataforma, que tem prioridade sobre o Global. 
        Se nenhuma regra for encontrada, o sistema tentará usar as configurações legadas do arquivo <code>constants.py</code>.
      </div>
    </div>
  );
}

export default IntegrationRoutingPage;
