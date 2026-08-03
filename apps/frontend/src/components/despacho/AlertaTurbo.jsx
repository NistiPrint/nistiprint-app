import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle } from 'lucide-react';
import { supabase } from '@/lib/supabase';

/**
 * Faixa de alerta das modalidades de prazo relativo (Turbo).
 *
 * A faixa reflete estado, não evento: aparece enquanto existir Turbo pendente e
 * some sozinha quando o último sai. Não há botão de dispensar de propósito —
 * não se dispensa um prazo que continua correndo. Um Turbo tem 40 minutos, e um
 * alerta que o operador pode fechar é um alerta que ele vai fechar.
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

function formatarRestante(ms) {
  const negativo = ms < 0;
  const total = Math.floor(Math.abs(ms) / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const corpo = h > 0
    ? `${h}h${String(m).padStart(2, '0')}`
    : `${m}:${String(s).padStart(2, '0')}`;
  return negativo ? `atrasado há ${corpo}` : corpo;
}

export default function AlertaTurbo() {
  const [pedidos, setPedidos] = useState([]);
  const [agora, setAgora] = useState(() => Date.now());
  const carregandoRef = useRef(false);

  const carregar = useCallback(async () => {
    if (carregandoRef.current) return;
    carregandoRef.current = true;
    try {
      const { data, error } = await supabase.rpc('despacho_esteira_relativo');
      if (!error) setPedidos(data || []);
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

  if (pedidos.length === 0) return null;

  const urgente = pedidos[0];
  const restante = new Date(urgente.compromisso_em).getTime() - agora;
  const atrasado = restante < 0;

  return (
    <div
      role="alert"
      aria-live="assertive"
      className={`w-full text-white ${atrasado ? 'bg-red-700' : 'bg-red-600'}`}
    >
      {/* Aponta para a torre. A esteira FIFO de prazo relativo (/despacho/esteira,
          spec "Modalidades de prazo relativo") ainda nao existe; quando existir,
          este link muda para la — e so ele. */}
      <Link
        to="/despacho"
        className="flex items-center gap-3 px-4 py-2 text-sm font-medium hover:bg-red-800 transition-colors"
      >
        <AlertTriangle className={`w-4 h-4 shrink-0 ${atrasado ? 'animate-pulse' : ''}`} />
        <span className="font-semibold uppercase tracking-wide">
          {pedidos.length === 1 ? 'Novo Turbo' : `${pedidos.length} Turbos pendentes`}
        </span>
        <span className="opacity-90">
          Pedido {urgente.numero_pedido} · {urgente.marketplace_nome?.trim()}
        </span>
        {urgente.em_rascunho && (
          <span className="rounded bg-white/20 px-1.5 py-0.5 text-xs">
            em rascunho — ainda não publicado
          </span>
        )}
        <span className="ml-auto flex items-center gap-3">
          <span className="tabular-nums font-mono text-base">{formatarRestante(restante)}</span>
          <span className="underline underline-offset-2 opacity-90">ver na torre</span>
        </span>
      </Link>
    </div>
  );
}
