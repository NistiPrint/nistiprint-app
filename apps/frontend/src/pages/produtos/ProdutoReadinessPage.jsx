import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import TagService from '@/services/TagService';
import ProductService from '@/services/ProductService';
import { RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

const stages = ['RASCUNHO', 'ARTE_PENDENTE', 'ARTE_OK', 'FICHA_OK', 'CANAL_OK', 'PUBLICADO', 'DESCONTINUADO'];

function ProdutoReadinessPage() {
  const [tags, setTags] = useState([]);
  const [products, setProducts] = useState([]);
  const [tagId, setTagId] = useState('all');
  const [stage, setStage] = useState('all');
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      setProducts(await ProductService.getReadiness({ tagId: tagId === 'all' ? null : tagId, estagio: stage }));
    } catch (error) {
      toast.error(`Erro ao carregar prontidão: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const publish = async product => {
    try {
      await ProductService.publish(product.produto_id);
      toast.success('Produto publicado.');
      load();
    } catch (error) {
      toast.error(`Não foi possível publicar: ${error.response?.data?.error || error.message}`);
    }
  };

  useEffect(() => {
    TagService.getAll().then(setTags).catch(error => toast.error(`Erro ao carregar tags: ${error.message}`));
  }, []);

  useEffect(() => { load(); }, [tagId, stage]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Prontidão do catálogo</h1>
          <p className="text-sm text-muted-foreground">Pendências reais de produtos e coleções. Nenhuma correção é aplicada automaticamente.</p>
        </div>
        <Button variant="outline" onClick={load} disabled={loading}><RefreshCw className="mr-2 h-4 w-4" />Atualizar</Button>
      </div>

      <Card>
        <CardContent className="flex flex-wrap gap-4 pt-6">
          <Select value={tagId} onValueChange={setTagId}>
            <SelectTrigger className="w-[220px]"><SelectValue placeholder="Todas as tags" /></SelectTrigger>
            <SelectContent><SelectItem value="all">Todas as tags</SelectItem>{tags.map(tag => <SelectItem key={tag.id} value={String(tag.id)}>{tag.nome}</SelectItem>)}</SelectContent>
          </Select>
          <Select value={stage} onValueChange={setStage}>
            <SelectTrigger className="w-[220px]"><SelectValue placeholder="Todos os estágios" /></SelectTrigger>
            <SelectContent><SelectItem value="all">Todos os estágios</SelectItem>{stages.map(item => <SelectItem key={item} value={item}>{item}</SelectItem>)}</SelectContent>
          </Select>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {products.map(product => (
          <Card key={product.produto_id}>
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between gap-3">
                <div><CardTitle className="text-base">{product.nome}</CardTitle><p className="font-mono text-xs text-muted-foreground">{product.sku}</p></div>
                <Badge variant={product.pendencias?.length ? 'secondary' : 'outline'}>{product.estagio}</Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="grid grid-cols-2 gap-2 text-xs">
                <span>Ficha: {product.ficha_completa ? 'OK' : 'Pendente'}</span>
                <span>Eixos: {product.eixos_completos ? 'OK' : 'Pendente'}</span>
                <span>Arte: {!product.exige_arte || product.arte_confirmada ? 'OK' : 'Pendente'}</span>
                <span>Canal: {product.tem_apelido_externo ? 'OK' : 'Pendente'}</span>
              </div>
              {product.pendencias?.length > 0 && <ul className="list-disc pl-5 text-amber-700">{product.pendencias.map(item => <li key={item}>{item}</li>)}</ul>}
              <div className="flex gap-2">
                <Button asChild variant="outline" size="sm"><Link to={`/produtos/${product.produto_id}/editar`}>Abrir produto</Link></Button>
                {product.estagio !== 'PUBLICADO' && <Button size="sm" disabled={product.pendencias?.length > 0} onClick={() => publish(product)}>Publicar</Button>}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      {!loading && products.length === 0 && <p className="py-10 text-center text-muted-foreground">Nenhum produto encontrado.</p>}
    </div>
  );
}

export default ProdutoReadinessPage;