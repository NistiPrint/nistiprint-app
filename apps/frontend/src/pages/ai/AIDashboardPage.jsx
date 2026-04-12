import React, { useState, useEffect } from 'react';
import { aiService } from '@/services/aiService';
import { AIStatusBadge } from './AIStatusBadge';
import { ChatSidebar } from '@/components/chat/ChatSidebar';
import { format } from 'date-fns';
import { supabase } from '@/lib/supabase';

const AIDashboardPage = () => {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatUser, setChatUser] = useState(null);
  const [processingId, setProcessingId] = useState(null);

  useEffect(() => {
    loadOrders();

    const subscription = supabase
      .channel('public:cache_dashboard_pedidos')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'cache_dashboard_pedidos' }, (payload) => {
        handleRealtimeUpdate(payload);
      })
      .subscribe();

    return () => {
      supabase.removeChannel(subscription);
    };
  }, []);

  const loadOrders = async () => {
    try {
      const { data } = await aiService.getDashboardOrders(1, 50);
      setOrders(data);
    } catch (error) {
      console.error('Erro ao carregar pedidos:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleRealtimeUpdate = (payload) => {
    if (payload.eventType === 'INSERT') {
      setOrders(prev => [payload.new, ...prev]);
    } else if (payload.eventType === 'UPDATE') {
      setOrders(prev => prev.map(order => order.order_sn === payload.new.order_sn ? payload.new : order));
    }
  };

  const handleProcessAI = async (orderSn) => {
    setProcessingId(orderSn);
    try {
        await aiService.triggerAIProcessing(orderSn);
    } catch (error) {
        console.error("Erro ao disparar IA:", error);
        alert("Erro ao iniciar processamento");
    } finally {
        setProcessingId(null);
    }
  };

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="mb-6 flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">Identificação de Nomes (IA)</h1>
          <p className="text-gray-600">Monitoramento e extração de personalização em tempo real</p>
        </div>
        <button
            onClick={loadOrders}
            className="px-4 py-2 bg-white border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
            Atualizar
        </button>
      </div>

      <div className="bg-white shadow rounded-lg overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Pedido</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Comprador</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Data</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Chat</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status IA</th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Ações</th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {loading ? (
               <tr><td colSpan="6" className="px-6 py-4 text-center">Carregando...</td></tr>
            ) : orders.map((order) => (
              <tr key={order.order_sn} className="hover:bg-gray-50">
                <td className="px-6 py-4 whitespace-nowrap">
                  <div className="text-sm font-medium text-gray-900">{order.bling_number || order.order_sn}</div>
                  <div className="text-xs text-gray-500">{order.order_sn}</div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <div className="text-sm text-gray-900">{order.buyer_username || '-'}</div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                  {order.order_date ? format(new Date(order.order_date), 'dd/MM/yyyy HH:mm') : '-'}
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  {order.has_chat ? (
                    <span className="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-blue-100 text-blue-800">
                      Sim
                    </span>
                  ) : (
                    <span className="text-gray-400 text-xs">Não</span>
                  )}
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                    <AIStatusBadge status={order.last_ai_status} />
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                  <button
                    onClick={() => { setChatUser(order.buyer_username); setChatOpen(true); }}
                    className="text-indigo-600 hover:text-indigo-900 mr-4"
                  >
                    Chat
                  </button>
                  <button
                    onClick={() => handleProcessAI(order.order_sn)}
                    disabled={processingId === order.order_sn}
                    className={`text-green-600 hover:text-green-900 ${processingId === order.order_sn ? 'opacity-50 cursor-wait' : ''}`}
                  >
                    {processingId === order.order_sn ? '...' : 'Processar'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ChatSidebar
        open={chatOpen}
        onOpenChange={setChatOpen}
        username={chatUser}
        orderId=""
      />
    </div>
  );
};

export default AIDashboardPage;
