import PassoCliente from '@/components/producao/nova-demanda/PassoCliente';
import PassoItens from '@/components/producao/nova-demanda/PassoItens';
import PassoOrigem from '@/components/producao/nova-demanda/PassoOrigem';
import ResumoDemanda from '@/components/producao/nova-demanda/ResumoDemanda';
import TrilhaPassos from '@/components/producao/nova-demanda/TrilhaPassos';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Form } from '@/components/ui/form';
import PageHeader from '@/components/ui/PageHeader';
import { dataOperacionalHoje } from '@/lib/dataOperacional';
import { deriveDemandFlow, getDemandFlowConfig } from '@/lib/demandaFlow';
import {
  calcularFinalizacaoPrevista,
  modalidadesDisponiveis,
  montarPayloadDemanda,
  sugerirHorarioColeta,
  urlCriacaoDemanda,
} from '@/lib/novaDemanda';
import { CAMPOS_POR_PASSO, criarDemandaSchema } from '@/schemas/demandaSchema';
import CanalVendaService from '@/services/CanalVendaService';
import MarketplaceService from '@/services/MarketplaceService';
import { zodResolver } from '@hookform/resolvers/zod';
import { ArrowLeft, ArrowRight, Edit, Loader2, PlusCircle } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useFieldArray, useForm } from 'react-hook-form';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';

const PASSO_ORIGEM = 1;
const PASSO_CLIENTE = 1.5;
const PASSO_ITENS = 2;

const itemVazio = () => ({
  product_id: null,
  quantidade: 1,
  descricao: '',
  sku: '',
  variacao: '',
  miolo_nome: '',
  id_produto_miolo: null,
  observacoes: '',
});

/** Converte um timestamp do backend para o formato do `datetime-local`. */
function paraDatetimeLocal(valor) {
  if (!valor) return '';
  const data = new Date(valor);
  if (Number.isNaN(data.getTime())) return '';
  const p = (n) => String(n).padStart(2, '0');
  return `${data.getFullYear()}-${p(data.getMonth() + 1)}-${p(data.getDate())}T${p(data.getHours())}:${p(data.getMinutes())}`;
}

async function buscarProdutoPorSku(sku) {
  try {
    const resposta = await fetch(`/api/v2/estoque/produtos-busca?q=${encodeURIComponent(sku)}&only_marketable=true`);
    const dados = await resposta.json();
    const item = dados.results?.[0];
    if (!item) return null;
    return {
      id: item.id,
      name: item.text.split(' - ').slice(1).join(' - ') || item.text,
      sku: item.text.split(' - ')[0] || '',
    };
  } catch (erro) {
    console.error('Erro ao buscar produto por SKU:', erro);
    return null;
  }
}

function NovaDemandaPage() {
  const { id } = useParams();
  const isEditing = !!id;
  const navigate = useNavigate();

  const [canais, setCanais] = useState([]);
  const [moduleIcons, setModuleIcons] = useState({});
  const [loadingInitialData, setLoadingInitialData] = useState(true);
  const [loadingSubmit, setLoadingSubmit] = useState(false);
  const [passo, setPasso] = useState(PASSO_ORIGEM);
  const [maiorVisitado, setMaiorVisitado] = useState(PASSO_ORIGEM);

  const hoje = useMemo(() => dataOperacionalHoje(), []);
  // Na edição, os prazos já gravados mandam: o automático só volta a agir
  // depois que o usuário mexer em canal, modalidade ou data.
  const autoPrazosAtivo = useRef(!isEditing);
  const schema = useMemo(() => criarDemandaSchema({ validarDataPassada: !isEditing }), [isEditing]);

  const form = useForm({
    resolver: zodResolver(schema),
    defaultValues: {
      fluxo_demanda: 'venda_diaria',
      nome: '',
      canal_venda_id: '',
      data_entrega: hoje,
      horario_coleta_especifico: '',
      data_finalizacao_prevista: '',
      observacoes: '',
      modalidade_logistica: 'STANDARD',
      classificacao_cliente: 'B2C',
      empresa_cliente_nome: '',
      empresa_wire_o_cor: '#000000',
      empresa_elastico_cor: '#000000',
      empresa_interacao_status: 'Aguardando arte',
      empresa_pedido_plataforma_numero: '',
      empresa_responsavel_id: '',
      empresa_responsavel_nome: '',
      itens: [itemVazio()],
    },
  });

  const { fields: itemFields, append: appendItem, remove: removeItem } = useFieldArray({
    control: form.control,
    name: 'itens',
  });

  const fluxo = form.watch('fluxo_demanda');
  const canalVendaId = form.watch('canal_venda_id');
  const modalidade = form.watch('modalidade_logistica');
  const dataEntrega = form.watch('data_entrega');
  const horarioColeta = form.watch('horario_coleta_especifico');
  const itens = form.watch('itens');
  const { dirtyFields } = form.formState;

  const canalSelecionado = useMemo(
    () => canais.find((canal) => String(canal.id) === canalVendaId) || null,
    [canais, canalVendaId]
  );

  const passos = useMemo(() => {
    const lista = [{ id: PASSO_ORIGEM, label: 'Origem e entrega' }];
    if (fluxo === 'venda_corporativa') lista.push({ id: PASSO_CLIENTE, label: 'Cliente' });
    lista.push({ id: PASSO_ITENS, label: 'Itens' });
    return lista;
  }, [fluxo]);

  useEffect(() => {
    const carregar = async () => {
      try {
        const [listaCanais, modulos] = await Promise.all([
          CanalVendaService.getAll(true),
          MarketplaceService.getAvailableModules().catch(() => []),
        ]);

        setCanais(listaCanais || []);
        setModuleIcons(
          Object.fromEntries((modulos || []).filter((m) => m.icon_url).map((m) => [m.slug, m.icon_url]))
        );

        if (isEditing) {
          const resposta = await fetch(`/api/v2/demanda_producao/${id}`);
          const dados = await resposta.json();

          if (!dados.success) {
            toast.error('Erro ao carregar dados da demanda.');
            navigate('/producao/demanda');
            return;
          }

          const d = dados.demanda;
          form.reset({
            fluxo_demanda: deriveDemandFlow(d),
            nome: d.nome || '',
            canal_venda_id: d.canal_venda_id ? String(d.canal_venda_id) : '',
            data_entrega: d.data_entrega ? d.data_entrega.split('T')[0] : '',
            horario_coleta_especifico: d.horario_coleta || '',
            data_finalizacao_prevista: paraDatetimeLocal(d.data_finalizacao_prevista),
            observacoes: d.observacoes || '',
            modalidade_logistica: d.modalidade_logistica || 'STANDARD',
            classificacao_cliente: d.classificacao_cliente || 'B2C',
            empresa_cliente_nome: d.empresa_cliente_nome || '',
            empresa_wire_o_cor: d.empresa_wire_o_cor || '#000000',
            empresa_elastico_cor: d.empresa_elastico_cor || '#000000',
            empresa_interacao_status: d.empresa_interacao_status || 'Aguardando arte',
            empresa_pedido_plataforma_numero: d.empresa_pedido_plataforma_numero || '',
            empresa_responsavel_id: d.empresa_responsavel_id ? String(d.empresa_responsavel_id) : '',
            empresa_responsavel_nome: d.empresa_responsavel_nome || '',
            itens: (d.itens || []).map((item) => ({
              product_id: item.product_id ? String(item.product_id) : null,
              quantidade: item.quantidade_total || item.quantidade || 1,
              descricao: item.descricao || '',
              sku: item.sku || '',
              variacao: item.variacao || '',
              miolo_nome: item.miolo_name || '',
              id_produto_miolo: item.id_produto_miolo ? String(item.id_produto_miolo) : null,
              observacoes: item.observacoes || '',
            })),
          });
          setMaiorVisitado(PASSO_ITENS);
        }
      } catch (erro) {
        toast.error(`Erro ao carregar dados iniciais: ${erro.message}`);
      } finally {
        setLoadingInitialData(false);
      }
    };

    carregar();
  }, [isEditing, id, form, navigate]);

  /**
   * Preenche horário de coleta e finalização prevista a partir do canal e da
   * modalidade. Campos tocados pelo usuário ficam intactos, a menos que ele
   * peça "Recalcular" (`forcar`). `resetField` mantém o estado dirty honesto:
   * preenchimento automático não suja o campo.
   */
  const aplicarPrazos = useCallback(
    ({ canal, modalidade: modalidadeAlvo, dataAlvo, forcar = false } = {}) => {
      if (!forcar && !autoPrazosAtivo.current) return;
      const canalAtual = canal ?? canalSelecionado;
      if (!canalAtual) return;

      const modalidadeAtual = modalidadeAlvo ?? form.getValues('modalidade_logistica');
      const data = dataAlvo ?? form.getValues('data_entrega');

      let horario = form.getValues('horario_coleta_especifico');
      if (forcar || !dirtyFields.horario_coleta_especifico) {
        const sugerido = sugerirHorarioColeta(canalAtual, modalidadeAtual);
        if (sugerido && sugerido !== horario) {
          form.resetField('horario_coleta_especifico', { defaultValue: sugerido });
          horario = sugerido;
        }
      }

      if (forcar || !dirtyFields.data_finalizacao_prevista) {
        const finalizacao = calcularFinalizacaoPrevista(data, horario);
        if (finalizacao && finalizacao !== form.getValues('data_finalizacao_prevista')) {
          form.resetField('data_finalizacao_prevista', { defaultValue: finalizacao });
        }
      }
    },
    [canalSelecionado, dirtyFields.horario_coleta_especifico, dirtyFields.data_finalizacao_prevista, form]
  );

  // Recalcula quando canal, modalidade, data ou horário mudam.
  useEffect(() => {
    if (!canalSelecionado) return;
    aplicarPrazos();
  }, [canalSelecionado, modalidade, dataEntrega, horarioColeta, aplicarPrazos]);

  /** Troca a data e devolve o controle ao preenchimento automático. */
  const alterarData = useCallback(
    (valor) => {
      autoPrazosAtivo.current = true;
      form.setValue('data_entrega', valor, { shouldDirty: true, shouldValidate: true });
    },
    [form]
  );

  const passoSeguinte = useCallback(
    (atual) => {
      if (atual === PASSO_ORIGEM) return fluxo === 'venda_corporativa' ? PASSO_CLIENTE : PASSO_ITENS;
      return PASSO_ITENS;
    },
    [fluxo]
  );

  const passoAnterior = useCallback(
    (atual) => {
      if (atual === PASSO_ITENS) return fluxo === 'venda_corporativa' ? PASSO_CLIENTE : PASSO_ORIGEM;
      return PASSO_ORIGEM;
    },
    [fluxo]
  );

  const irPara = useCallback((destino) => {
    setPasso(destino);
    setMaiorVisitado((anterior) => Math.max(anterior, destino));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, []);

  const avancar = useCallback(async () => {
    const campos = passo === PASSO_ORIGEM ? CAMPOS_POR_PASSO.origem : CAMPOS_POR_PASSO.cliente;
    const valido = await form.trigger(campos);
    if (!valido) return;
    irPara(passoSeguinte(passo));
  }, [form, irPara, passo, passoSeguinte]);

  /** Passo 1 já tem o necessário? Define se o clique no canal avança sozinho. */
  const origemCompleta = useCallback(() => {
    const valores = form.getValues();
    return Boolean(valores.nome?.trim() && valores.data_entrega && valores.canal_venda_id);
  }, [form]);

  const escolherFluxo = (fluxoId) => {
    const config = getDemandFlowConfig(fluxoId);
    autoPrazosAtivo.current = true;
    form.setValue('fluxo_demanda', fluxoId, { shouldDirty: true });
    form.setValue('classificacao_cliente', config.classificacao_cliente);
    form.setValue('modalidade_logistica', config.modalidade_logistica);
    if (canalSelecionado) {
      aplicarPrazos({ modalidade: config.modalidade_logistica });
    }
  };

  const escolherCanal = (canal) => {
    autoPrazosAtivo.current = true;
    form.setValue('canal_venda_id', String(canal.id), { shouldDirty: true, shouldValidate: true });

    const disponiveis = modalidadesDisponiveis(canal, fluxo);
    const modalidadeAtual = form.getValues('modalidade_logistica');
    const modalidadeFinal = disponiveis.includes(modalidadeAtual) ? modalidadeAtual : disponiveis[0];
    form.setValue('modalidade_logistica', modalidadeFinal);

    aplicarPrazos({ canal, modalidade: modalidadeFinal });

    // "Avançar ao clicar": se o passo já está completo, segue; senão, o foco
    // vai para o único campo que ainda falta digitar.
    if (origemCompleta()) {
      irPara(passoSeguinte(PASSO_ORIGEM));
    } else {
      form.setFocus('nome');
    }
  };

  const escolherModalidade = (novaModalidade) => {
    autoPrazosAtivo.current = true;
    form.setValue('modalidade_logistica', novaModalidade, { shouldDirty: true });
    aplicarPrazos({ modalidade: novaModalidade });
    if (origemCompleta()) irPara(passoSeguinte(PASSO_ORIGEM));
  };

  const selecionarProduto = useCallback(
    async (index, produto) => {
      form.setValue(`itens.${index}.product_id`, String(produto.id));
      form.setValue(`itens.${index}.descricao`, produto.name);
      form.setValue(`itens.${index}.sku`, produto.sku);

      try {
        const resposta = await fetch(`/api/v2/demanda_producao/products/${produto.id}/default-miolo`);
        const dados = await resposta.json();

        if (dados.success && dados.miolo) {
          form.setValue(`itens.${index}.miolo_nome`, dados.miolo.nome);
          form.setValue(`itens.${index}.id_produto_miolo`, String(dados.miolo.id));
          return;
        }
      } catch (erro) {
        console.error('Erro ao buscar miolo padrão:', erro);
      }

      form.setValue(`itens.${index}.miolo_nome`, '');
      form.setValue(`itens.${index}.id_produto_miolo`, '');
    },
    [form]
  );

  const colarItens = async () => {
    if (!navigator.clipboard?.readText) {
      toast.error('Seu navegador não suporta leitura da área de transferência. Tente usar HTTPS.');
      return;
    }

    try {
      const texto = await navigator.clipboard.readText();
      if (!texto) {
        toast.warning('Área de transferência vazia.');
        return;
      }

      const novosItens = texto
        .split(/\r?\n/)
        .filter((linha) => linha.trim() !== '')
        .map((linha) => {
          const colunas = linha.split('\t');
          // Colunas esperadas: item, sku, variação, miolo, quantidade
          const descricao = colunas[0]?.trim() || '';
          const sku = colunas[1]?.trim() || '';
          const quantidade = parseInt(colunas[4]?.trim() || '1', 10);

          if (!descricao && !sku) return null;

          return {
            ...itemVazio(),
            descricao: descricao || sku,
            sku,
            variacao: colunas[2]?.trim() || '',
            miolo_nome: colunas[3]?.trim() || '',
            quantidade: Number.isNaN(quantidade) ? 1 : quantidade,
          };
        })
        .filter(Boolean);

      if (novosItens.length === 0) {
        toast.warning('Nenhum item válido encontrado. Os dados precisam estar separados por TAB.');
        return;
      }

      // Descarta a linha vazia inicial antes de anexar.
      const atuais = form.getValues('itens');
      if (atuais.length === 1 && !atuais[0].descricao && !atuais[0].sku) removeItem(0);

      const deslocamento = form.getValues('itens').length;
      appendItem(novosItens);

      for (let i = 0; i < novosItens.length; i += 1) {
        const { sku } = novosItens[i];
        if (!sku) continue;
        const produto = await buscarProdutoPorSku(sku);
        if (produto) await selecionarProduto(deslocamento + i, produto);
      }

      toast.success(`${novosItens.length} itens adicionados da planilha!`);
    } catch (erro) {
      console.error('Falha ao ler a área de transferência:', erro);
      toast.error(`Erro ao ler da área de transferência: ${erro?.message || erro}`);
    }
  };

  const enviar = async (valores, isDraft) => {
    setLoadingSubmit(true);
    try {
      const url = isEditing ? `/api/v2/demanda_producao/${id}` : urlCriacaoDemanda(valores.fluxo_demanda);
      const resposta = await fetch(url, {
        method: isEditing ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(montarPayloadDemanda(valores, { isDraft })),
      });

      if (!resposta.ok) {
        const erro = await resposta.json().catch(() => ({}));
        throw new Error(erro.message || 'Erro ao salvar demanda.');
      }

      const resultado = await resposta.json();
      toast.success(resultado.message || 'Demanda salva com sucesso!');
      navigate('/producao/demanda');
    } catch (erro) {
      toast.error(`Erro: ${erro.message}`);
    } finally {
      setLoadingSubmit(false);
    }
  };

  // Enter avança o passo; no último, envia.
  const onSubmitForm = (evento) => {
    evento.preventDefault();
    if (passo === PASSO_ITENS) {
      form.handleSubmit((valores) => enviar(valores, false))(evento);
      return;
    }
    avancar();
  };

  if (loadingInitialData) {
    return (
      <div className="flex justify-center py-10">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  const prazosSobrescritos = Boolean(
    dirtyFields.horario_coleta_especifico || dirtyFields.data_finalizacao_prevista
  );

  return (
    <div className="mx-auto w-full max-w-[1800px] space-y-4 py-2">
      <PageHeader
        title={isEditing ? 'Editar Demanda' : 'Nova Demanda'}
        icon={isEditing ? Edit : PlusCircle}
        description={getDemandFlowConfig(fluxo).description}
        actions={
          <Button variant="outline" onClick={() => navigate('/producao/demanda')}>
            Voltar
          </Button>
        }
      />

      <TrilhaPassos
        passos={passos}
        atual={passo}
        maiorVisitado={maiorVisitado}
        onSelecionar={setPasso}
        liberarTodos={isEditing}
      />

      {passo !== PASSO_ORIGEM && (
        <ResumoDemanda
          canal={canalSelecionado}
          modalidade={modalidade}
          dataEntrega={dataEntrega}
          horarioColeta={horarioColeta}
          totalItens={(itens || []).length}
          onVoltarParaOrigem={() => setPasso(PASSO_ORIGEM)}
        />
      )}

      <Form {...form}>
        <form onSubmit={onSubmitForm} className="space-y-6">
          <Card>
            <CardContent className="py-4">
              {passo === PASSO_ORIGEM && (
                <PassoOrigem
                  form={form}
                  canais={canais}
                  moduleIcons={moduleIcons}
                  hoje={hoje}
                  canalSelecionado={canalSelecionado}
                  fluxo={fluxo}
                  modalidade={modalidade}
                  onEscolherFluxo={escolherFluxo}
                  onEscolherCanal={escolherCanal}
                  onEscolherModalidade={escolherModalidade}
                  onAlterarData={alterarData}
                  onRecalcularPrazos={() => aplicarPrazos({ forcar: true })}
                  prazosSobrescritos={prazosSobrescritos}
                />
              )}

              {passo === PASSO_CLIENTE && <PassoCliente form={form} />}

              {passo === PASSO_ITENS && (
                <PassoItens
                  form={form}
                  itemFields={itemFields}
                  onAdicionarItem={() => appendItem(itemVazio())}
                  onRemoverItem={removeItem}
                  onColarItens={colarItens}
                  onSelecionarProduto={selecionarProduto}
                />
              )}
            </CardContent>
          </Card>

          <div className="flex flex-col gap-3 sm:flex-row sm:justify-between">
            <Button
              type="button"
              variant="outline"
              disabled={passo === PASSO_ORIGEM}
              onClick={() => irPara(passoAnterior(passo))}
            >
              <ArrowLeft className="mr-2 h-4 w-4" /> Voltar
            </Button>

            {passo === PASSO_ITENS ? (
              <div className="flex flex-col gap-3 sm:flex-row">
                <Button
                  type="button"
                  variant="secondary"
                  disabled={loadingSubmit}
                  onClick={form.handleSubmit((valores) => enviar(valores, true))}
                >
                  {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  {isEditing ? 'Salvar alterações no rascunho' : 'Salvar como rascunho'}
                </Button>
                <Button type="submit" disabled={loadingSubmit} className="shadow-md">
                  {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  {isEditing ? 'Atualizar e publicar' : 'Criar demanda'}
                </Button>
              </div>
            ) : (
              <Button type="submit">
                Próximo <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            )}
          </div>
        </form>
      </Form>
    </div>
  );
}

export default NovaDemandaPage;
