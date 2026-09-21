import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, X } from 'lucide-react';
import { supabase } from '@/lib/supabase';
import { calcularRestante, formatarRestante } from '@/lib/alertaTurbo';

/**
 * Faixa de alerta das modalidades de prazo relativo (Turbo).
 *
 * A faixa reflete estado, não evento: aparece enquanto existir Turbo pendente e
 * some sozinha quando o último sai. O operador pode fechá-la para a carga atual;
 * ao recarregar a página, a fila pendente volta a ser exibida.
 *
 * "Pendente" é definido pela RPC como "não está em demanda publicada" — e não
 * por `despachado_em`. Um Turbo dentro de um rascunho ainda não foi entregue ao
 * atendimento: alguém começou a montar o lote e pode não ter terminado. A faixa
 * muda de texto nesse caso, mas não some.
 *
 * O relógio é recalculado no cliente a cada segundo a partir de
 * `compromisso_em`, não do `minutos_restantes` devolvido pela RPC: a contagem
 * precisa continuar correndo entre um refetch e outro.
 */
const REFETCH_MS = 60_000;

export default function AlertaTurbo() {
  const [pedidos, setPedidos] = useState([]);
  const [agora, setAgora] = useState(() => Date.now());
  const [fechado, setFechado] = useState(false);
  const carregandoRef = useRef(false);

  const carregar = useCallback(async () => {
    if (carregandoRef.current) return;
    carregandoRef.current = true;
    try {
      const resposta = await fetch('/api/v2/despacho/esteira');
      const json = await resposta.json();
      if (resposta.ok && json.success) setPedidos(json.data?.pedidos || []);
    } finally {
      carregandoRef.current = false;
    }
  }, []);

  useEffect(() => {
    carregar();
    const intervalo = setInterval(carregar, REFETCH_MS);
    return () => clearInterval(intervalo);
  }, [carregar]);

  // Realtime: um Turbo que entra precisa aparecer em segundos, não no próximo
  // refetch. O filtro fino fica na RPC — aqui só se sabe que algo mudou.
  useEffect(() => {
    const canal = supabase
      .channel('turbo-esteira')
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'pedidos' }, carregar)
      .on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'pedidos' }, carregar)
      // A saída da fila acontece na demanda, não no pedido: publicar um
      // rascunho não altera nenhuma linha de `pedidos`. Sem escutar aqui, a
      // faixa só sumiria no refetch de um minuto depois.
      .on('postgres_changes', { event: '*', schema: 'public', table: 'demandas_producao' }, carregar)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'demandas_pedidos' }, carregar)
      .subscribe();
    return () => { supabase.removeChannel(canal); };
  }, [carregar]);

  useEffect(() => {
    if (pedidos.length === 0) return undefined;
    const tick = setInterval(() => setAgora(Date.now()), 1000);
    return () => clearInterval(tick);
  }, [pedidos.length]);

  if (pedidos.length === 0 || fechado) return null;

  const urgente = pedidos[0];
  const restante = calcularRestante(urgente.compromisso_em, agora);
  const atrasado = Number.isFinite(restante) && restante < 0;

  return (
    <div
      role="alert"
      aria-live="assertive"
      className={`w-full text-white ${atrasado ? 'bg-red-700' : 'bg-red-600'}`}
    >
      {/* Aponta para a torre. A esteira FIFO de prazo relativo (/despacho/esteira,
          spec "Modalidades de prazo relativo") ainda nao existe; quando existir,
          este link muda para la — e so ele. */}
      <div className="flex items-stretch">
        <Link
          to="/despacho"
          className="flex min-w-0 flex-1 items-center gap-3 px-4 py-2 text-sm font-medium hover:bg-red-800 transition-colors"
        >
          <AlertTriangle className={`w-4 h-4 shrink-0 ${atrasado ? 'animate-pulse' : ''}`} />
          <span className="font-semibold uppercase tracking-wide">
            {pedidos.length === 1 ? 'Novo Turbo' : `${pedidos.length} Turbos pendentes`}
          </span>
          <span className="truncate opacity-90">
            Pedido {urgente.numero_pedido} · {urgente.marketplace_nome?.trim()}
          </span>
          {urgente.em_rascunho && (
            <span className="shrink-0 rounded bg-white/20 px-1.5 py-0.5 text-xs">
              consolidado — ainda não publicado
            </span>
          )}
          <span className="ml-auto flex shrink-0 items-center gap-3">
            <span className="tabular-nums font-mono text-base">{formatarRestante(restante)}</span>
            <span className="underline underline-offset-2 opacity-90">ver na torre</span>
          </span>
        </Link>
        <button
          type="button"
          aria-label="Fechar alerta Turbo"
          title="Fechar alerta"
          onClick={() => setFechado(true)}
          className="flex w-10 shrink-0 items-center justify-center hover:bg-red-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-white"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
