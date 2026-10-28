import { horarioJaPassou } from '@/lib/novaDemanda';
import { getDemandFlowConfig } from '@/lib/demandaFlow';
import { z } from 'zod';

export const INTERACAO_STATUS_OPTIONS = [
  'Aguardando arte',
  'Aguardando prévia',
  'Aguardando aprovação',
  'Aprovado',
];

export const itemSchema = z.object({
  product_id: z.string().optional().nullable(),
  quantidade: z.preprocess(
    (valor) => Number(valor),
    z.number().min(1, { message: 'Qtd deve ser >= 1.' })
  ),
  descricao: z.string().min(1, { message: 'Descrição é obrigatória.' }),
  sku: z.string().optional(),
  variacao: z.string().optional(),
  miolo_nome: z.string().optional(),
  id_produto_miolo: z.string().optional().nullable(),
  observacoes: z.string().optional(),
});

/** Campos validados em cada passo, para o `form.trigger` da navegação. */
export const CAMPOS_POR_PASSO = {
  origem: [
    'fluxo_demanda',
    'canal_venda_id',
    'modalidade_logistica',
    'data_entrega',
    'horario_coleta_especifico',
    'nome',
  ],
  cliente: ['empresa_cliente_nome', 'empresa_responsavel_nome'],
  itens: ['itens'],
};

/**
 * `validarDataPassada` fica desligado na edição: o backend também não checa no
 * PUT, e bloquear impediria corrigir uma demanda antiga.
 */
export function criarDemandaSchema({ validarDataPassada = true } = {}) {
  return z
    .object({
      fluxo_demanda: z
        .enum(['venda_diaria', 'fulfillment', 'venda_corporativa', 'producao_interna'])
        .default('venda_diaria'),
      nome: z.string().min(1, { message: 'Nome da demanda é obrigatório.' }),
      canal_venda_id: z.string().min(1, { message: 'Canal / origem é obrigatório.' }),
      data_entrega: z.string().min(1, { message: 'Data de entrega é obrigatória.' }),
      horario_coleta_especifico: z.string().optional(),
      data_finalizacao_prevista: z.string().optional(),
      observacoes: z.string().optional(),

      modalidade_logistica: z
        .enum(['STANDARD', 'EXPRESS', 'FULFILLMENT', 'RETIRADA'], {
          message: 'Modalidade logística é obrigatória.',
        })
        .default('STANDARD'),
      classificacao_cliente: z
        .enum(['B2C', 'B2B', 'INTERNO'], { message: 'Classificação do cliente é obrigatória.' })
        .default('B2C'),

      empresa_cliente_nome: z.string().optional(),
      empresa_wire_o_cor: z.string().optional(),
      empresa_elastico_cor: z.string().optional(),
      empresa_interacao_status: z.string().optional(),
      empresa_pedido_plataforma_numero: z.string().optional(),
      empresa_responsavel_id: z.string().optional(),
      empresa_responsavel_nome: z.string().optional(),

      itens: z.array(itemSchema).min(1, { message: 'É necessário pelo menos um item.' }),
    })
    .superRefine((data, ctx) => {
      if (getDemandFlowConfig(data.fluxo_demanda).tipo_demanda === 'B2B') {
        if (!data.empresa_cliente_nome) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: 'Empresa / cliente é obrigatório para demandas B2B.',
            path: ['empresa_cliente_nome'],
          });
        }
        if (!data.empresa_responsavel_nome) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: 'Responsável é obrigatório para demandas B2B.',
            path: ['empresa_responsavel_nome'],
          });
        }
      }

      // O backend recusa entrega no passado com 400; avisamos antes de enviar.
      if (validarDataPassada && horarioJaPassou(data.data_entrega, data.horario_coleta_especifico)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: data.horario_coleta_especifico
            ? 'Esta janela de coleta já passou. Escolha outro horário ou outro dia.'
            : 'A data de entrega já passou. Escolha outro dia.',
          path: [data.horario_coleta_especifico ? 'horario_coleta_especifico' : 'data_entrega'],
        });
      }
    });
}
