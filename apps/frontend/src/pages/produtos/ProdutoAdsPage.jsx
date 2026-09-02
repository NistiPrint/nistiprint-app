import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import ProductService from '@/services/ProductService';
import { RefreshCw, Link2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

function ProdutoAdsPage() {
  const [ads, setAds] = useState([]);
  const [orphansOnly, setOrphansOnly] = useState(true);
  const [productIds, setProductIds] = useState({});
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try { setAds(await ProductService.getAds(orphansOnly)); }
    catch (error) { toast.error(`Erro ao carregar anúncios: ${error.message}`); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [orphansOnly]);

  const link = async ad => {
    const productId = productIds[ad.id];
    if (!productId) { toast.error('Informe o ID do produto interno.'); return; }
    try {
      await ProductService.linkAd(ad.id, productId);
      toast.success('Anúncio vinculado.');
      load();
    } catch (error) { toast.error(`Erro ao vincular anúncio: ${error.response?.data?.error || error.message}`); }
  };

  return <div className="space-y-6">
    <div className="flex items-center justify-between gap-4">
      <div><h1 className="text-2xl font-semibold">Anúncios e vínculos</h1><p className="text-sm text-muted-foreground">Revise anúncios históricos e vincule-os manualmente ao produto interno.</p></div>
      <Button variant="outline" onClick={load} disabled={loading}><RefreshCw className="mr-2 h-4 w-4" />Atualizar</Button>
    </div>
    <div className="flex items-center gap-3"><Button variant={orphansOnly ? 'default' : 'outline'} onClick={() => setOrphansOnly(true)}>Órfãos</Button><Button variant={!orphansOnly ? 'default' : 'outline'} onClick={() => setOrphansOnly(false)}>Todos</Button></div>
    <div className="grid gap-4 md:grid-cols-2">
      {ads.map(ad => <Card key={ad.id}><CardHeader><div className="flex justify-between gap-3"><CardTitle className="text-base">{ad.titulo || 'Sem título'}</CardTitle><Badge>{ad.status}</Badge></div><p className="font-mono text-xs text-muted-foreground">Item: {ad.item_externo_id} {ad.variacao_externa_id ? `| Variação: ${ad.variacao_externa_id}` : ''}</p></CardHeader><CardContent className="space-y-3"><p className="text-sm">SKU anunciado: <span className="font-mono">{ad.sku_anuncio || '-'}</span></p>{ad.produto_id ? <p className="text-sm text-green-700">Produto interno: {ad.produto_id}</p> : <div className="flex gap-2"><Input placeholder="ID do produto interno" value={productIds[ad.id] || ''} onChange={event => setProductIds(current => ({ ...current, [ad.id]: event.target.value }))} /><Button onClick={() => link(ad)}><Link2 className="mr-2 h-4 w-4" />Vincular</Button></div>}</CardContent></Card>)}
    </div>
    {!loading && ads.length === 0 && <p className="py-10 text-center text-muted-foreground">Nenhum anúncio encontrado.</p>}
  </div>;
}

export default ProdutoAdsPage;