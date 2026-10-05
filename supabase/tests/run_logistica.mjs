// npm install --prefix temp/logistica-sql @electric-sql/pglite
// node supabase/tests/run_logistica.mjs (a partir da raiz do repositorio)
import { readFile } from 'node:fs/promises';
import { PGlite } from '../../temp/logistica-sql/node_modules/@electric-sql/pglite/dist/index.js';
const db = new PGlite();
try {
  for (const file of [
    'supabase/tests/fixtures/logistica_schema.sql',
    'supabase/migrations/20261002120000_logistica_agenda_e_alertas.sql',
    'supabase/migrations/20261002121000_logistica_manutencao_transacional.sql',
    'supabase/tests/logistica_agenda_e_alertas.sql',
  ]) {
    try { await db.exec(await readFile(file, 'utf8')); console.log(`OK: ${file}`); }
    catch (error) { console.error(file, error.message, error.where || '', error.position || ''); process.exitCode=1; break; }
  }
} finally { await db.close(); }
