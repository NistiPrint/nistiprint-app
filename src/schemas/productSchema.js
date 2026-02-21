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
  formato: z.enum(["simples", "com_variacao", "variacao", "composicao", "kit"], { message: "Formato do produto inválido." }),
  herdar_dados_pai: z.boolean().default(true),
  herdar_bom_pai: z.boolean().default(true),
  external_product_links: z.object({
    skus: z.array(z.string()).optional(),
    names: z.array(z.string()).optional(),
    ids: z.array(z.string()).optional(),
  }).optional(),
  artworks: z.array(z.object({
    id: z.string(),
    filename: z.string(),
    original_filename: z.string(),
    file_path: z.string(),
    file_size: z.number(),
    mime_type: z.string(),
    upload_date: z.string(),
  })).optional(),
});
