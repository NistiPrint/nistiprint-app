import CanalBotao from '@/components/producao/nova-demanda/CanalBotao';
import { OpcaoBotao, PilulaBotao } from '@/components/producao/nova-demanda/OpcaoBotao';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { DEMANDA_FLOW_OPTIONS, getModalidadeLabel } from '@/lib/demandaFlow';
import { datasRapidas, janelasColeta, modalidadesDisponiveis } from '@/lib/novaDemanda';
import { Briefcase, Factory, PackageCheck, RotateCcw, Search, ShoppingCart } from 'lucide-react';
import { useMemo, useState } from 'react';

const ICONES_FLUXO = {
  venda_diaria: ShoppingCart,
  fulfillment: PackageCheck,
  venda_corporativa: Briefcase,
  producao_interna: Factory,
};

const LIMITE_BUSCA_CANAIS = 12;

function Grupo({ titulo, descricao, children, ...rest }) {
  return (
    <section className="space-y-3" {...rest}>
      <div>
        <h3 className="text-sm font-semibold">{titulo}</h3>
        {descricao && <p className="text-xs text-muted-foreground">{descricao}</p>}
      </div>
      {children}
    </section>
  );
}

/**
 * Passo 1: fluxo, canal e modalidade em botões; data, horário de coleta e
 * finalização prevista já preenchidos a partir do canal escolhido.
 */
function PassoOrigem({
  form,
  canais,
  moduleIcons,
  hoje,
  canalSelecionado,
  fluxo,
  modalidade,
  onEscolherFluxo,
  onEscolherCanal,
  onEscolherModalidade,
  onAlterarData,
  onRecalcularPrazos,
  prazosSobrescritos,
}) {
  const [busca, setBusca] = useState('');

  const canaisDoFluxo = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    const filtrados = termo
      ? canais.filter((canal) =>
          `${canal.nome} ${canal.plataforma || ''}`.toLowerCase().includes(termo)
        )
      : canais;

    if (fluxo !== 'fulfillment') return filtrados;
    // Em fulfillment, os canais que fazem Full vêm primeiro.
    return [...filtrados].sort((a, b) => Number(Boolean(b.fulfillment)) - Number(Boolean(a.fulfillment)));
  }, [canais, busca, fluxo]);

  const gruposDeCanais = useMemo(() => {
    const grupos = new Map();
    canaisDoFluxo.forEach((canal) => {
      const chave = canal.plataforma || 'Outros';
      if (!grupos.has(chave)) grupos.set(chave, []);
      grupos.get(chave).push(canal);
    });
    return [...grupos.entries()];
  }, [canaisDoFluxo]);

  const modalidades = useMemo(
    () => (canalSelecionado ? modalidadesDisponiveis(canalSelecionado, fluxo) : []),
    [canalSelecionado, fluxo]
  );

  const janelas = useMemo(
    () => (canalSelecionado ? janelasColeta(canalSelecionado, modalidade) : []),
    [canalSelecionado, modalidade]
  );

  const datas = useMemo(() => datasRapidas(hoje), [hoje]);
  const dataEntrega = form.watch('data_entrega');
  const horarioColeta = form.watch('horario_coleta_especifico');

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <div className="space-y-5">
      <Grupo titulo="Fluxo da demanda" descricao="Define o tipo, a classificação do cliente e a modalidade padrão.">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {DEMANDA_FLOW_OPTIONS.map((opcao) => (
            <OpcaoBotao
              key={opcao.id}
              ativo={fluxo === opcao.id}
              onClick={() => onEscolherFluxo(opcao.id)}
              titulo={opcao.label}
              descricao={opcao.description}
              icone={ICONES_FLUXO[opcao.id]}
            />
          ))}
        </div>
      </Grupo>

      <Grupo titulo="Plataforma / canal" descricao="Um clique seleciona a origem e preenche data e horário de coleta.">
        {canais.length > LIMITE_BUSCA_CANAIS && (
          <div className="relative max-w-sm">
            <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              value={busca}
              onChange={(evento) => setBusca(evento.target.value)}
              placeholder="Filtrar canais..."
              className="pl-8"
            />
          </div>
        )}

        {gruposDeCanais.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nenhum canal de venda ativo encontrado.</p>
        ) : (
          gruposDeCanais.map(([plataforma, lista]) => (
            <div key={plataforma} className="space-y-2">
              <p className="text-xs font-bold uppercase tracking-wide text-muted-foreground">{plataforma}</p>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                {lista.map((canal) => (
                  <CanalBotao
                    key={canal.id}
                    canal={canal}
                    moduleIcons={moduleIcons}
                    ativo={String(canal.id) === form.watch('canal_venda_id')}
                    onClick={() => onEscolherCanal(canal)}
                  />
                ))}
              </div>
            </div>
          ))
        )}
        <FormField
          control={form.control}
          name="canal_venda_id"
          render={() => (
            <FormItem>
              <FormMessage />
            </FormItem>
          )}
        />
      </Grupo>

      {canalSelecionado && (
        <Grupo titulo="Modalidade logística">
          {modalidades.length > 1 ? (
            <div className="flex flex-wrap gap-2">
              {modalidades.map((opcao) => (
                <PilulaBotao
                  key={opcao}
                  ativo={modalidade === opcao}
                  onClick={() => onEscolherModalidade(opcao)}
                >
                  {getModalidadeLabel(opcao)}
                </PilulaBotao>
              ))}
            </div>
          ) : (
            <Badge variant="outline">{getModalidadeLabel(modalidade)}</Badge>
          )}
        </Grupo>
      )}

      </div>

      <div className="space-y-5 lg:sticky lg:top-4 lg:self-start lg:rounded-lg lg:border lg:bg-muted/20 lg:p-5">
      <Grupo titulo="Entrega" descricao="Preenchido pelo canal e pela modalidade; altere se precisar.">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 2xl:grid-cols-3">
          <FormField
            control={form.control}
            name="data_entrega"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Data de entrega</FormLabel>
                <div className="mb-2 flex flex-wrap gap-2">
                  {datas.map((data) => (
                    <PilulaBotao
                      key={data.value}
                      ativo={dataEntrega === data.value}
                      onClick={() => onAlterarData(data.value)}
                    >
                      {data.label}
                    </PilulaBotao>
                  ))}
                </div>
                <FormControl>
                  <Input type="date" {...field} onChange={(evento) => onAlterarData(evento.target.value)} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="horario_coleta_especifico"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Horário de coleta</FormLabel>
                {janelas.length > 0 && (
                  <div className="mb-2 flex flex-wrap gap-2">
                    {janelas.map((janela, indice) => (
                      <PilulaBotao
                        key={`${janela.horario}-${indice}`}
                        ativo={horarioColeta === janela.horario}
                        title={[janela.tipo, janela.ponto].filter(Boolean).join(' · ') || undefined}
                        onClick={() =>
                          form.setValue('horario_coleta_especifico', janela.horario, {
                            shouldDirty: true,
                            shouldValidate: true,
                          })
                        }
                      >
                        {janela.horario}
                        {janela.ponto ? ` · ${janela.ponto}` : ''}
                      </PilulaBotao>
                    ))}
                  </div>
                )}
                <FormControl>
                  <Input type="time" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="data_finalizacao_prevista"
            render={({ field }) => (
              <FormItem className="sm:col-span-2 2xl:col-span-1">
                <FormLabel className="flex items-center gap-2">
                  Finalização prevista
                  {prazosSobrescritos ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-6 px-2 text-xs"
                      onClick={onRecalcularPrazos}
                    >
                      <RotateCcw className="mr-1 h-3 w-3" /> Recalcular
                    </Button>
                  ) : (
                    <Badge variant="outline" className="text-[10px] uppercase">auto</Badge>
                  )}
                </FormLabel>
                <FormControl>
                  <Input type="datetime-local" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>
      </Grupo>

      <Grupo titulo="Identificação">
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <FormField
            control={form.control}
            name="nome"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Nome da demanda</FormLabel>
                <FormControl>
                  <Input placeholder="Ex: Pedido Bling 12345" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="observacoes"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Observações</FormLabel>
                <FormControl>
                  <Textarea placeholder="Observações gerais..." rows={1} className="min-h-[40px]" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>
      </Grupo>
      </div>
    </div>
  );
}

export default PassoOrigem;
