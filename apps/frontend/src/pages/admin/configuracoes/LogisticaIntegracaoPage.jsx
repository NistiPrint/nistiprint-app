import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import { Trash2 } from 'lucide-react';
import * as integracaoCanalService from '@/services/integracaoCanalService';
import PontoColetaService from '@/services/PontoColetaService';
import LogisticaIntegracaoService from '@/services/LogisticaIntegracaoService';

const defaultForm = {
  marketplace_integration_id: '',
  modalidade: 'STANDARD',
  tipo_envio: 'COLETA_LOCAL',
  horario_limite: '',
  ponto_coleta_id: 'none',
  dias_semana: [1, 2, 3, 4, 5],
  ativo: true,
  prioridade_uso: 100,
  descricao: ''
};

const diasLabel = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sab'];

export default function LogisticaIntegracaoPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [regras, setRegras] = useState([]);
  const [integracoes, setIntegracoes] = useState([]);
  const [pontos, setPontos] = useState([]);
  const [selectedIntegration, setSelectedIntegration] = useState('all');
  const [form, setForm] = useState(defaultForm);

  const marketplaceIntegrations = useMemo(
    () => integracoes.filter((i) => i.module_id !== 'bling' && i.is_active !== false),
    [integracoes]
  );

  async function carregarDados() {
    setLoading(true);
    try {
      const [ints, pontosData] = await Promise.all([
        integracaoCanalService.listarIntegracoes(),
        PontoColetaService.getAll(true)
      ]);
      setIntegracoes(ints || []);
      setPontos(pontosData || []);
    } catch (e) {
      toast.error('Falha ao carregar integrações e pontos de coleta');
    } finally {
      setLoading(false);
    }
  }

  async function carregarRegras(integrationId = selectedIntegration) {
    try {
      const regrasData = await LogisticaIntegracaoService.listarRegras(
        integrationId === 'all' ? null : Number(integrationId)
      );
      setRegras(regrasData || []);
    } catch (e) {
      toast.error('Falha ao carregar regras logísticas');
    }
  }

  useEffect(() => {
    carregarDados();
  }, []);

  useEffect(() => {
    carregarRegras(selectedIntegration);
  }, [selectedIntegration]);

  const onDiaToggle = (dia) => {
    const exists = form.dias_semana.includes(dia);
    setForm((prev) => ({
      ...prev,
      dias_semana: exists
        ? prev.dias_semana.filter((d) => d !== dia)
        : [...prev.dias_semana, dia].sort((a, b) => a - b)
    }));
  };

  const onSubmit = async () => {
    if (!form.marketplace_integration_id || !form.horario_limite) {
      toast.error('Integração e horário limite são obrigatórios');
      return;
    }

    setSaving(true);
    try {
      await LogisticaIntegracaoService.criarRegra({
        ...form,
        marketplace_integration_id: Number(form.marketplace_integration_id),
        ponto_coleta_id: form.ponto_coleta_id === 'none' ? null : Number(form.ponto_coleta_id)
      });
      toast.success('Regra logística criada');
      setForm(defaultForm);
      await carregarRegras(selectedIntegration);
    } catch (e) {
      toast.error('Erro ao criar regra logística');
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async (id) => {
    if (!window.confirm('Remover esta regra logística?')) return;
    try {
      await LogisticaIntegracaoService.removerRegra(id);
      toast.success('Regra removida');
      await carregarRegras(selectedIntegration);
    } catch (e) {
      toast.error('Erro ao remover regra');
    }
  };

  if (loading) return <div className="text-center py-8">Carregando logística por integração...</div>;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Logística por Integração</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div className="space-y-2">
              <Label>Integração marketplace</Label>
              <Select value={form.marketplace_integration_id} onValueChange={(v) => setForm((p) => ({ ...p, marketplace_integration_id: v }))}>
                <SelectTrigger><SelectValue placeholder="Selecione" /></SelectTrigger>
                <SelectContent>
                  {marketplaceIntegrations.map((i) => (
                    <SelectItem key={i.id} value={String(i.id)}>{i.instance_name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Modalidade</Label>
              <Select value={form.modalidade} onValueChange={(v) => setForm((p) => ({ ...p, modalidade: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="STANDARD">STANDARD</SelectItem>
                  <SelectItem value="FLEX">FLEX</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Tipo de envio</Label>
              <Select value={form.tipo_envio} onValueChange={(v) => setForm((p) => ({ ...p, tipo_envio: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="COLETA_LOCAL">COLETA_LOCAL</SelectItem>
                  <SelectItem value="PONTO_COLETA">PONTO_COLETA</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Horário limite</Label>
              <Input type="time" value={form.horario_limite} onChange={(e) => setForm((p) => ({ ...p, horario_limite: e.target.value }))} />
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="space-y-2">
              <Label>Ponto de coleta</Label>
              <Select value={form.ponto_coleta_id} onValueChange={(v) => setForm((p) => ({ ...p, ponto_coleta_id: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Sem ponto</SelectItem>
                  {pontos.map((p) => (
                    <SelectItem key={p.id} value={String(p.id)}>{p.nome}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Prioridade de uso</Label>
              <Input
                type="number"
                value={form.prioridade_uso}
                onChange={(e) => setForm((p) => ({ ...p, prioridade_uso: Number(e.target.value || 100) }))}
              />
            </div>
            <div className="space-y-2">
              <Label>Descrição</Label>
              <Input value={form.descricao} onChange={(e) => setForm((p) => ({ ...p, descricao: e.target.value }))} />
            </div>
          </div>

          <div className="space-y-2">
            <Label>Dias de atendimento</Label>
            <div className="flex flex-wrap gap-3">
              {diasLabel.map((dia, idx) => (
                <label key={dia} className="flex items-center gap-2 text-sm">
                  <Checkbox checked={form.dias_semana.includes(idx)} onCheckedChange={() => onDiaToggle(idx)} />
                  {dia}
                </label>
              ))}
            </div>
          </div>

          <div className="flex items-center justify-between">
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={form.ativo} onCheckedChange={(v) => setForm((p) => ({ ...p, ativo: !!v }))} />
              Ativa
            </label>
            <Button onClick={onSubmit} disabled={saving}>{saving ? 'Salvando...' : 'Adicionar Regra'}</Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Regras Cadastradas</CardTitle>
          <Select value={selectedIntegration} onValueChange={setSelectedIntegration}>
            <SelectTrigger className="w-72"><SelectValue placeholder="Filtrar integração" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todas as integrações</SelectItem>
              {marketplaceIntegrations.map((i) => (
                <SelectItem key={i.id} value={String(i.id)}>{i.instance_name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Integração</TableHead>
                <TableHead>Modalidade</TableHead>
                <TableHead>Janela</TableHead>
                <TableHead>Dias</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Ação</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {regras.map((r) => (
                <TableRow key={r.id}>
                  <TableCell>{r.installed_integrations?.instance_name || `#${r.marketplace_integration_id}`}</TableCell>
                  <TableCell>{r.modalidade}</TableCell>
                  <TableCell>{r.tipo_envio} até {r.horario_limite?.slice(0, 5)} {r.pontos_coleta?.nome ? `(${r.pontos_coleta.nome})` : ''}</TableCell>
                  <TableCell>{(r.dias_semana || []).map((d) => diasLabel[d]).join(', ')}</TableCell>
                  <TableCell>{r.ativo ? <Badge className="bg-green-600 text-white">Ativa</Badge> : <Badge variant="secondary">Inativa</Badge>}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="icon" onClick={() => onDelete(r.id)}>
                      <Trash2 className="w-4 h-4 text-red-600" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {regras.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground py-6">
                    Nenhuma regra logística cadastrada para o filtro selecionado.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
