import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
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
  modalidade_id: '',
  tipo_envio: 'COLETA_LOCAL',
  horario_corte: '',
  horario_coleta: '',
  offset_etiqueta_min: 40,
  offset_coleta_min: 60,
  ponto_coleta_id: 'none',
  dias_semana: [1, 2, 3, 4, 5],
  ativo: true,
  prioridade_uso: 100,
  descricao: '',
  // Canais extras que saem nesta mesma janela. A modalidade principal nao entra
  // aqui: ela ja e o dono da janela e nunca pode ser desmarcada.
  canais_extras: []
};

const diasLabel = { 1: 'Seg', 2: 'Ter', 3: 'Qua', 4: 'Qui', 5: 'Sex', 6: 'Sab', 7: 'Dom' };

const NAO_ASSOCIADO = 'none';

export default function LogisticaIntegracaoPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [regras, setRegras] = useState([]);
  const [canais, setCanais] = useState([]);
  const [modalidadesForm, setModalidadesForm] = useState([]);
  const [modalidadesFiltro, setModalidadesFiltro] = useState([]);
  const [integracoes, setIntegracoes] = useState([]);
  const [pontos, setPontos] = useState([]);
  const [selectedIntegration, setSelectedIntegration] = useState('all');
  const [form, setForm] = useState(defaultForm);

  const marketplaceIntegrations = useMemo(
    () =>
      integracoes
        .filter((i) => i.module_id !== 'bling' && i.is_active !== false)
        .map((i) => ({
          ...i,
          optionLabel: `${i.instance_name || i.module_id} (#${i.id}) · ${i.module_id}`
        })),
    [integracoes]
  );

  const integracaoSelecionada = useMemo(
    () => marketplaceIntegrations.find((i) => String(i.id) === String(selectedIntegration)),
    [marketplaceIntegrations, selectedIntegration]
  );

  // A forma do formulário segue o tipo de prazo da modalidade: hora de parede
  // para FIXO, minutos após a venda para RELATIVO. Turbo não tem "13:00" —
  // tem "40 minutos depois que o cliente comprou".
  const modalidadeSelecionada = useMemo(
    () => modalidadesForm.find((m) => String(m.id) === String(form.modalidade_id)),
    [modalidadesForm, form.modalidade_id]
  );
  const isPonto = form.tipo_envio === 'PONTO_COLETA';
  // A hora vem do cadastro do ponto; a janela só guarda exceção.
  const horaFechamentoDoPonto = (
    pontos.find((pt) => String(pt.id) === String(form.ponto_coleta_id))?.horario_fechamento || ''
  ).slice(0, 5);
  const isRelativo = modalidadeSelecionada?.tipo_prazo === 'RELATIVO';

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

  const carregarPorIntegracao = useCallback(async (integrationId) => {
    const id = integrationId === 'all' ? null : Number(integrationId);
    try {
      const [regrasData, canaisData, modalidadesData] = await Promise.all([
        LogisticaIntegracaoService.listarRegras(id),
        LogisticaIntegracaoService.listarCanais(id),
        LogisticaIntegracaoService.listarModalidades(id)
      ]);
      setRegras(regrasData || []);
      setCanais(canaisData || []);
      setModalidadesFiltro(modalidadesData || []);
    } catch (e) {
      toast.error('Falha ao carregar logística da integração');
    }
  }, []);

  useEffect(() => {
    carregarDados();
  }, []);

  useEffect(() => {
    carregarPorIntegracao(selectedIntegration);
  }, [selectedIntegration, carregarPorIntegracao]);

  // As modalidades do formulário seguem a integração escolhida NO formulário,
  // não a do filtro: são seletores independentes.
  useEffect(() => {
    if (!form.marketplace_integration_id) {
      setModalidadesForm([]);
      return;
    }
    LogisticaIntegracaoService.listarModalidades(Number(form.marketplace_integration_id))
      .then((data) => setModalidadesForm(data || []))
      .catch(() => setModalidadesForm([]));
  }, [form.marketplace_integration_id]);

  const onDiaToggle = (dia) => {
    const exists = form.dias_semana.includes(dia);
    setForm((prev) => ({
      ...prev,
      dias_semana: exists
        ? prev.dias_semana.filter((d) => d !== dia)
        : [...prev.dias_semana, dia].sort((a, b) => a - b)
    }));
  };

  const onAssociarCanal = async (canal, modalidadeId) => {
    try {
      const res = await LogisticaIntegracaoService.associarCanal({
        moduleId: canal.module_id,
        chave: canal.chave,
        modalidadeId: modalidadeId === NAO_ASSOCIADO ? null : Number(modalidadeId),
        campoOrigem: canal.campo_origem
      });
      const n = res?.pedidos_reclassificados ?? 0;
      toast.success(
        modalidadeId === NAO_ASSOCIADO
          ? `Canal desassociado · ${n} pedido(s) voltaram para não classificada`
          : `Canal associado · ${n} pedido(s) reclassificados`
      );
      await carregarPorIntegracao(selectedIntegration);
    } catch (e) {
      toast.error('Erro ao associar canal de envio');
    }
  };

  const onSubmit = async () => {
    if (!form.marketplace_integration_id || !form.modalidade_id) {
      toast.error('Integração e modalidade são obrigatórias');
      return;
    }
    if (isRelativo) {
      const etiqueta = Number(form.offset_etiqueta_min);
      const coleta = Number(form.offset_coleta_min);
      if (!etiqueta || !coleta) {
        toast.error('Informe os prazos de etiqueta e de coleta em minutos');
        return;
      }
      if (coleta < etiqueta) {
        toast.error('A coleta não pode vir antes da etiqueta');
        return;
      }
    } else {
      if (!form.horario_corte || (!form.horario_coleta && !isPonto)) {
        toast.error('Hora de corte e hora de coleta são obrigatórias');
        return;
      }
      if (form.horario_coleta && form.horario_coleta < form.horario_corte) {
        toast.error('Hora de coleta/entrega precisa ser maior ou igual à hora de corte');
        return;
      }
    }

    setSaving(true);
    try {
      const base = {
        marketplace_integration_id: Number(form.marketplace_integration_id),
        modalidade_id: Number(form.modalidade_id),
        tipo_envio: form.tipo_envio,
        ativo: form.ativo,
        prioridade_uso: form.prioridade_uso,
        descricao: form.descricao,
        ponto_coleta_id: form.ponto_coleta_id === 'none' ? null : Number(form.ponto_coleta_id)
      };
      await LogisticaIntegracaoService.criarRegra(
        isRelativo
          ? {
              ...base,
              offset_etiqueta_min: Number(form.offset_etiqueta_min),
              offset_coleta_min: Number(form.offset_coleta_min)
            }
          : {
              ...base,
              dias_semana: form.dias_semana,
              horario_corte: form.horario_corte,
              horario_coleta: form.horario_coleta || null,
              horario_limite: form.horario_coleta || null,
              modalidade_ids: [Number(form.modalidade_id), ...form.canais_extras.map(Number)]
            }
      );
      toast.success('Janela de coleta criada');
      setForm(defaultForm);
      await carregarPorIntegracao(selectedIntegration);
    } catch (e) {
      toast.error(e?.response?.data?.error || 'Erro ao criar janela de coleta');
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async (id) => {
    if (!window.confirm('Remover esta janela de coleta?')) return;
    try {
      await LogisticaIntegracaoService.removerRegra(id);
      toast.success('Janela removida');
      await carregarPorIntegracao(selectedIntegration);
    } catch (e) {
      toast.error('Erro ao remover janela');
    }
  };

  if (loading) return <div className="text-center py-8">Carregando logística por integração...</div>;

  const naoAssociados = canais.filter((c) => !c.modalidade_id);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>Canais de envio</CardTitle>
            <CardDescription>
              Canais que a origem realmente usou nos pedidos já importados, não um catálogo fixo.
              Canal novo aparece aqui sozinho. Associe cada um a uma modalidade para os pedidos
              serem agrupados na torre de despacho.
            </CardDescription>
          </div>
          <Select value={selectedIntegration} onValueChange={setSelectedIntegration}>
            <SelectTrigger className="w-72 shrink-0"><SelectValue placeholder="Filtrar integração" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todas as integrações</SelectItem>
              {marketplaceIntegrations.map((i) => (
                <SelectItem key={i.id} value={String(i.id)}>{i.optionLabel}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardHeader>
        <CardContent>
          {naoAssociados.length > 0 && (
            <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              {naoAssociados.length} canal(is) sem modalidade. Os pedidos deles ficam em
              “Modalidade não classificada”, com prioridade máxima, até serem associados.
            </div>
          )}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Canal</TableHead>
                <TableHead>Identificador</TableHead>
                <TableHead className="text-right">Pedidos</TableHead>
                <TableHead className="text-right">Pendentes</TableHead>
                <TableHead className="w-64">Modalidade</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {canais.map((c) => (
                <TableRow key={`${c.module_id}-${c.chave}`} className={!c.modalidade_id ? 'bg-amber-50/50' : undefined}>
                  <TableCell className="font-medium">
                    {c.rotulo || <span className="text-muted-foreground">sem rótulo</span>}
                    <div className="text-xs text-muted-foreground">{c.module_id}</div>
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {c.chave}
                    <div className="text-muted-foreground">{c.campo_origem}</div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{c.ocorrencias}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {c.pedidos_pendentes > 0
                      ? <span className="font-medium">{c.pedidos_pendentes}</span>
                      : <span className="text-muted-foreground">0</span>}
                  </TableCell>
                  <TableCell>
                    <Select
                      value={c.modalidade_id ? String(c.modalidade_id) : NAO_ASSOCIADO}
                      onValueChange={(v) => onAssociarCanal(c, v)}
                    >
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value={NAO_ASSOCIADO}>Não classificada</SelectItem>
                        {modalidadesFiltro
                          .filter((m) => m.module_id === c.module_id)
                          .map((m) => (
                            <SelectItem key={m.id} value={String(m.id)}>
                              {m.nome}{m.entra_na_torre === false ? ' · fora da torre' : ''}
                            </SelectItem>
                          ))}
                      </SelectContent>
                    </Select>
                  </TableCell>
                </TableRow>
              ))}
              {canais.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground py-6">
                    Nenhum canal de envio observado ainda. Eles aparecem conforme os pedidos são importados.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Janela de coleta por modalidade</CardTitle>
          <CardDescription>
            Corte e coleta de cada modalidade nesta conta. O corte define o compromisso
            logístico, que é a ordem de toda a fila de produção.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div className="space-y-2">
              <Label>Integração instalada</Label>
              <Select
                value={form.marketplace_integration_id}
                onValueChange={(v) => setForm((p) => ({ ...p, marketplace_integration_id: v, modalidade_id: '' }))}
              >
                <SelectTrigger><SelectValue placeholder="Selecione" /></SelectTrigger>
                <SelectContent>
                  {marketplaceIntegrations.map((i) => (
                    <SelectItem key={i.id} value={String(i.id)}>{i.optionLabel}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Modalidade</Label>
              <Select
                value={form.modalidade_id}
                onValueChange={(v) => setForm((p) => ({ ...p, modalidade_id: v }))}
                disabled={!form.marketplace_integration_id}
              >
                <SelectTrigger>
                  <SelectValue placeholder={form.marketplace_integration_id ? 'Selecione' : 'Escolha a integração'} />
                </SelectTrigger>
                <SelectContent>
                  {modalidadesForm.map((m) => (
                    <SelectItem key={m.id} value={String(m.id)}>{m.nome}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Tipo de envio</Label>
              <Select value={form.tipo_envio} onValueChange={(v) => setForm((p) => ({ ...p, tipo_envio: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="COLETA_LOCAL">Coleta local</SelectItem>
                  <SelectItem value="PONTO_COLETA">Ponto de coleta</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{isRelativo ? 'Etiqueta (min após a venda)' : 'Hora de corte'}</Label>
              {isRelativo ? (
                <Input
                  type="number"
                  min={1}
                  value={form.offset_etiqueta_min}
                  onChange={(e) => setForm((p) => ({ ...p, offset_etiqueta_min: e.target.value }))}
                />
              ) : (
                <Input type="time" value={form.horario_corte} onChange={(e) => setForm((p) => ({ ...p, horario_corte: e.target.value }))} />
              )}
            </div>
          </div>

          {isRelativo && (
            <p className="text-sm text-muted-foreground">
              Prazo relativo: o relógio de cada pedido começa na hora da venda, não em um
              horário fixo do dia. Por isso não há dias de atendimento — um Turbo que cai
              no sábado tem o mesmo prazo de um que cai na terça.
            </p>
          )}

          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div className="space-y-2">
              <Label>
                {isRelativo
                  ? 'Coleta (min após a venda)'
                  : isPonto
                    ? 'Hora de entrega no ponto'
                    : 'Hora da coleta'}
              </Label>
              {isRelativo ? (
                <Input
                  type="number"
                  min={1}
                  value={form.offset_coleta_min}
                  onChange={(e) => setForm((p) => ({ ...p, offset_coleta_min: e.target.value }))}
                />
              ) : (
                <Input
                  type="time"
                  value={form.horario_coleta}
                  placeholder={isPonto ? horaFechamentoDoPonto || '' : ''}
                  onChange={(e) => setForm((p) => ({ ...p, horario_coleta: e.target.value }))}
                />
              )}
              {/* O ponto de coleta não tem hora de corte: tem uma hora em que
                  fecha, e é ela que é o prazo de entrega. Repetir esse horário
                  em cada janela é a forma mais comum de os dois divergirem. */}
              {isPonto && !isRelativo && (
                <p className="text-xs text-muted-foreground">
                  {horaFechamentoDoPonto
                    ? `Em branco usa o fechamento do ponto (${horaFechamentoDoPonto}). Preencha só como exceção.`
                    : 'Escolha um ponto com hora de fechamento cadastrada, ou informe a hora aqui.'}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label>{isPonto ? 'Ponto de coleta (obrigatório)' : 'Ponto de coleta'}</Label>
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

          {/* Canais que compartilham esta janela.
              Shopee Xpress e Retirada pelo Comprador saem no mesmo caminhão. Sem
              este campo, a única forma de juntá-los era classificar um como o
              outro — foi o que aconteceu com o canal 90024, e a classificação
              errada sobreviveu meses porque nada acusava. */}
          {!isRelativo && (
            <div className="space-y-2">
              <Label>Outros canais que saem nesta mesma janela</Label>
              <div className="flex flex-wrap gap-2">
                {modalidadesForm
                  .filter((m) => String(m.id) !== String(form.modalidade_id) && m.tipo_prazo !== 'RELATIVO')
                  .map((m) => {
                    const marcado = form.canais_extras.includes(m.id);
                    return (
                      <button
                        key={m.id}
                        type="button"
                        onClick={() =>
                          setForm((p) => ({
                            ...p,
                            canais_extras: marcado
                              ? p.canais_extras.filter((id) => id !== m.id)
                              : [...p.canais_extras, m.id],
                          }))
                        }
                        className={
                          'rounded-full border px-3 py-1 text-xs transition-colors ' +
                          (marcado
                            ? 'border-primary bg-primary/10 text-primary'
                            : 'border-border text-muted-foreground hover:border-primary/40')
                        }
                      >
                        {marcado ? '✓ ' : '+ '}{m.nome}
                      </button>
                    );
                  })}
                {modalidadesForm.filter((m) => String(m.id) !== String(form.modalidade_id) && m.tipo_prazo !== 'RELATIVO').length === 0 && (
                  <span className="text-xs text-muted-foreground">
                    Nenhum outro canal de prazo fixo cadastrado neste marketplace.
                  </span>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                Os canais marcados entram no mesmo lote: mesmo corte, mesma coleta e
                uma demanda só. Na torre eles aparecem como um card.
              </p>
            </div>
          )}

          {!isRelativo && (
            <div className="space-y-2">
              <Label>Dias de atendimento</Label>
              <div className="flex flex-wrap gap-3">
                {Object.entries(diasLabel).map(([idx, dia]) => (
                  <label key={dia} className="flex items-center gap-2 text-sm">
                    <Checkbox checked={form.dias_semana.includes(Number(idx))} onCheckedChange={() => onDiaToggle(Number(idx))} />
                    {dia}
                  </label>
                ))}
              </div>
            </div>
          )}

          <div className="flex items-center justify-between">
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={form.ativo} onCheckedChange={(v) => setForm((p) => ({ ...p, ativo: !!v }))} />
              Ativa
            </label>
            <Button onClick={onSubmit} disabled={saving}>{saving ? 'Salvando...' : 'Adicionar janela'}</Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            Janelas cadastradas
            {integracaoSelecionada ? ` · ${integracaoSelecionada.instance_name || integracaoSelecionada.module_id}` : ''}
          </CardTitle>
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
                  <TableCell>
                    {r.modalidades_logisticas?.nome || (
                      <span className="text-amber-700">sem modalidade</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {r.offset_etiqueta_min != null ? (
                      <>
                        Etiqueta +{r.offset_etiqueta_min}min · Coleta +{r.offset_coleta_min}min
                        <div className="text-xs text-muted-foreground">a partir da venda</div>
                      </>
                    ) : (
                      <>
                        Corte {r.horario_corte?.slice(0, 5) || '--:--'} · Coleta{' '}
                        {r.horario_coleta?.slice(0, 5) || r.horario_limite?.slice(0, 5)}
                        {r.coleta_dia_offset > 0 ? ' (D+1)' : ''}
                        {r.pontos_coleta?.nome ? ` (${r.pontos_coleta.nome})` : ''}
                      </>
                    )}
                  </TableCell>
                  <TableCell>
                    {r.offset_etiqueta_min != null
                      ? <span className="text-muted-foreground">todos</span>
                      : (r.dias_semana || []).map((d) => diasLabel[d]).filter(Boolean).join(', ')}
                  </TableCell>
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
                    Nenhuma janela de coleta cadastrada para o filtro selecionado.
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
