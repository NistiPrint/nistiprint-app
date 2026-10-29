import CanalBotao from '@/components/producao/nova-demanda/CanalBotao';
import { OpcaoBotao, PilulaBotao } from '@/components/producao/nova-demanda/OpcaoBotao';
import { Button } from '@/components/ui/button';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { DEMANDA_FLOW_OPTIONS } from '@/lib/demandaFlow';
import { datasRapidas, janelasColeta } from '@/lib/novaDemanda';
import { Briefcase, Factory, PackageCheck, RotateCcw, Search, ShoppingCart } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

const FLOW_ICONS = { venda_diaria: ShoppingCart, fulfillment: PackageCheck, venda_corporativa: Briefcase, producao_interna: Factory };
const MODALIDADES = [{ value: 'STANDARD', label: 'Comum' }, { value: 'EXPRESS', label: 'Flex' }, { value: 'FULFILLMENT', label: 'Full' }, { value: 'RETIRADA', label: 'Retirada' }];

function Section({ title, children, className = '' }) {
  return <section className={`space-y-2 ${className}`}><h3 className="text-sm font-semibold">{title}</h3>{children}</section>;
}

function PassoOrigem({ form, canais, moduleIcons, hoje, canalSelecionado, fluxo, modalidade, onEscolherFluxo, onEscolherCanal, onEscolherModalidade, onAlterarData, onRecalcularPrazos, prazosSobrescritos, isEditing, onFinalizar }) {
  const [busca, setBusca] = useState('');
  const [nomeManual, setNomeManual] = useState(isEditing);
  const [etapa, setEtapa] = useState(0);
  const nome = form.watch('nome');
  const horarioColeta = form.watch('horario_coleta_especifico');
  const dataEntrega = form.watch('data_entrega');
  const nomeSugerido = canalSelecionado ? `${canalSelecionado.nome.trim()} - ${MODALIDADES.find((item) => item.value === modalidade)?.label || 'Comum'}` : '';
  const canaisFiltrados = useMemo(() => canais.filter((canal) => `${canal.nome} ${canal.plataforma || ''}`.toLowerCase().includes(busca.trim().toLowerCase())), [canais, busca]);
  const janelas = useMemo(() => canalSelecionado ? janelasColeta(canalSelecionado, modalidade) : [], [canalSelecionado, modalidade]);
  const datas = useMemo(() => datasRapidas(hoje), [hoje]);

  // Sugere o nome sem interferir em uma edição manual ou em demandas existentes.
  useEffect(() => {
    if (!nomeManual && !isEditing && nomeSugerido && nome !== nomeSugerido) form.setValue('nome', nomeSugerido, { shouldDirty: true, shouldValidate: true });
  }, [form, isEditing, nome, nomeManual, nomeSugerido]);

  const titulos = ['Nome e tipo', 'Canal e modalidade', 'Prazos'];
  return <div className="space-y-6">
    <div className="flex items-center justify-center gap-3" aria-label="Etapas da origem">
      {titulos.map((titulo, index) => <button key={titulo} type="button" onClick={() => index < etapa && setEtapa(index)} className={`rounded-full px-4 py-2 text-sm font-semibold ${index === etapa ? 'bg-primary text-primary-foreground' : index < etapa ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'}`} aria-current={index === etapa ? 'step' : undefined}>{index + 1}. {titulo}</button>)}
    </div>
    {etapa === 0 && <div className="mx-auto max-w-5xl space-y-6">
      <Section title="Nome da demanda">
        <FormField control={form.control} name="nome" render={({ field }) => <FormItem>
          <FormControl><Input className="h-10" placeholder="Ex.: Shopee - Flex" {...field} onChange={(event) => { setNomeManual(true); field.onChange(event); }} /></FormControl>
          {!nomeManual && nomeSugerido && <p className="text-xs text-muted-foreground">Sugestão automática · você pode editar</p>}
          {nomeManual && nomeSugerido && <Button type="button" variant="link" className="h-auto p-0 text-xs" onClick={() => { setNomeManual(false); form.setValue('nome', nomeSugerido, { shouldDirty: true, shouldValidate: true }); }}>Usar sugestão: {nomeSugerido}</Button>}
          <FormMessage />
        </FormItem>} />
      </Section>
      <Section title="Tipo da demanda">
        <div className="grid grid-cols-2 gap-4">{DEMANDA_FLOW_OPTIONS.map((option) => <OpcaoBotao key={option.id} ativo={fluxo === option.id} onClick={() => onEscolherFluxo(option.id)} titulo={{ venda_corporativa: 'Empresa', fulfillment: 'Full', producao_interna: 'Estoque', venda_diaria: 'Venda avulsa' }[option.id]} descricao={option.description} icone={FLOW_ICONS[option.id]} className="min-h-24 items-center p-5" />)}</div>
      </Section>
    </div>}
    {etapa === 1 && <div className="mx-auto max-w-6xl space-y-6">
      <Section title="Plataforma / canal">
        <div className="relative max-w-sm"><Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" /><Input value={busca} onChange={(event) => setBusca(event.target.value)} placeholder="Buscar canal..." className="h-9 pl-8" /></div>
        {canaisFiltrados.length ? <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">{canaisFiltrados.map((canal) => <CanalBotao key={canal.id} canal={canal} moduleIcons={moduleIcons} ativo={String(canal.id) === form.watch('canal_venda_id')} onClick={() => onEscolherCanal(canal)} />)}</div> : <p className="text-sm text-muted-foreground">Nenhum canal encontrado.</p>}
        <FormField control={form.control} name="canal_venda_id" render={() => <FormItem><FormMessage /></FormItem>} />
      </Section>
      <Section title="Modalidade logística"><div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{MODALIDADES.map((option) => <PilulaBotao key={option.value} ativo={modalidade === option.value} onClick={() => onEscolherModalidade(option.value)} className="rounded-lg px-5 py-4 text-base">{option.label}</PilulaBotao>)}</div></Section>
    </div>}
    {etapa === 2 && <div className="mx-auto grid max-w-6xl grid-cols-1 gap-5 md:grid-cols-2">
    <div className="space-y-3 rounded-lg border bg-muted/20 p-5">
      <Section title="Prazos">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FormField control={form.control} name="data_finalizacao_prevista" render={({ field }) => <FormItem className="sm:col-span-2">
            <FormLabel className="flex items-center gap-2">Data de finalização {prazosSobrescritos ? <Button type="button" variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={onRecalcularPrazos}><RotateCcw className="mr-1 h-3 w-3" />Recalcular</Button> : <span className="text-xs text-muted-foreground">auto</span>}</FormLabel>
            <FormControl><Input type="datetime-local" {...field} /></FormControl><FormMessage />
          </FormItem>} />
          <FormField control={form.control} name="data_entrega" render={({ field }) => <FormItem>
            <FormLabel>Data / hora de envio ou coleta</FormLabel>
            <div className="flex flex-wrap gap-1">{datas.map((data) => <PilulaBotao key={data.value} ativo={dataEntrega === data.value} onClick={() => onAlterarData(data.value)}>{data.label}</PilulaBotao>)}</div>
            <FormControl><Input type="date" {...field} onChange={(event) => onAlterarData(event.target.value)} /></FormControl><FormMessage />
          </FormItem>} />
          <FormField control={form.control} name="horario_coleta_especifico" render={({ field }) => <FormItem>
            <FormLabel>Horário de envio / coleta</FormLabel>
            {janelas.length > 0 && <div className="flex flex-wrap gap-1">{janelas.map((janela, index) => <PilulaBotao key={`${janela.horario}-${index}`} ativo={horarioColeta === janela.horario} title={[janela.tipo, janela.ponto].filter(Boolean).join(' · ')} onClick={() => form.setValue('horario_coleta_especifico', janela.horario, { shouldDirty: true, shouldValidate: true })}>{janela.horario}{janela.ponto ? ` · ${janela.ponto}` : ''}</PilulaBotao>)}</div>}
            <FormControl><Input type="time" {...field} /></FormControl><FormMessage />
          </FormItem>} />
        </div>
      </Section>
      <FormField control={form.control} name="observacoes" render={({ field }) => <FormItem>
        <FormLabel>Observações</FormLabel><FormControl><Textarea placeholder="Observações gerais..." rows={5} {...field} /></FormControl><FormMessage />
      </FormItem>} />
    </div></div>}
    <div className="flex justify-between border-t pt-4">
      <Button type="button" variant="outline" disabled={etapa === 0} onClick={() => setEtapa((value) => Math.max(0, value - 1))}>Voltar</Button>
      {etapa < 2 ? <Button type="button" onClick={() => setEtapa((value) => Math.min(2, value + 1))}>Próximo</Button> : <Button type="button" onClick={onFinalizar}>Continuar para itens</Button>}
    </div>
  </div>;
}

export default PassoOrigem;
