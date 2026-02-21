import { z } from 'zod';

export const sectorSchema = z.object({
  nome: z.string().min(1, { message: 'Nome é obrigatório' }),
  descricao: z.string().optional(),
  ativo: z.boolean().default(true),
});
