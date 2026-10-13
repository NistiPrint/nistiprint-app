import { useEffect, useRef, useState, useCallback } from 'react';
import { toast } from 'sonner';
import { supabase } from '@/lib/supabase';

export function useRealtimeDemandas(pendingChanges = {}) {
  const [demandas, setDemandas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const isMounted = useRef(false);
  const pendingChangesRef = useRef(pendingChanges);
  const requestVersion = useRef(0);
  const invalidationTimer = useRef(null);
  const realtimeRef = useRef(false);
  const sseRef = useRef(false);
  const [realtimeConnected, setRealtimeConnected] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState(null);

  // Manter ref atualizada para usar no fetch sem disparar o effect
  useEffect(() => {
    pendingChangesRef.current = pendingChanges;
  }, [pendingChanges]);

  const sortDemandas = (demandas) => {
    // ... (mesma lógica)
    return [...demandas].sort((a, b) => {
      const aIsFlex = a.is_flex || false;
      const bIsFlex = b.is_flex || false;
      if (aIsFlex !== bIsFlex) return aIsFlex ? -1 : 1;

      const aPriority = a.manual_priority_score || 0;
      const bPriority = b.manual_priority_score || 0;
      if (aPriority !== bPriority) return bPriority - aPriority;

      const aDate = a.data_entrega || '9999-12-31';
      const bDate = b.data_entrega || '9999-12-31';
      if (aDate !== bDate) return aDate.localeCompare(bDate);

      const aTime = a.horario_coleta || '23:59';
      const bTime = b.horario_coleta || '23:59';
      return aTime.localeCompare(bTime);
    });
  };

  const fetchDemandas = useCallback(async (silent = false) => {
    const version = ++requestVersion.current;
    if (!silent) setLoading(true);
    try {
      const response = await fetch('/api/v2/demanda_producao/', {
        headers: { 'Accept': 'application/json' }
      });
      if (!response.ok) throw new Error('Falha ao carregar demandas');
      const data = await response.json();
      
      if (isMounted.current && version === requestVersion.current) {
        let newDemandas = data.demandas || [];
        
        // Mesclar mudanças pendentes locais
        const pending = pendingChangesRef.current;
        if (Object.keys(pending).length > 0) {
          newDemandas = newDemandas.map(d => {
            if (pending[d.id]) {
              return { ...d, ...pending[d.id] };
            }
            return d;
          });
        }

        const sortedDemandas = sortDemandas(newDemandas);
        setDemandas(sortedDemandas);
        setError(null);
        setLastUpdatedAt(new Date().toISOString());
      }
    } catch (e) {
      if (isMounted.current && version === requestVersion.current) setError(e.message);
      if (!silent) toast.error('Erro na sincronização: ' + e.message);
    } finally {
      if (isMounted.current && version === requestVersion.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    isMounted.current = true;
    fetchDemandas();

    const scheduleRefresh = () => {
      if (invalidationTimer.current) clearTimeout(invalidationTimer.current);
      invalidationTimer.current = setTimeout(() => fetchDemandas(true), 300);
    };
    const handleStockUpdate = () => scheduleRefresh();
    const handleStreamState = (event) => {
      sseRef.current = Boolean(event.detail?.connected);
      if (isMounted.current) setRealtimeConnected(realtimeRef.current || sseRef.current);
      if (sseRef.current) scheduleRefresh();
    };
    window.addEventListener('stock:updated', handleStockUpdate);
    window.addEventListener('stock:stream-state', handleStreamState);

    // Agrupa as invalidações geradas por várias linhas na mesma operação.
    const channel = supabase
      .channel('demandas-changes')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'demandas_producao' },
        scheduleRefresh
      )
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'itens_demanda' },
        scheduleRefresh
      )
      .subscribe((status) => {
        const connected = status === 'SUBSCRIBED';
        realtimeRef.current = connected;
        if (isMounted.current) setRealtimeConnected(connected || sseRef.current);
        if (connected) fetchDemandas(true);
      });

    const recoveryPoll = setInterval(() => {
      if (!realtimeRef.current && !sseRef.current) fetchDemandas(true);
    }, 30000);

    return () => {
      isMounted.current = false;
      if (invalidationTimer.current) clearTimeout(invalidationTimer.current);
      clearInterval(recoveryPoll);
      window.removeEventListener('stock:updated', handleStockUpdate);
      window.removeEventListener('stock:stream-state', handleStreamState);
      realtimeRef.current = false;
      sseRef.current = false;
      supabase.removeChannel(channel);
    };
  }, [fetchDemandas]);

  return {
    demandas,
    setDemandas,
    loading,
    error,
    realtimeConnected,
    isStale: Boolean(error),
    lastUpdatedAt,
    refresh: () => fetchDemandas(true),
  };
}
