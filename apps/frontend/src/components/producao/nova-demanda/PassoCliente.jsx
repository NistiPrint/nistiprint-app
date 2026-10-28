import { PilulaBotao } from '@/components/producao/nova-demanda/OpcaoBotao';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { INTERACAO_STATUS_OPTIONS } from '@/schemas/demandaSchema';

/** Passo exclusivo da venda corporativa. */
function PassoCliente({ form }) {
  const statusAtual = form.watch('empresa_interacao_status');

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <FormField
          control={form.control}
          name="empresa_cliente_nome"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Empresa / cliente</FormLabel>
              <FormControl>
                <Input placeholder="Nome da empresa" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="empresa_responsavel_nome"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Contato responsável</FormLabel>
              <FormControl>
                <Input placeholder="Nome do contato na empresa" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="empresa_pedido_plataforma_numero"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Nº pedido plataforma</FormLabel>
              <FormControl>
                <Input placeholder="Nº pedido externo" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
      </div>

      <FormField
        control={form.control}
        name="empresa_interacao_status"
        render={() => (
          <FormItem>
            <FormLabel>Status da interação</FormLabel>
            <div className="flex flex-wrap gap-2">
              {INTERACAO_STATUS_OPTIONS.map((status) => (
                <PilulaBotao
                  key={status}
                  ativo={statusAtual === status}
                  onClick={() => form.setValue('empresa_interacao_status', status, { shouldDirty: true })}
                >
                  {status}
                </PilulaBotao>
              ))}
            </div>
            <FormMessage />
          </FormItem>
        )}
      />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <FormField
          control={form.control}
          name="empresa_wire_o_cor"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Cor do wire-o</FormLabel>
              <FormControl>
                <Input type="color" {...field} className="h-10 w-full" />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="empresa_elastico_cor"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Cor do elástico</FormLabel>
              <FormControl>
                <Input type="color" {...field} className="h-10 w-full" />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
      </div>
    </div>
  );
}

export default PassoCliente;
