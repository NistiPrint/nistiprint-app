import { useState, useEffect, useRef } from 'react';
import { toast } from 'sonner';
import { supabase } from '@/lib/supabase';

export function useRealtimePrioritizedDemandas(intervalMs = 5000) {
  const [prioritizedItems, setPrioritizedItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const isMounted = useRef(false);
  const requestVersion = useRef(0);
  const invalidationTimer = useRef(null);
  const realtimeRef = useRef(false);
  const sseRef = useRef(false);
  const [realtimeConnected, setRealtimeConnected] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState(null);

  const fetchPrioritizedItems = async (silent = false) => {
    const version = ++requestVersion.current;
    if (!silent) setLoading(true);
    try {
      const response = await fetch('/api/v2/demanda_producao/prioritized', {
        headers: { 'Accept': 'application/json' }
      });
      if (!response.ok) throw new Error('Falha ao carregar itens priorizados');
      const data = await response.json();
      if (isMounted.current && version === requestVersion.current) {
        setPrioritizedItems(data.prioritized_items || []);
        setError(null);
        setLastUpdatedAt(new Date().toISOString());
      }
    } catch (e) {
      if (isMounted.current && version === requestVersion.current) setError(e.message);
      if (!silent) toast.error('Erro na sincronização de prioridades: ' + e.message);
    } finally {
      if (isMounted.current && version === requestVersion.current) setLoading(false);
    }
  };

  useEffect(() => {
    isMounted.current = true;
    fetchPrioritizedItems();

    const scheduleRefresh = () => {
      if (invalidationTimer.current) clearTimeout(invalidationTimer.current);
      invalidationTimer.current = setTimeout(() => fetchPrioritizedItems(true), 300);
    };
    const handleStockUpdate = () => scheduleRefresh();
    const handleStreamState = (event) => {
      sseRef.current = Boolean(event.detail?.connected);
      if (isMounted.current) setRealtimeConnected(realtimeRef.current || sseRef.current);
      if (sseRef.current) scheduleRefresh();
    };
    window.addEventListener('stock:updated', handleStockUpdate);
    window.addEventListener('stock:stream-state', handleStreamState);
    const channel = supabase
      .channel('prioritized-demandas-changes')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'demandas_producao' }, scheduleRefresh)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'itens_demanda' }, scheduleRefresh)
      .subscribe((status) => {
        const connected = status === 'SUBSCRIBED';
        realtimeRef.current = connected;
        if (isMounted.current) setRealtimeConnected(connected || sseRef.current);
        if (connected) fetchPrioritizedItems(true);
      });

    const recoveryPoll = setInterval(() => {
      if (!realtimeRef.current && !sseRef.current) fetchPrioritizedItems(true);
    }, Math.max(30000, intervalMs));

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
  }, [intervalMs]);

  return {
    prioritizedItems,
    loading,
    error,
    realtimeConnected,
    isStale: Boolean(error),
    lastUpdatedAt,
    refresh: () => fetchPrioritizedItems(true),
  };
}
