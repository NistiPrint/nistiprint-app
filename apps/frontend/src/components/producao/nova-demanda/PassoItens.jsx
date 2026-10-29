import ProductSearchInput from '@/components/produtos/ProductSearchInput';
import { Button } from '@/components/ui/button';
import { FormControl, FormField, FormItem, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ClipboardPaste, PlusCircle, Trash2 } from 'lucide-react';

/** Passo 2: itens da demanda. */
function PassoItens({ form, itemFields, onAdicionarItem, onRemoverItem, onColarItens, onSelecionarProduto, fluxo }) {
  const itens = form.watch('itens') || [];
  const quantidadeTotal = itens.reduce((total, item) => total + (Number(item?.quantidade) || 0), 0);
  const erroItens = form.formState.errors.itens?.message || form.formState.errors.itens?.root?.message;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {itens.length} {itens.length === 1 ? 'linha' : 'linhas'} · {quantidadeTotal} un.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" onClick={onColarItens}>
            <ClipboardPaste className="mr-2 h-4 w-4" /> Colar itens da planilha
          </Button>
          <Button type="button" variant="outline" onClick={onAdicionarItem}>
            <PlusCircle className="mr-2 h-4 w-4" /> Adicionar item
          </Button>
        </div>
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[300px]">Item (descrição / busca)</TableHead>
              <TableHead className="w-[120px]">SKU</TableHead>
              <TableHead className="w-[120px]">Variação</TableHead>
              <TableHead className="w-[160px]">Miolo</TableHead>
              <TableHead className="w-[80px]">Qtd</TableHead>
              <TableHead className="w-[50px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {itemFields.map((item, index) => (
              <TableRow key={item.id}>
                <TableCell>
                  <FormField
                    control={form.control}
                    name={`itens.${index}.descricao`}
                    render={({ field }) => (
                      <FormItem>
                        <FormControl>
                          <ProductSearchInput
                            value={field.value}
                            selectedProductId={form.getValues(`itens.${index}.product_id`)}
                            onChange={field.onChange}
                            onProductSelect={(produto) => onSelecionarProduto(index, produto)}
                            placeholder="Digite para buscar ou descrever..."
                            materialTypes={fluxo === 'producao_interna' ? ['intermediario', 'produto_acabado'] : ['produto_acabado']}
                            showProductLevelBadge
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </TableCell>
                <TableCell>
                  <FormField
                    control={form.control}
                    name={`itens.${index}.sku`}
                    render={({ field }) => (
                      <FormItem>
                        <FormControl>
                          <Input {...field} className="h-8" />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                </TableCell>
                <TableCell>
                  <FormField
                    control={form.control}
                    name={`itens.${index}.variacao`}
                    render={({ field }) => (
                      <FormItem>
                        <FormControl>
                          <Input {...field} className="h-8" />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                </TableCell>
                <TableCell>
                  <FormField
                    control={form.control}
                    name={`itens.${index}.miolo_nome`}
                    render={({ field }) => (
                      <FormItem>
                        <FormControl>
                          <ProductSearchInput
                            value={field.value}
                            selectedProductId={form.getValues(`itens.${index}.id_produto_miolo`)}
                            onChange={field.onChange}
                            onProductSelect={(produto) => {
                              form.setValue(`itens.${index}.miolo_nome`, produto.name);
                              form.setValue(`itens.${index}.id_produto_miolo`, String(produto.id));
                            }}
                            placeholder="Digite para buscar miolo..."
                            materialTypes={['intermediario']}
                            showCheckIndicator
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <input type="hidden" {...form.register(`itens.${index}.id_produto_miolo`)} />
                </TableCell>
                <TableCell>
                  <FormField
                    control={form.control}
                    name={`itens.${index}.quantidade`}
                    render={({ field }) => (
                      <FormItem>
                        <FormControl>
                          <Input type="number" min="1" {...field} className="h-8" />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </TableCell>
                <TableCell>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label="Remover item"
                    onClick={() => onRemoverItem(index)}
                  >
                    <Trash2 className="h-4 w-4 text-red-500" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {erroItens && <p className="text-sm font-medium text-destructive">{erroItens}</p>}
    </div>
  );
}

export default PassoItens;
