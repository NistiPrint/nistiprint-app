import { useEffect, useState, useCallback } from 'react';
import { supabase } from '@/lib/supabase';
import { toast } from 'sonner';

/**
 * Hook para buscar e gerenciar rascunhos de demandas automáticas.
 * 
 * Rascunhos são demandas criadas automaticamente pelo sistema de consolidação
 * enquanto a janela de agrupamento está aberta.
 */
export function useRascunhos() {
  const [rascunhos, setRascunhos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  /**
   * Busca todos os rascunhos ativos
   */
  const fetchRascunhos = useCallback(async () => {
    try {
      setLoading(true);
      const { data, error } = await supabase
        .from('demandas_producao')
        .select(`
          *,
          canais_venda (
            nome,
            slug,
            color,
            flex,
            fulfillment
          ),
          produtos (
            nome,
            sku
          ),
          demandas_pedidos (
            pedido_id,
            adicionado_apos_edicao,
            adicionado_em,
            pedidos (
              id,
              numero_pedido,
              codigo_pedido_externo
            )
          )
        `)
        .eq('status', 'RASCUNHO')
        .order('rascunho_expira_em', { ascending: true });

      if (error) throw error;

      // Processar dados para incluir contagens
      const processed = (data || []).map(demanda => {
        const pedidos = demanda.demandas_pedidos || [];
        const pedidosAposEdicao = pedidos.filter(p => p.adicionado_apos_edicao).length;
        
        return {
          ...demanda,
          total_pedidos: pedidos.length,
          pedidos_apos_edicao_qtd: pedidosAposEdicao,
          canal_nome: demanda.canais_venda?.nome || 'Canal',
          canal_color: demanda.canais_venda?.color || '#6b7280',
          canal_flex: demanda.canais_venda?.flex || false,
          produto_nome: demanda.produtos?.nome || null,
          produto_sku: demanda.produtos?.sku || null,
        };
      });

      setRascunhos(processed);
      setError(null);
    } catch (err) {
      console.error('Erro ao buscar rascunhos:', err);
      setError(err.message);
      toast.error('Erro ao carregar rascunhos');
    } finally {
      setLoading(false);
    }
  }, []);

  /**
   * Publica um rascunho (transforma em demanda ativa)
   */
  const publicarRascunho = useCallback(async (demandaId) => {
    try {
      const response = await fetch(`/api/v2/demanda_producao/${demandaId}/publicar`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.message || 'Erro ao publicar rascunho');
      }

      toast.success('Rascunho publicado!');
      await fetchRascunhos();
      return true;
    } catch (err) {
      toast.error(err.message);
      return false;
    }
  }, [fetchRascunhos]);

  /**
   * Edita um rascunho (marca como editado pelo usuário)
   */
  const editarRascunho = useCallback(async (demandaId, dados) => {
    try {
      const response = await fetch(`/api/v2/demanda_producao/${demandaId}/detalhes`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...dados,
          editado_pelo_usuario: true,
          editado_em: new Date().toISOString(),
        }),
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.message || 'Erro ao editar rascunho');
      }

      toast.success('Rascunho atualizado!');
      await fetchRascunhos();
      return true;
    } catch (err) {
      toast.error(err.message);
      return false;
    }
  }, [fetchRascunhos]);

  /**
   * Deleta um rascunho
   */
  const deletarRascunho = useCallback(async (demandaId) => {
    if (!window.confirm('Tem certeza que deseja deletar este rascunho?')) return false;

    try {
      const response = await fetch(`/api/v2/demanda_producao/${demandaId}`, {
        method: 'DELETE',
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.message || 'Erro ao deletar rascunho');
      }

      toast.success('Rascunho deletado!');
      await fetchRascunhos();
      return true;
    } catch (err) {
      toast.error(err.message);
      return false;
    }
  }, [fetchRascunhos]);

  /**
   * Busca pedidos novos de um rascunho (após edição)
   */
  const buscarPedidosNovos = useCallback(async (demandaId) => {
    try {
      const { data, error } = await supabase
        .from('demandas_pedidos')
        .select(`
          *,
          pedidos (
            id,
            numero_pedido,
            codigo_pedido_externo,
            total_pedido,
            data_venda
          )
        `)
        .eq('demanda_id', demandaId)
        .eq('adicionado_apos_edicao', true);

      if (error) throw error;

      return data || [];
    } catch (err) {
      console.error('Erro ao buscar pedidos novos:', err);
      toast.error('Erro ao buscar pedidos novos');
      return [];
    }
  }, []);

  /**
   * Confirma inclusão de pedidos novos (reseta flag)
   */
  const confirmarPedidosNovos = useCallback(async (demandaId) => {
    try {
      // Atualiza demanda para resetar contador
      const response = await fetch(`/api/v2/demanda_producao/${demandaId}/detalhes`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pedidos_apos_edicao_qtd: 0,
          requer_revisao: false,
        }),
      });

      if (!response.ok) throw new Error('Erro ao confirmar pedidos');

      toast.success('Pedidos confirmados!');
      await fetchRascunhos();
      return true;
    } catch (err) {
      toast.error(err.message);
      return false;
    }
  }, [fetchRascunhos]);

  /**
   * Processa pedidos sem demanda dos últimos 3 dias (consolidação manual síncrona)
   * USA A MESMA LÓGICA DO WEBHOOK
   */
  const processarPedidos = useCallback(async () => {
    try {
      const response = await fetch('/api/v2/consolidar/rascunhos/processar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.error || 'Erro ao processar pedidos');
      }

      const data = await response.json();
      
      // Atualiza lista de rascunhos após processamento
      await fetchRascunhos();
      
      return data;
    } catch (err) {
      console.error('Erro ao processar pedidos:', err);
      throw err;
    }
  }, [fetchRascunhos]);

  // Auto-refresh ao montar
  useEffect(() => {
    fetchRascunhos();
    
    // Refresh a cada 30 segundos
    const interval = setInterval(fetchRascunhos, 30000);
    return () => clearInterval(interval);
  }, [fetchRascunhos]);

  return {
    rascunhos,
    loading,
    error,
    refresh: fetchRascunhos,
    publicarRascunho,
    editarRascunho,
    deletarRascunho,
    buscarPedidosNovos,
    confirmarPedidosNovos,
    processarPedidos,
  };
}
