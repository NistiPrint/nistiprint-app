import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { ArrowLeft, FileUp, Loader2 } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useSecaoSidebar } from '@/lib/hooks/useSecaoSidebar';

// Conferir arquivo — a porta de entrada do lote vindo de planilha.
//
// Esta tela faz UMA coisa: ler o arquivo, aplicar o filtro e casar os IDs de
// origem com os pedidos da base. Feito isso ela sai da frente e leva o operador
// ao escopo, que e onde o lote e consolidado, impresso, faturado e publicado —
// exatamente a mesma tela do lote aberto pelo card da torre, porque o objetivo
// e o mesmo.
//
// Ela nao mostra o resultado da conferencia. Antes mostrava, e o operador
// terminava numa pagina de estatistica que exigia mais um clique para chegar
// onde ele queria desde o inicio. Os numeros da conferencia continuam
// visiveis — dentro do escopo, junto do lote que eles descrevem.

const PLATAFORMAS = [
  { id: 'shopee', nome: 'Shopee' },
  { id: 'mercadolivre', nome: 'Mercado Livre' },
  { id: 'amazon', nome: 'Amazon' },
  { id: 'shein', nome: 'Shein' },
];

// Os padroes reproduzem o que o legado filtrava sem perguntar. Abrir a tela,
// escolher o arquivo e enviar tem que dar o mesmo conjunto de sempre.
const padrao = (moduleId) => ({
  ...(moduleId === 'shopee' ? { modalidade: 'comum', ja_rastreado: true } : {}),
  ...(moduleId === 'mercadolivre' ? { estado: 'valido' } : {}),
  ...(moduleId === 'shein' ? { ja_rastreado: true } : {}),
});

export default function ArquivoDespachoPage() {
  useSecaoSidebar();
  const navigate = useNavigate();
  const [moduleId, setModuleId] = useState('shopee');
  const [file, setFile] = useState(null);
  const [filtro, setFiltro] = useState(padrao('shopee'));
  const [enviando, setEnviando] = useState(false);

  const trocarPlataforma = (value) => {
    setModuleId(value);
    setFiltro(padrao(value));
  };

  const conferir = async () => {
    if (!file) {
      toast.warning('Escolha um arquivo para conferir.');
      return;
    }
    setEnviando(true);
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('module_id', moduleId);
      form.append('filtro', JSON.stringify(filtro));
      const res = await fetch('/api/v2/despacho/arquivo/conferir', { method: 'POST', body: form });
      const json = await res.json();
      if (!json.success) throw new Error(json.error || 'Falha ao conferir o arquivo');

      const { conferencia_id: id, funil, arquivo_nome: nome } = json.data;
      // Zero pedidos na torre quase sempre e filtro errado ou plataforma
      // errada, nao base vazia. Segurar aqui, com o numero na frente, evita
      // mandar o operador para um escopo vazio sem explicacao.
      if (!funil?.na_torre) {
        toast.warning(
          `Nenhum pedido de ${nome} está pendente na torre. ` +
          `Foram lidas ${funil?.linhas ?? 0} linhas e ${funil?.refs ?? 0} pedidos passaram no filtro.`
        );
      }
      navigate(`/despacho/escopo?conferencia_id=${id}`);
    } catch (error) {
      toast.error(error.message);
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div className="p-6">
      <button
        type="button"
        onClick={() => navigate('/despacho')}
        className="mb-4 flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Voltar para a torre de despacho
      </button>

      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Conferir arquivo do marketplace</h1>
          <p className="text-sm text-muted-foreground">
            O filtro define o lote. Ao enviar, você vai direto para a consolidação.
          </p>
        </div>
        <FileUp className="h-6 w-6 text-muted-foreground" />
      </div>

      <Card className="max-w-3xl">
        <CardHeader>
          <CardTitle className="text-base">Arquivo e filtro</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span className="font-medium">Plataforma</span>
              <select
                value={moduleId}
                onChange={(event) => trocarPlataforma(event.target.value)}
                className="flex h-10 w-full rounded-md border bg-background px-3 text-sm"
              >
                {PLATAFORMAS.map((p) => (
                  <option key={p.id} value={p.id}>{p.nome}</option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-medium">Arquivo</span>
              <Input
                type="file"
                accept=".xlsx,.xls,.csv"
                onChange={(event) => setFile(event.target.files?.[0] || null)}
              />
            </label>
          </div>

          {/* Os filtros que existiam desde o legado, agora visiveis. Flex e
              comum particionam o arquivo: eles saem em caminhoes diferentes,
              entao sao dois lotes, nunca um. */}
          {moduleId === 'shopee' && (
            <div className="grid gap-4 md:grid-cols-2">
              <label className="space-y-1 text-sm">
                <span className="font-medium">Modalidade</span>
                <select
                  value={filtro.modalidade || 'comum'}
                  onChange={(event) => setFiltro((old) => ({ ...old, modalidade: event.target.value }))}
                  className="flex h-10 w-full rounded-md border bg-background px-3 text-sm"
                >
                  <option value="comum">Lote comum (exclui Entrega Rápida, Full e Estoque)</option>
                  <option value="flex">Entrega Rápida (Flex)</option>
                  <option value="tudo">Sem filtro de modalidade</option>
                </select>
              </label>
              <label className="flex items-center gap-2 pt-6 text-sm">
                <input
                  type="checkbox"
                  checked={filtro.ja_rastreado !== false}
                  onChange={(event) => setFiltro((old) => ({ ...old, ja_rastreado: event.target.checked }))}
                />
                Ocultar pedidos já com rastreio
              </label>
            </div>
          )}

          {moduleId === 'mercadolivre' && (
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={filtro.estado !== 'todos'}
                onChange={(event) => setFiltro((old) => ({ ...old, estado: event.target.checked ? 'valido' : 'todos' }))}
              />
              Apenas estados elegíveis para despacho
            </label>
          )}

          {moduleId === 'shein' && (
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={filtro.ja_rastreado !== false}
                onChange={(event) => setFiltro((old) => ({ ...old, ja_rastreado: event.target.checked }))}
              />
              Ocultar pedidos já com rastreio
            </label>
          )}

          <div className="grid gap-4 md:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span className="font-medium">Prazo de envio — de (opcional)</span>
              <Input
                type="date"
                value={filtro.periodo?.inicio || ''}
                onChange={(event) => setFiltro((old) => ({ ...old, periodo: { ...old.periodo, inicio: event.target.value } }))}
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-medium">Prazo de envio — até (opcional)</span>
              <Input
                type="date"
                value={filtro.periodo?.fim || ''}
                onChange={(event) => setFiltro((old) => ({ ...old, periodo: { ...old.periodo, fim: event.target.value } }))}
              />
            </label>
          </div>

          <Button onClick={conferir} disabled={enviando} size="lg" className="gap-2">
            {enviando ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileUp className="h-4 w-4" />}
            {enviando ? 'Conferindo…' : 'Conferir e consolidar'}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
