import React, { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/card';
import { Badge } from '../ui/badge';

const WebhookMonitor = () => {
  const [logs, setLogs] = useState([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    fetchLogs();
    const interval = setInterval(fetchLogs, 10000); // Poll every 10 seconds
    return () => clearInterval(interval);
  }, []);

  const fetchLogs = async () => {
    try {
      // We need an API for this, for now we'll mock or call a new endpoint
      const response = await fetch('/api/v2/webhooks/logs');
      const data = await response.json();
      setLogs(data.logs || []);
      setIsLoading(false);
    } catch (error) {
      console.error('Error fetching webhook logs:', error);
      setIsLoading(false);
    }
  };

  const getStatusBadge = (status) => {
    switch (status) {
      case 'SUCESSO':
        return <Badge className="bg-green-500 text-white">Sucesso</Badge>;
      case 'ERRO':
        return <Badge className="bg-red-500 text-white">Erro</Badge>;
      case 'PENDENTE':
        return <Badge className="bg-yellow-500 text-white">Pendente</Badge>;
      default:
        return <Badge>{status}</Badge>;
    }
  };

  return (
    <div className="p-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span>📡 Monitor de Webhooks</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p>Carregando logs...</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="text-xs uppercase bg-gray-50">
                  <tr>
                    <th className="px-4 py-2">ID</th>
                    <th className="px-4 py-2">Plataforma</th>
                    <th className="px-4 py-2">Evento</th>
                    <th className="px-4 py-2">Status</th>
                    <th className="px-4 py-2">Data</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.length === 0 ? (
                    <tr>
                      <td colSpan="5" className="px-4 py-8 text-center text-gray-500">
                        Nenhum webhook recebido ainda.
                      </td>
                    </tr>
                  ) : (
                    logs.map((log) => (
                      <tr key={log.id} className="border-b">
                        <td className="px-4 py-2 font-mono text-xs">{log.id}</td>
                        <td className="px-4 py-2 uppercase">{log.plataforma}</td>
                        <td className="px-4 py-2">{log.evento}</td>
                        <td className="px-4 py-2">{getStatusBadge(log.status)}</td>
                        <td className="px-4 py-2">
                          {log.created_at ? new Date(log.created_at).toLocaleString('pt-BR') : '-'}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default WebhookMonitor;
