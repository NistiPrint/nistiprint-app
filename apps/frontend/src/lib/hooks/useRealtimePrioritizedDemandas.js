import { useState, useEffect, useRef } from 'react';
import { toast } from 'sonner';

export function useRealtimePrioritizedDemandas(intervalMs = 5000) {
  const [prioritizedItems, setPrioritizedItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const isMounted = useRef(false);

  const fetchPrioritizedItems = async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const response = await fetch('/api/v2/demanda_producao/prioritized', {
        headers: { 'Accept': 'application/json' }
      });
      if (!response.ok) throw new Error('Falha ao carregar itens priorizados');
      const data = await response.json();
      if (isMounted.current) {
        setPrioritizedItems(data.prioritized_items || []);
        setError(null);
      }
    } catch (e) {
      if (isMounted.current) setError(e.message);
      if (!silent) toast.error('Erro na sincronização de prioridades: ' + e.message);
    } finally {
      if (isMounted.current && !silent) setLoading(false);
    }
  };

  useEffect(() => {
    isMounted.current = true;
    fetchPrioritizedItems();

    const interval = setInterval(() => {
      fetchPrioritizedItems(true);
    }, intervalMs);

    return () => {
      isMounted.current = false;
      clearInterval(interval);
    };
  }, [intervalMs]);

  return { prioritizedItems, loading, error, refresh: () => fetchPrioritizedItems(true) };
}
