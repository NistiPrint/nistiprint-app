import { useEffect, useRef, useState, useCallback } from 'react';
import { toast } from 'sonner';
import { supabase } from '@/lib/supabase';

export function useRealtimePrintJobs() {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const isMounted = useRef(false);

  const fetchJobs = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const response = await fetch('/api/v2/printing/jobs', {
        headers: { 'Accept': 'application/json' }
      });
      if (!response.ok) throw new Error('Falha ao carregar jobs');
      const data = await response.json();
      
      if (isMounted.current) {
        setJobs(data);
        setError(null);
      }
    } catch (e) {
      if (isMounted.current) setError(e.message);
      if (!silent) toast.error('Erro na sincronização: ' + e.message);
    } finally {
      if (isMounted.current && !silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    isMounted.current = true;
    fetchJobs();

    const channel = supabase
      .channel('print-jobs-changes')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'print_jobs' },
        () => {
          fetchJobs(true);
        }
      )
      .subscribe();

    return () => {
      isMounted.current = false;
      supabase.removeChannel(channel);
    };
  }, [fetchJobs]);

  return { jobs, loading, error, refresh: () => fetchJobs(true) };
}
