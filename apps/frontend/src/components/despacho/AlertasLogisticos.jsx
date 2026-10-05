import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { calcularRestante, formatarRestante } from '@/lib/alertaTurbo';

export default function AlertasLogisticos() {
  const { pathname } = useLocation();
  const enabled = /^\/(despacho|producao|producao-pedidos|ordens-producao|estoque|demandas)(\/|$)/.test(pathname);
  const [data, setData] = useState({ pedidos: [], divergencias: [] });
  const [agora, setAgora] = useState(Date.now);
  const [erro, setErro] = useState(false);
  useEffect(() => {
    if (!enabled) return undefined;
    let live = true;
    const controller = new AbortController();
    const load = async () => {
      try {
        const res = await fetch('/api/v2/despacho/alertas-logisticos', { signal: controller.signal });
        const json = await res.json();
        if (!res.ok || !json.success) throw new Error('Falha ao consultar');
        if (live) { setData(json.data); setErro(false); }
      } catch (e) { if (live && e.name !== 'AbortError') setErro(true); }
    };
    load(); const refresh = setInterval(load, 60_000); const tick = setInterval(() => setAgora(Date.now()), 1000);
    return () => { live = false; controller.abort(); clearInterval(refresh); clearInterval(tick); };
  }, [enabled]);
  if (!enabled || (!erro && !data.pedidos.length && !data.divergencias.length)) return null;
  const late = data.pedidos.some((p) => calcularRestante(p.prazo_em, agora) < 0);
  return <div role="status" aria-live="polite" className={`max-h-48 overflow-y-auto border-b px-4 py-3 text-sm ${late ? 'bg-red-50 text-red-900' : 'bg-amber-50 text-amber-950'}`}>
    {erro && <p>Não foi possível atualizar os alertas. A última consulta continua visível.</p>}
    {data.pedidos.length > 0 && <details><summary className="cursor-pointer font-semibold">{data.pedidos.length} pedido(s) próximos do prazo ou atrasados · {data.pedidos[0].numero_pedido} · {formatarRestante(calcularRestante(data.pedidos[0].prazo_em, agora))}</summary>
      <ul className="mt-2 space-y-1">{data.pedidos.map((p) => <li key={p.pedido_id}>Pedido {p.numero_pedido} · {p.marketplace_nome} · {p.etapa} · {formatarRestante(calcularRestante(p.prazo_em, agora))}{p.demanda_codigo && ` · Demanda ${p.demanda_codigo}`}</li>)}</ul></details>}
    {data.divergencias.map((d) => <p key={d.id}>Demanda {d.demanda_id}: a agenda ou o prazo mudou. Os horários publicados foram preservados.</p>)}
  </div>;
}
