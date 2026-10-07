import { createElement, useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import PageHeader from '@/components/ui/PageHeader';
import S from '@/services/LogisticaIntegracaoService';
import { listarIntegracoes } from '@/services/integracaoCanalService';

const control = 'h-9 w-full rounded-md border bg-background px-3 text-sm';
const errorText = (e) => e?.response?.data?.error || 'Não foi possível salvar';
const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Sao_Paulo' }).format(new Date());
const fmt = (v) => v ? new Intl.DateTimeFormat('pt-BR', { timeZone: 'America/Sao_Paulo', dateStyle: 'short', timeStyle: 'short' }).format(new Date(v)) : '—';
function Field({ label, children }) { return <label className="flex flex-col gap-2 text-sm">{label}{children}</label>; }
function Check({ label, checked, onChange }) { return <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!checked} onChange={(e) => onChange(e.target.checked)} />{label}</label>; }

export default function LogisticaManutencao({ Janelas, integrationId: forcedIntegrationId = null, marketplaceModuleId = null, mode = 'all' }) {
  const [integracoes, setIntegracoes] = useState([]);
  const [integrationId, setIntegrationId] = useState(forcedIntegrationId ? String(forcedIntegrationId) : 'all');
  const [versao, setVersao] = useState(0);
  const [modalidades, setModalidades] = useState([]);
  useEffect(() => { listarIntegracoes().then((data) => setIntegracoes((data || []).filter((i) => i.module_id !== 'bling'))).catch(() => toast.error('Falha ao carregar contas')); }, []);
  useEffect(() => {
    let live = true;
    S.listarModalidades(integrationId === 'all' ? null : Number(integrationId), true)
      .then((data) => { if (live) setModalidades(data); }).catch(() => toast.error('Falha ao carregar modalidades'));
    return () => { live = false; };
  }, [integrationId, versao]);
  const conta = integracoes.find((i) => String(i.id) === integrationId);
  const modules = [...new Set([...(marketplaceModuleId ? [marketplaceModuleId] : []), ...integracoes.map((i) => i.module_id)])];
  const reload = () => setVersao((v) => v + 1);
  const showLogistics = mode !== 'despacho';
  const showDispatch = mode !== 'logistica';
  return <div className="space-y-6">
    {mode === 'all' && <PageHeader title="Logística dos marketplaces" description="Mantenha modalidades, identificadores e horários. O prazo oficial de cada pedido é acompanhado separadamente." />}
    {forcedIntegrationId ? (
      <div className="rounded-lg border bg-muted/20 px-4 py-3 text-sm">
        Configuração para <strong>{conta?.instance_name || `Conta ${forcedIntegrationId}`}</strong> · {conta?.module_id || 'marketplace'}
      </div>
    ) : (
      <Field label="Conta"><select className={`${control} max-w-lg`} value={integrationId} onChange={(e) => setIntegrationId(e.target.value)}>
        <option value="all">Todas as contas</option>{integracoes.map((i) => <option key={i.id} value={i.id}>{i.instance_name || i.module_id} · {i.module_id}</option>)}
      </select></Field>
    )}
    <Tabs defaultValue={showLogistics ? 'modalidades' : 'agenda'}>
      <TabsList>
        {showLogistics && <><TabsTrigger value="modalidades">Modalidades</TabsTrigger><TabsTrigger value="identificadores">Identificadores de envio</TabsTrigger></>}
        {showDispatch && <><TabsTrigger value="janelas">Janelas de despacho</TabsTrigger><TabsTrigger value="agenda">Agenda e regras</TabsTrigger></>}
      </TabsList>
      {showLogistics && <>
        <TabsContent value="modalidades" className="space-y-4">
          {forcedIntegrationId && <p className="rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-100">Modalidades são compartilhadas entre contas do mesmo marketplace. Alterações aqui também aparecem nas outras contas de {conta?.module_id || 'este marketplace'}.</p>}
          <Modalidades key={integrationId} modalidades={modalidades} modules={conta ? [conta.module_id] : modules} reload={reload} />
        </TabsContent>
        <TabsContent value="identificadores" className="space-y-4">
          {forcedIntegrationId && <p className="rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-100">As associações de identificadores também são compartilhadas entre contas do mesmo marketplace.</p>}
          <Identificadores key={integrationId} integrationId={integrationId} moduleId={conta?.module_id} modules={modules} modalidades={modalidades} />
        </TabsContent>
      </>}
      {showDispatch && <>
        <TabsContent value="janelas">{createElement(Janelas, { key: `${integrationId}-${versao}`, integrationId })}</TabsContent>
        <TabsContent value="agenda"><Agenda key={integrationId} integrationId={integrationId} conta={conta} versao={versao} /></TabsContent>
      </>}
    </Tabs>
  </div>;
}

const emptyModal = { codigo: '', nome: '', tipo_prazo: 'FIXO', politica_lote: 'LOTE', nivel_interrupcao: 0, entra_na_torre: true, entrega_rapida: false, ativo: true, cor: '#2563eb', ordem_exibicao: 100, offset_etiqueta_min: 40, offset_coleta_min: 60 };
function Modalidades({ modalidades, modules, reload }) {
  const [form, setForm] = useState({ ...emptyModal, module_id: modules[0] || '' });
  const [id, setId] = useState(null);
  const [saving, setSaving] = useState(false);
  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  const save = async () => {
    setSaving(true);
    try { await S.salvarModalidade(form, id); toast.success('Modalidade salva'); setId(null); setForm({ ...emptyModal, module_id: form.module_id }); reload(); }
    catch (e) { toast.error(errorText(e)); } finally { setSaving(false); }
  };
  const toggle = async (m) => {
    try { await S.salvarModalidade({ ativo: !m.ativo }, m.id); reload(); } catch (e) { toast.error(errorText(e)); }
  };
  return <div className="space-y-4"><Card><CardHeader><CardTitle>{id ? 'Editar modalidade' : 'Nova modalidade'}</CardTitle></CardHeader><CardContent className="space-y-4">
    <div className="grid gap-3 md:grid-cols-3">
      <Field label="Marketplace"><select className={control} disabled={!!id} value={form.module_id} onChange={(e) => set('module_id', e.target.value)}><option value="">Selecione</option>{modules.map((m) => <option key={m}>{m}</option>)}</select></Field>
      <Field label="Código"><Input disabled={!!id} value={form.codigo} onChange={(e) => set('codigo', e.target.value.toUpperCase())} /></Field>
      <Field label="Nome"><Input value={form.nome} onChange={(e) => set('nome', e.target.value)} /></Field>
      <Field label="Prazo"><select className={control} value={form.tipo_prazo} onChange={(e) => set('tipo_prazo', e.target.value)}><option value="FIXO">Por janela de despacho</option><option value="RELATIVO">Minutos após a venda</option></select></Field>
      <Field label="Agrupamento"><select className={control} value={form.politica_lote} onChange={(e) => set('politica_lote', e.target.value)}><option value="LOTE">Em lote</option><option value="INDIVIDUAL">Individual</option></select></Field>
      <Field label="Prioridade de interrupção (0 = normal)"><Input type="number" min={0} value={form.nivel_interrupcao} onChange={(e) => set('nivel_interrupcao', Number(e.target.value))} /></Field>
      <Field label="Cor"><Input type="color" value={form.cor || '#2563eb'} onChange={(e) => set('cor', e.target.value)} /></Field>
      <Field label="Ordem na tela"><Input type="number" value={form.ordem_exibicao} onChange={(e) => set('ordem_exibicao', Number(e.target.value))} /></Field>
      {form.tipo_prazo === 'RELATIVO' && <>
        <Field label="Etiqueta (min após venda)"><Input type="number" min={1} value={form.offset_etiqueta_min} onChange={(e) => set('offset_etiqueta_min', Number(e.target.value))} /></Field>
        <Field label="Coleta (min após venda)"><Input type="number" min={1} value={form.offset_coleta_min} onChange={(e) => set('offset_coleta_min', Number(e.target.value))} /></Field>
      </>}
    </div>
    <div className="flex flex-wrap gap-5"><Check label="Ativa" checked={form.ativo} onChange={(v) => set('ativo', v)} /><Check label="Participa da torre" checked={form.entra_na_torre} onChange={(v) => set('entra_na_torre', v)} /><Check label="Entrega rápida" checked={form.entrega_rapida} onChange={(v) => set('entrega_rapida', v)} /></div>
    <p className="text-sm text-muted-foreground">Os horários são definidos por conta na aba Agenda e regras. Para mudar o tipo de prazo de uma modalidade utilizada, cadastre outra.</p>
    <div className="flex gap-2"><Button disabled={saving} onClick={save}>{saving ? 'Salvando...' : 'Salvar modalidade'}</Button>{id && <Button variant="outline" onClick={() => { setId(null); setForm({ ...emptyModal, module_id: modules[0] }); }}>Cancelar</Button>}</div>
  </CardContent></Card>
  <div className="overflow-x-auto rounded-md border"><table className="w-full text-sm"><thead><tr className="border-b text-left"><th className="p-3">Modalidade</th><th>Prazo</th><th>Status</th><th className="p-3">Ações</th></tr></thead><tbody>{modalidades.map((m) => <tr key={m.id} className="border-b"><td className="p-3">{m.nome}<div className="text-xs text-muted-foreground">{m.module_id} · {m.codigo}</div></td><td>{m.tipo_prazo === 'RELATIVO' ? 'Após venda' : 'Por janela'}</td><td>{m.ativo ? 'Ativa' : 'Inativa'}</td><td className="space-x-2 p-3"><Button variant="outline" size="sm" onClick={() => { setId(m.id); setForm({ ...emptyModal, ...m }); }}>Editar</Button><Button variant="ghost" size="sm" onClick={() => toggle(m)}>{m.ativo ? 'Desativar' : 'Ativar'}</Button></td></tr>)}{!modalidades.length && <tr><td colSpan={4} className="p-4 text-muted-foreground">Nenhuma modalidade cadastrada.</td></tr>}</tbody></table></div></div>;
}

function Identificadores({ integrationId, moduleId, modules, modalidades }) {
  const [observados, setObservados] = useState([]);
  const [associacoes, setAssociacoes] = useState([]);
  const [form, setForm] = useState({ module_id: moduleId || '', chave: '', modalidade_id: '', service: '', tags: '', associacao_id: null });
  const [saving, setSaving] = useState(false);
  const load = useCallback(async () => {
    const [obs, assocs] = await Promise.all([S.listarCanais(integrationId === 'all' ? null : Number(integrationId)), S.listarAssociacoes(moduleId)]);
    setObservados(obs); setAssociacoes(assocs);
  }, [integrationId, moduleId]);
  useEffect(() => { load().catch(() => toast.error('Falha ao carregar identificadores')); }, [load]);
  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  const save = async () => {
    if (!form.modalidade_id) { toast.error('Selecione uma modalidade'); return; }
    setSaving(true);
    try {
      const condicoes = {};
      if (form.service.trim()) condicoes.service = form.service.trim();
      if (form.tags.trim()) condicoes.tags = form.tags.split(',').map((t) => t.trim()).filter(Boolean);
      const res = await S.associarCanal({ moduleId: form.module_id, chave: form.chave, modalidadeId: Number(form.modalidade_id), condicoes, associacaoId: form.associacao_id });
      toast.success(`Associação salva · ${res.pedidos_reclassificados} pedido(s) reclassificados`);
      setForm({ module_id: moduleId || form.module_id, chave: '', modalidade_id: '', service: '', tags: '', associacao_id: null }); await load();
    } catch (e) { toast.error(errorText(e)); } finally { setSaving(false); }
  };
  const toggle = async (a) => {
    try { await S.associarCanal({ moduleId: a.module_id, chave: a.valor, modalidadeId: a.ativo ? null : a.modalidade_id, associacaoId: a.id, condicoes: a.condicoes }); await load(); } catch (e) { toast.error(errorText(e)); }
  };
  return <div className="space-y-4">
    <p className="text-sm text-muted-foreground">A associação vale para todas as contas do marketplace. Condições de serviço e tags distinguem envios que compartilham o mesmo identificador.</p>
    <Card><CardHeader><CardTitle>{form.associacao_id ? 'Editar associação' : 'Associar identificador'}</CardTitle></CardHeader><CardContent className="space-y-4"><div className="grid gap-3 md:grid-cols-3">
      <Field label="Marketplace"><select className={control} disabled={!!form.associacao_id} value={form.module_id} onChange={(e) => { set('module_id', e.target.value); set('modalidade_id', ''); }}><option value="">Selecione</option>{(moduleId ? [moduleId] : modules).map((m) => <option key={m}>{m}</option>)}</select></Field>
      <Field label="Identificador"><Input value={form.chave} placeholder="Ex.: 91003 ou cross_docking" onChange={(e) => set('chave', e.target.value)} /></Field>
      <Field label="Modalidade"><select className={control} value={form.modalidade_id} onChange={(e) => set('modalidade_id', e.target.value)}><option value="">Selecione</option>{modalidades.filter((m) => m.ativo && m.module_id === form.module_id).map((m) => <option key={m.id} value={m.id}>{m.nome}</option>)}</select></Field>
      <Field label="Serviço do envio (opcional)"><Input value={form.service} placeholder="Ex.: xd_same_day" onChange={(e) => set('service', e.target.value)} /></Field>
      <Field label="Tags exigidas (opcional, separadas por vírgula)"><Input value={form.tags} placeholder="Ex.: proximity" onChange={(e) => set('tags', e.target.value)} /></Field>
    </div><Button disabled={saving} onClick={save}>{saving ? 'Salvando...' : 'Salvar associação'}</Button>{form.associacao_id && <Button variant="ghost" onClick={() => set('associacao_id', null)}>Nova associação</Button>}</CardContent></Card>
    <Card><CardHeader><CardTitle>Identificadores observados</CardTitle></CardHeader><CardContent className="space-y-2">{observados.map((o, i) => <div key={`${o.module_id}-${o.chave}-${i}`} className={`flex flex-wrap items-center justify-between gap-2 rounded-md border p-3 ${!o.modalidade_id ? 'border-amber-400 bg-amber-50 text-amber-950' : ''}`}><div><strong>{o.rotulo || o.chave}</strong><div className="text-xs">{o.module_id} · {o.chave} · {o.pedidos_pendentes} pendentes · {o.modalidade_nome || 'Não classificado'}{o.pedido_exemplo_id && ` · Exemplo: pedido ${o.pedido_exemplo_numero || o.pedido_exemplo_id}`}</div>{o.service && <div className="text-xs">Serviço: {o.service} · Tags: {(o.tags || []).join(', ') || 'nenhuma'}</div>}</div><Button size="sm" variant="outline" onClick={() => setForm({ module_id: o.module_id, chave: o.chave, modalidade_id: o.modalidade_id ? String(o.modalidade_id) : '', service: o.service || '', tags: '', associacao_id: null })}>Associar</Button></div>)}{!observados.length && <p className="text-muted-foreground">Ainda não há identificadores observados. Você pode cadastrar uma associação acima.</p>}</CardContent></Card>
    <Card><CardHeader><CardTitle>Associações cadastradas</CardTitle></CardHeader><CardContent className="space-y-2">{associacoes.map((a) => <div key={a.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3"><div><strong>{a.valor} → {a.modalidades_logisticas?.nome}</strong><div className="text-xs text-muted-foreground">{a.module_id} · {a.condicoes?.service || 'Todos os serviços'} · {(a.condicoes?.tags || []).join(', ') || 'Sem condição de tag'} · {a.ativo ? 'Ativa' : 'Inativa'}</div></div><div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => setForm({ module_id: a.module_id, chave: a.valor, modalidade_id: String(a.modalidade_id), service: a.condicoes?.service || '', tags: (a.condicoes?.tags || []).join(', '), associacao_id: a.id })}>Editar</Button><Button size="sm" variant="ghost" onClick={() => toggle(a)}>{a.ativo ? 'Desativar' : 'Ativar'}</Button></div></div>)}{!associacoes.length && <p className="text-muted-foreground">Nenhuma associação cadastrada.</p>}</CardContent></Card>
  </div>;
}

const emptyWindow = { from: '', to: '', cutoff: '', day_offset: 0 };
function Agenda({ integrationId, conta, versao }) {
  const [dia, setDia] = useState(today);
  const [data, setData] = useState({ janelas: [], sincronizacoes: [], excecoes: [], divergencias: [] });
  const [regras, setRegras] = useState([]);
  const [regraId, setRegraId] = useState('');
  const [windows, setWindows] = useState([{ ...emptyWindow }]);
  const [semColeta, setSemColeta] = useState(false);
  const [motivo, setMotivo] = useState('');
  const [busy, setBusy] = useState(false);
  const [erro, setErro] = useState('');
  const load = useCallback(async () => {
    if (integrationId === 'all') return;
    const [agenda, rs] = await Promise.all([S.consultarAgenda(Number(integrationId), dia, dia), S.listarRegras(Number(integrationId))]);
    setData(agenda); setRegras(rs); setErro('');
  }, [integrationId, dia]);
  useEffect(() => { load().catch((e) => setErro(errorText(e))); const timer = setInterval(() => load().catch((e) => setErro(errorText(e))), 60_000); return () => clearInterval(timer); }, [load, versao]);
  const action = async (call, message) => { setBusy(true); try { await call(); toast.success(message); await load(); } catch (e) { toast.error(errorText(e)); } finally { setBusy(false); } };
  const selectRule = (id) => {
    setRegraId(id);
    const e = data.excecoes.find((x) => String(x.regra_id) === id);
    setWindows(e?.janelas.length ? e.janelas : [{ ...emptyWindow }]); setSemColeta(!!e && !e.janelas.length); setMotivo(e?.motivo || '');
  };
  if (integrationId === 'all') return <p className="rounded-md border p-4 text-muted-foreground">Selecione uma conta para consultar a agenda e ajustar uma data.</p>;
  return <Card><CardHeader><CardTitle>Agenda efetiva</CardTitle></CardHeader><CardContent className="space-y-4">
    <div className="flex flex-wrap items-end gap-3"><Field label="Data"><Input type="date" value={dia} onChange={(e) => { setDia(e.target.value); setRegraId(''); }} /></Field><Button variant="outline" disabled={busy} onClick={() => action(load, 'Agenda atualizada')}>Recarregar</Button>{conta?.module_id === 'mercadolivre' && <Button disabled={busy} onClick={() => action(() => S.sincronizar(integrationId), 'Atualização enfileirada. O resultado aparecerá na próxima consulta.')}>Atualizar agora</Button>}</div>
    {erro && <p role="alert" className="text-red-700">{erro}</p>}
    {data.sincronizacoes.map((s) => <div key={s.logistic_type} className={`rounded-md border p-3 text-sm ${s.erro || !s.consultada_em || Date.now() - new Date(s.consultada_em).getTime() > 1_800_000 ? 'border-amber-400 text-amber-800' : ''}`}>{s.logistic_type} · Último sucesso: {fmt(s.consultada_em)}{s.erro ? ` · ${s.erro}` : ''}</div>)}
    <div className="space-y-2">{data.janelas.map((j, i) => <div key={`${j.regra_id}-${i}`} className="rounded-md border p-3 text-sm"><strong>{j.modalidade_nome}</strong> · Corte: {fmt(j.corte_em)} · {j.logistic_type === 'xd_drop_off' || j.tipo_envio === 'PONTO_COLETA' ? 'Limite de entrega no ponto' : 'Coleta'}: {fmt(j.coleta_em)}{j.fim_em !== j.coleta_em && ` até ${fmt(j.fim_em)}`}<div className="text-xs text-muted-foreground">{j.fonte}{j.desatualizada ? ' · Dados desatualizados' : ''}{j.ponto_nome ? ` · ${j.ponto_nome}` : ''}</div></div>)}{!data.janelas.length && <p className="text-muted-foreground">Sem janela calculável nesta data. Confira o atendimento, os ajustes e os horários de contingência.</p>}</div>
    {data.divergencias.map((d) => <p key={d.demanda_id} role="status" className="rounded-md border border-amber-400 p-3 text-sm">Demanda {d.demanda_codigo}: horários publicados preservados. Coleta atual: {fmt(d.divergencia.coleta_atual)}; registrada: {fmt(d.divergencia.coleta_registrada)}.</p>)}
    <div className="space-y-3 border-t pt-4"><h3 className="font-medium">Ajustar somente esta data</h3><Field label="Regra"><select className={control} value={regraId} onChange={(e) => selectRule(e.target.value)}><option value="">Selecione a regra</option>{regras.filter((r) => r.ativo && r.modalidades_logisticas?.tipo_prazo !== 'RELATIVO').map((r) => <option key={r.id} value={r.id}>{r.modalidades_logisticas?.nome} · {r.tipo_envio === 'PONTO_COLETA' ? 'Ponto de coleta' : 'Coleta local'} · #{r.id}</option>)}</select></Field>
      <Check label="Sem coleta / entrega nesta data" checked={semColeta} onChange={setSemColeta} />
      {!semColeta && windows.map((w, i) => <div key={i} className="grid items-end gap-3 md:grid-cols-5">{[['from', 'Coleta / entrega'], ['to', 'Fim da faixa (opcional)'], ['cutoff', 'Corte desta faixa (opcional)']].map(([key, label]) => <Field key={key} label={label}><Input type="time" value={w[key] || ''} onChange={(e) => setWindows((ws) => ws.map((v, n) => n === i ? { ...v, [key]: e.target.value } : v))} /></Field>)}<Field label="Dia da coleta"><select className={control} value={w.day_offset || 0} onChange={(e) => setWindows((ws) => ws.map((v, n) => n === i ? { ...v, day_offset: Number(e.target.value) } : v))}><option value={0}>Mesmo dia</option><option value={1}>Dia seguinte</option></select></Field><Button variant="ghost" disabled={windows.length === 1} onClick={() => setWindows((ws) => ws.filter((_, n) => n !== i))}>Remover faixa</Button></div>)}
      {!semColeta && <Button variant="outline" onClick={() => setWindows((ws) => [...ws, { ...emptyWindow }])}>Adicionar faixa</Button>}
      <Field label="Motivo do ajuste"><Input value={motivo} onChange={(e) => setMotivo(e.target.value)} /></Field>
      <div className="flex gap-2"><Button disabled={busy || !regraId || !motivo.trim()} onClick={() => action(() => S.salvarExcecao(regraId, dia, { motivo, janelas: semColeta ? [] : windows }), 'Ajuste salvo para esta data')}>Salvar ajuste</Button><Button variant="outline" disabled={busy || !regraId} onClick={() => action(() => S.salvarExcecao(regraId, dia, null), 'Agenda original restaurada')}>Restaurar agenda original</Button></div>
    </div>
  </CardContent></Card>;
}
