import { z } from "zod";

export const productSchema = z.object({
  sku: z.string().min(1, { message: "SKU é obrigatório." }),
  name: z.string().min(1, { message: "Nome do produto é obrigatório." }),
  description: z.string().optional(),
  category_id: z.string().min(1, { message: "Categoria é obrigatória." }),
  unit_of_measure_id: z.string().min(1, { message: "Unidade de medida é obrigatória." }),
  setor_responsavel_id: z.string().optional(), // Campo opcional para setor responsável
  cost_price: z.preprocess(
    (a) => parseFloat(a),
    z.number().min(0, { message: "Preço de custo não pode ser negativo." }).or(z.literal('')) // Handle empty string for input field
  ).transform((a) => (a === '' ? 0 : a)), // Transform empty string to 0 or appropriate default
  stock_min: z.preprocess(
    (a) => parseInt(a, 10),
    z.number().int().min(0, { message: "Estoque mínimo não pode ser negativo." }).optional().nullable().or(z.literal(''))
  ).transform((a) => (a === '' ? null : a)),
  stock_max: z.preprocess(
    (a) => parseInt(a, 10),
    z.number().int().min(0, { message: "Estoque máximo não pode ser negativo." }).optional().nullable().or(z.literal(''))
  ).transform((a) => (a === '' ? null : a)),
  material_type: z.enum(["materia_prima", "intermediario", "produto_acabado", "servico"], { message: "Nível do produto inválido." }),
  requires_personalization: z.boolean().default(false),
  status: z.enum(["ativo", "rascunho", "inativo"], { message: "Status inválido." }),
  estagio: z.enum(["RASCUNHO", "ARTE_PENDENTE", "ARTE_OK", "FICHA_OK", "CANAL_OK", "PUBLICADO", "DESCONTINUADO"]).default('RASCUNHO'),
  formato: z.enum(["simples", "com_variacao", "variacao", "composicao", "kit"], { message: "Formato do produto inválido." }),
  herdar_dados_pai: z.boolean().default(true),
  herdar_bom_pai: z.boolean().default(true),
  ncm: z.string().regex(/^$|^\d{8}$/, { message: 'NCM deve ter 8 dígitos.' }).optional(),
  cest: z.string().regex(/^$|^\d{7}$/, { message: 'CEST deve ter 7 dígitos.' }).optional(),
  origem_mercadoria: z.coerce.number().int().min(0).max(8).optional().nullable(),
  cfop_padrao_venda: z.string().regex(/^$|^\d{4}$/, { message: 'CFOP deve ter 4 dígitos.' }).optional(),
  gtin: z.string().optional(),
  gtin_embalagem: z.string().optional(),
  marca: z.string().optional(),
  fabricante: z.string().optional(),
  mpn: z.string().optional(),
  peso_liquido: z.coerce.number().min(0).optional().nullable(),
  peso_bruto: z.coerce.number().min(0).optional().nullable(),
  comprimento: z.coerce.number().min(0).optional().nullable(),
  largura: z.coerce.number().min(0).optional().nullable(),
  altura: z.coerce.number().min(0).optional().nullable(),
  garantia_meses: z.coerce.number().int().min(0).optional().nullable(),
  perfil_fiscal_id: z.coerce.number().int().positive().optional().nullable(),
  origem_fiscal: z.enum(['interno', 'espelho_bling']).default('interno'),
  external_product_links: z.object({
    skus: z.array(z.string()).optional(),
    names: z.array(z.string()).optional(),
    ids: z.array(z.string()).optional(),
  }).optional(),
});
