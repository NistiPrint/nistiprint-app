import { z } from 'zod';

export const userSchema = z.object({
  nome: z.string().min(1, { message: 'Nome é obrigatório' }),
  email: z.string().email({ message: 'Email inválido' }),
  senha: z.string().min(6, { message: 'Senha deve ter pelo menos 6 caracteres' }).optional(),
  setor_id: z.union([z.string(), z.number()]).transform((val) => {
    if (typeof val === 'string' && val === '') return undefined;
    return typeof val === 'string' ? parseInt(val) : val;
  }).refine((val) => val !== undefined && !isNaN(val), { message: 'Setor é obrigatório' }),
  ativo: z.boolean().default(true),
  is_admin: z.boolean().default(false),
});

export const userUpdateSchema = z.object({
  nome: z.string().min(1, { message: 'Nome é obrigatório' }),
  email: z.string().email({ message: 'Email inválido' }),
  senha: z.string().optional(),
  setor_id: z.union([z.string(), z.number()]).transform((val) => {
    if (typeof val === 'string' && val === '') return undefined;
    return typeof val === 'string' ? parseInt(val) : val;
  }).refine((val) => val !== undefined && !isNaN(val), { message: 'Setor é obrigatório' }),
  ativo: z.boolean().default(true),
  is_admin: z.boolean().default(false),
});
