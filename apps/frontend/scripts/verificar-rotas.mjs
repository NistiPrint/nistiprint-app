#!/usr/bin/env node
// Verificador de cobertura de navegacao (regra R3 do Plano de Otimizacao).
//
// Confere nos dois sentidos:
//   1. todo href declarado em src/navigation.js aponta para uma rota real;
//   2. toda rota de App.jsx tem link de menu, ou esta declarada abaixo como
//      alcancavel por dentro da tela (detalhe, formulario, redirect).
//
// Sem dependencias: le os dois arquivos como texto. Roda com `npm run
// verificar:rotas` e serve tanto local quanto em CI.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const raiz = join(dirname(fileURLToPath(import.meta.url)), '..');

// Rotas que existem de proposito sem entrada de menu: sao alcancadas a partir
// de uma listagem, de um botao ou de um fluxo. Acrescentar aqui e uma decisao
// consciente; o teste falha para qualquer rota nova fora desta lista.
const ROTAS_SEM_MENU = new Set([
  '/login',
  '/perfil',
  '/consolidar/revisao',
  '/despacho/escopo',
  '/producao/foco',
  '/producao/resumo',
  '/producao/demanda/prioridade',
  '/producao/demanda/calendario',
  '/estoque/dashboard',
  '/configuracoes/demanda-permissions',
  '/relatorios/index',
  // Raizes de layout: o filho index redireciona, ninguem aterrissa aqui.
  '/vendas',
  '/cadastros',
  '/configuracoes',
]);

function lerRotas(origem) {
  const rotas = [];
  const pilha = [];
  const re = /<Route\b|<\/Route>/g;
  let m;
  while ((m = re.exec(origem)) !== null) {
    if (m[0] === '</Route>') { pilha.pop(); continue; }

    // Le a tag ate o '>' que a fecha. Precisa ignorar '>' dentro de aspas e,
    // sobretudo, dentro de {expressoes JSX}: em
    // <Route path='vendas' element={<VendasPage />}> o primeiro '>' pertence
    // a <VendasPage />, e parar ali faria a rota parecer auto-fechada — os
    // filhos perderiam o prefixo do pai.
    let i = m.index + m[0].length;
    let aspas = null;
    let chaves = 0;
    while (i < origem.length) {
      const c = origem[i];
      if (aspas) { if (c === aspas) aspas = null; }
      else if (c === "'" || c === '"') aspas = c;
      else if (c === '{') chaves++;
      else if (c === '}') chaves--;
      else if (c === '>' && chaves === 0) break;
      i++;
    }
    const tag = origem.slice(m.index, i + 1);
    const autoFechada = /\/\s*>$/.test(tag);
    const path = (tag.match(/path=['"]([^'"]+)['"]/) || [])[1];
    const ehIndex = /\bindex\b/.test(tag.split('element')[0]);
    const ehRedirect = /<Navigate\b/.test(tag);

    const segmentos = pilha.filter(Boolean);
    let completa;
    if (path === undefined) completa = '/' + segmentos.join('/');
    else if (path.startsWith('/')) completa = path;
    else completa = '/' + [...segmentos, path].join('/');
    completa = ('/' + completa.split('/').filter(Boolean).join('/')) || '/';

    if ((path !== undefined || ehIndex) && !ehRedirect) rotas.push(completa);
    if (!autoFechada) pilha.push(path === undefined ? '' : path.replace(/^\//, ''));
  }
  return [...new Set(rotas)];
}

function lerHrefs(origem) {
  return [...new Set([...origem.matchAll(/href:\s*'([^']+)'/g)].map((m) => m[1]))];
}

const rotas = lerRotas(readFileSync(join(raiz, 'src/App.jsx'), 'utf8'));
const hrefs = lerHrefs(readFileSync(join(raiz, 'src/navigation.js'), 'utf8'));

const dinamica = (r) => r.includes(':');
// Telas de criacao sao abertas pelo botao da listagem correspondente.
const ehFormularioDeCriacao = (r) => /\/(novo|nova|new)$/.test(r);
const rotasFixas = rotas.filter((r) => !dinamica(r) && !ehFormularioDeCriacao(r));

const linksQuebrados = hrefs.filter((h) => !rotas.includes(h));
const rotasOrfas = rotasFixas.filter((r) => !hrefs.includes(r) && !ROTAS_SEM_MENU.has(r));
const permissoesObsoletas = [...ROTAS_SEM_MENU].filter((r) => !rotasFixas.includes(r));

const problemas = [];
if (linksQuebrados.length) problemas.push(['Link de menu sem rota correspondente', linksQuebrados]);
if (rotasOrfas.length) problemas.push(['Rota sem link de menu e fora de ROTAS_SEM_MENU', rotasOrfas]);
if (permissoesObsoletas.length) problemas.push(['Entrada obsoleta em ROTAS_SEM_MENU (a rota nao existe mais)', permissoesObsoletas]);

console.log(`rotas em App.jsx: ${rotas.length} (${rotasFixas.length} fixas)`);
console.log(`hrefs em navigation.js: ${hrefs.length}`);

if (!problemas.length) {
  console.log('\nOK: navegacao coerente nos dois sentidos.');
  process.exit(0);
}
for (const [titulo, itens] of problemas) {
  console.error(`\n${titulo}:`);
  for (const i of itens) console.error(`  - ${i}`);
}
process.exit(1);
