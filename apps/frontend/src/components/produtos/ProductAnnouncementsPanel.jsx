import { useCallback, useEffect, useState } from 'react';
import ProductService from '@/services/ProductService';
import { Link } from 'react-router-dom';
import AnnouncementUnit from './AnnouncementUnit';
import { useAuth } from '@/contexts/AuthContext';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export default function ProductAnnouncementsPanel({ productId }) {
  const { hasPermission } = useAuth();
  const canEdit = hasPermission('produtos','editar');
  const [error, setError] = useState('');
  const [data, setData] = useState(null);
  const load = useCallback(async () => {
    try { const result = await ProductService.getAnnouncements(productId); setData(result); setError(''); }
    catch (error) { setError(error.message || 'Não foi possível consultar anúncios.'); }
  }, [productId]);
  useEffect(() => {
    let cancelled = false;
    ProductService.getAnnouncements(productId).then(result => {
      if (!cancelled) { setData(result); setError(''); }
    }).catch(err => { if (!cancelled) setError(err.message || 'Não foi possível consultar anúncios.'); });
    return () => { cancelled = true; };
  }, [productId]);

  if (error) return <p role="alert" className="py-6 text-sm text-red-700">{error}</p>;
  if (!data) return <p className="py-6 text-sm text-muted-foreground">Carregando anúncios…</p>;
  const headers = data.anuncios || [];
  const units = headers.flatMap(header => (header.unidades || []).map(unit => ({ ...unit, header })));
  return <div className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-muted/30 p-4"><div><p className="font-medium">{headers.length} anúncios · {units.length} variações vinculadas</p><p className="text-sm text-muted-foreground">Acompanhe este produto em cada conta e revise o histórico das relações.</p></div><div className="flex gap-2"><Button variant="outline" onClick={load}>Atualizar</Button><Button variant="outline" asChild><Link to={`/anuncios?produto_id=${productId}`}>Ver na central de vínculos</Link></Button></div></div>
    {!units.length && <p className="py-6 text-sm text-muted-foreground">Nenhum anúncio sincronizado para este produto.</p>}
    {units.map(unit => <Card key={unit.id}>
      <CardHeader className="pb-2"><CardTitle className="text-base">{unit.header.titulo || 'Título ainda não sincronizado'}</CardTitle>
        <p className="text-xs text-muted-foreground">{unit.header.conta_nome || `Conta ${unit.header.integration_id}`} · anúncio {unit.header.item_externo_id}</p>
      </CardHeader>
      <CardContent><AnnouncementUnit unit={unit} header={unit.header} canEdit={canEdit} onSaved={load} />
      </CardContent>
    </Card>)}
    {(data.unidades_sem_cabecalho || []).length > 0 && <p className="text-sm text-amber-700">Há unidades legadas sem cabeçalho de anúncio associado.</p>}
  </div>;
}
