import { supabase } from '@/lib/supabase';
import { ExecutionLog, Personalization, DashboardOrder, ChatMessage } from '@/types/ai';

export const aiService = {
  // Buscar pedidos cacheados para o dashboard
  getDashboardOrders: async (page = 1, pageSize = 20) => {
    const from = (page - 1) * pageSize;
    const to = from + pageSize - 1;

    const { data, error, count } = await supabase
      .from('cache_dashboard_pedidos')
      .select('*', { count: 'exact' })
      .order('order_date', { ascending: false })
      .range(from, to);

    if (error) throw error;
    return { data: data as DashboardOrder[], count };
  },

  // Buscar logs de um pedido específico
  getOrderLogs: async (orderSn: string) => {
    const { data, error } = await supabase
      .from('logs_execucao_ia')
      .select('*')
      .eq('order_sn', orderSn)
      .order('executed_at', { ascending: false });

    if (error) throw error;
    return data as ExecutionLog[];
  },

  // Buscar personalizações de um pedido
  getOrderPersonalizations: async (orderSn: string) => {
    const { data, error } = await supabase
      .from('personalizacoes_pedido')
      .select('*')
      .eq('shopee_order_sn', orderSn);

    if (error) throw error;
    return data as Personalization[];
  },

  // Buscar chat de um pedido (baseado no username do comprador)
  getOrderChat: async (username: string) => {
    const { data, error } = await supabase
      .from('mensagem_chat_shopee')
      .select('*')
      .or(`from_user_name.eq.${username},to_user_name.eq.${username}`)
      .order('created_at', { ascending: true });

    if (error) throw error;
    return data as ChatMessage[];
  },

  // Trigger para reprocessar IA (chama backend Flask)
  triggerAIProcessing: async (orderSn: string) => {
    const response = await fetch(`/api/v2/ferramentas/processar_nomes_ia`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shopee_order_sn: orderSn })
    });
    return response.json();
  }
};
