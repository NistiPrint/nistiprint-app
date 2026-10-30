import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Link2, Unlink, AlertCircle } from 'lucide-react';
import { toast } from 'sonner';
import api from '@/services/api';
import ProductSearchInput from './ProductSearchInput';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';

const reviewLabels = {
  unmapped: 'Nenhum produto identificado. Selecione o cadastro correspondente.',
  conflict: 'Mais de um cadastro pode corresponder a esta variação. Revise antes de vincular.',
  confirmed_conflict: 'O vínculo confirmado diverge dos dados encontrados na reconciliação.',
};

export default function AnnouncementUnit({ unit, header, canEdit, onSaved }) {
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState(null);
  const [reason, setReason] = useState('');
  const [unlink, setUnlink] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const variation = Object.entries(unit.atributos_variacao || {}).map(([key, value]) => `${key}: ${value}`).join(' · ') || (unit.variacao_externa_id ? `Variação ${unit.variacao_externa_id}` : 'Produto sem variações');
  const start = removing => { setTarget(null); setReason(''); setError(''); setUnlink(removing); setOpen(true); };
  const save = async () => {
    if (!canEdit || busy || !reason.trim() || (!unlink && (!target || target.id === unit.produto_id))) return;
    setBusy(true); setError('');
    try {
      await api.put(`/anuncios/unidades/${unit.id}/vinculo`, {
        integration_id: header.integration_id, produto_id: unlink ? null : target.id,
        expected_version: unit.vinculo_versao || 1, motivo: reason.trim(),
      });
      setOpen(false); toast.success('Vínculo atualizado. Alteração registrada no histórico.'); await onSaved();
    } catch (err) { setError(err.message || 'Não foi possível salvar. Atualize os dados e tente novamente.'); }
    finally { setBusy(false); }
  };
  return <div className="rounded-lg border bg-background p-4 space-y-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-xs font-medium ${unit.pendencia || !unit.produto_id ? 'bg-amber-100 text-amber-900' : 'bg-emerald-100 text-emerald-900'}`}>
        {unit.pendencia ? <AlertCircle className="h-3.5 w-3.5" /> : <Link2 className="h-3.5 w-3.5" />}{unit.pendencia ? 'Precisa de revisão' : unit.produto_id ? 'Vinculado' : 'Sem vínculo'}
      </span>
      {canEdit && <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => start(false)}>{unit.produto_id ? 'Alterar vínculo' : 'Vincular produto'}</Button>{unit.produto_id && <Button size="sm" variant="ghost" onClick={() => start(true)} aria-label={`Desvincular ${variation}`}><Unlink className="h-4 w-4" /></Button>}</div>}
    </div>
    <div className="grid gap-3 text-sm md:grid-cols-[1fr_auto_1fr] md:items-center">
      <div><p className="font-medium">{variation}</p><p className="mt-1 text-xs text-muted-foreground">SKU externo: {unit.sku_externo || 'não informado'}{unit.variacao_externa_id ? ` · ID ${unit.variacao_externa_id}` : ''}</p></div>
      <ArrowRight className="hidden h-4 w-4 text-muted-foreground md:block" />
      <div className="rounded-md bg-muted/50 p-3">{unit.produto_id ? <><Link className="font-medium underline underline-offset-4" to={`/produtos/${unit.produto_id}/editar`}>{unit.produto?.nome || `Produto #${unit.produto_id}`}</Link><p className="mt-1 text-xs text-muted-foreground">SKU interno: {unit.produto?.sku || '—'} · #{unit.produto_id}</p></> : <p className="text-muted-foreground">Selecione o cadastro interno que representa esta variação.</p>}</div>
    </div>
    <p className="text-xs text-muted-foreground">Preço observado: {unit.preco_observado == null ? 'não informado' : Number(unit.preco_observado).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })} · Disponibilidade: {unit.disponibilidade_observada ?? 'não informada'}</p>
    {unit.pendencia && <div className="rounded-md bg-amber-50 p-3 text-sm text-amber-900"><p>{reviewLabels[unit.pendencia.motivo] || unit.pendencia.motivo}</p>{!!unit.pendencia.candidatos?.length && <div className="mt-2 flex flex-wrap gap-3">{unit.pendencia.candidatos.map(id => <Link key={id} to={`/produtos/${id}/editar`} className="underline">Revisar produto #{id}</Link>)}</div>}</div>}
    {unit.produto?.status && unit.produto.status !== 'ativo' && <p className="text-xs text-amber-800">Cadastro interno {unit.produto.status === 'inativo' ? 'inativo' : unit.produto.status}. Confira a prontidão no cadastro do produto.</p>}
    <details className="text-xs"><summary className="cursor-pointer text-muted-foreground">Histórico de vínculos{unit.historico?.length ? ` (${unit.historico.length} registros disponíveis)` : ''}</summary>
      <ol className="mt-3 space-y-3 border-l pl-4">{(unit.historico || []).map(entry => <li key={entry.id}><p className="font-medium">{entry.produto_anterior_id ? `#${entry.produto_anterior_id}` : 'Sem produto'} → {entry.produto_novo_id ? `#${entry.produto_novo_id}` : 'Sem produto'}</p><p>{entry.motivo}</p><p className="text-muted-foreground">{entry.ocorrido_em ? new Date(entry.ocorrido_em).toLocaleString('pt-BR') : 'Data indisponível'} · {entry.origem}</p></li>)}</ol>{!unit.historico?.length && <p className="mt-2 text-muted-foreground">Nenhuma alteração disponível nesta consulta.</p>}
    </details>
    <Dialog open={open} onOpenChange={value => { if (!busy) setOpen(value); }}><DialogContent>
      <DialogHeader><DialogTitle>{unlink ? 'Desvincular produto' : unit.produto_id ? 'Alterar vínculo' : 'Vincular produto'}</DialogTitle><DialogDescription>{header.titulo} · {variation}. A alteração será registrada no histórico.</DialogDescription></DialogHeader>
      <div className="rounded-md bg-muted p-3 text-sm"><p>Atual: {unit.produto?.nome || (unit.produto_id ? `Produto #${unit.produto_id}` : 'Sem vínculo')}</p>{unlink && <p className="mt-2 font-medium">Após salvar: sem produto vinculado.</p>}</div>
      {!unlink && <div className="space-y-2"><p className="text-sm font-medium">Novo produto interno</p><ProductSearchInput value={target?.name || target?.nome || ''} selectedProductId={target?.id} onChange={() => setTarget(null)} onProductSelect={setTarget} onlyMarketable placeholder="Buscar pelo nome ou SKU" />{target && <p className="text-sm">Selecionado: {target.name || target.nome} · #{target.id}</p>}</div>}
      <label className="grid gap-2 text-sm font-medium">Motivo da alteração<textarea className="min-h-20 rounded-md border bg-background p-3 font-normal" value={reason} onChange={event => setReason(event.target.value)} placeholder="Explique a identificação ou correção realizada" disabled={busy} /></label>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <DialogFooter><Button variant="outline" disabled={busy} onClick={() => setOpen(false)}>Cancelar</Button><Button variant={unlink ? 'destructive' : 'default'} disabled={busy || !reason.trim() || (!unlink && (!target || target.id === unit.produto_id))} onClick={save}>{busy ? 'Salvando…' : unlink ? 'Confirmar desvinculação' : 'Confirmar vínculo'}</Button></DialogFooter>
    </DialogContent></Dialog>
  </div>;
}
