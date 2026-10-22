import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import ProductService from '@/services/ProductService';
import api from '@/services/api';
import ProductSearchInput from '@/components/produtos/ProductSearchInput';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export default function ProductAnnouncementsPanel({ productId }) {
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState({});
  const [busy, setBusy] = useState(null);
  const load = useCallback(async () => {
    try { setData(await ProductService.getAnnouncements(productId)); }
    catch (error) { toast.error(error.message || 'Não foi possível consultar anúncios.'); }
  }, [productId]);
  useEffect(() => { load(); }, [load]);

  const linkUnit = async unit => {
    const target = selected[unit.id];
    if (!target) return toast.error('Selecione um produto para vincular.');
    setBusy(unit.id);
    try {
      await api.put(`/anuncios/unidades/${unit.id}/vinculo`, {
        integration_id: unit.integration_id,
        produto_id: target.id,
        expected_version: unit.vinculo_versao || 1,
        motivo: 'Vínculo revisado na ficha do produto',
      });
      toast.success('Vínculo atualizado.');
      await load();
    } catch (error) { toast.error(error.message || 'Falha ao vincular a unidade.'); }
    finally { setBusy(null); }
  };

  if (!data) return <p className="py-6 text-sm text-muted-foreground">Carregando anúncios…</p>;
  const headers = data.anuncios || [];
  const units = headers.flatMap(header => (header.unidades || []).map(unit => ({ ...unit, header })));
  return <div className="space-y-4">
    {!units.length && <p className="py-6 text-sm text-muted-foreground">Nenhum anúncio sincronizado para este produto.</p>}
    {units.map(unit => <Card key={unit.id}>
      <CardHeader className="pb-2"><CardTitle className="text-base">{unit.header.titulo || unit.header.item_externo_id}</CardTitle>
        <p className="text-xs text-muted-foreground">{unit.header.integration_id} · anúncio {unit.header.item_externo_id} · variação {unit.variacao_externa_id || 'simples'}</p>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-sm">SKU externo: {unit.sku_externo || 'não informado'} · preço observado: {unit.preco_observado ?? '—'} · disponibilidade: {unit.disponibilidade_observada || '—'}</p>
        <p className="text-sm">Produto vinculado: {unit.produto_id || 'pendente de revisão'}</p>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <div className="min-w-64 flex-1"><ProductSearchInput value={selected[unit.id]?.name || ''} selectedProductId={selected[unit.id]?.id}
            onChange={() => setSelected(current => ({ ...current, [unit.id]: null }))}
            onProductSelect={product => setSelected(current => ({ ...current, [unit.id]: product }))}
            onlyMarketable placeholder="Buscar produto/SKU para vincular" /></div>
          <Button disabled={busy === unit.id || !selected[unit.id]} onClick={() => linkUnit(unit)}>{busy === unit.id ? 'Salvando…' : 'Vincular produto'}</Button>
        </div>
      </CardContent>
    </Card>)}
    {(data.unidades_sem_cabecalho || []).length > 0 && <p className="text-sm text-amber-700">Há unidades legadas sem cabeçalho de anúncio associado.</p>}
  </div>;
}
