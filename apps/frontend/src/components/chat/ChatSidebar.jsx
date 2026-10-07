import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { formatAppDate, formatAppDateInput, formatAppDateTime } from '@/lib/dateTime';
import { Loader2, MessageSquare, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

const EMPTY_HIGHLIGHTED_MESSAGE_IDS = [];

/**
 * ChatSidebar — histórico de conversas da Shopee e do Mercado Livre.
 *
 * Props:
 *  - open: boolean
 *  - onOpenChange: (open: boolean) => void
 *  - username: string (comprador Shopee)
 *  - orderId: string (número do pedido para exibição)
 *  - highlightedMessageIds: string[] (mensagens que originaram personalizações)
 */
export function ChatSidebar({ open, onOpenChange, username, orderId, highlightedMessageIds = EMPTY_HIGHLIGHTED_MESSAGE_IDS, marketplace = 'shopee', integrationId, pedidoId }) {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const containerRef = useRef(null);
  const highlightSet = useRef(new Set(highlightedMessageIds));
  const requestRef = useRef(null);

  const loadMessages = useCallback(async (user) => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const path = marketplace === 'mercadolivre'
        ? `/api/v2/mercadolivre/integracoes/${integrationId}/personalizados/pedidos/${pedidoId}/chat`
        : `/api/v2/personalizados/chat/${encodeURIComponent(user)}${integrationId ? `?integration_id=${encodeURIComponent(integrationId)}` : ''}`;
      const res = await fetch(path, {
        headers: { Accept: 'application/json' },
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const msgs = data.success ? (data.data?.messages || []) : [];
      const displayMessages = marketplace === 'mercadolivre'
        ? msgs.map(message => {
          const senderRole = message.sender_role || 'unknown';
          const senderLabels = {
            seller: 'Vendedor',
            agent: 'Equipe de atendimento',
            unknown: 'Remetente não identificado',
          };
          return {
            id: message.provider_message_id,
            from_user_name: senderRole === 'buyer' ? user : `meli-${senderRole}`,
            sender_label: senderRole === 'buyer' ? null : senderLabels[senderRole] || 'Remetente não identificado',
            content: message.text_content || (message.attachments?.length ? `${message.attachments.length} anexo(s)` : 'Mensagem sem texto'),
            created_at: message.created_at,
            type: 'text',
          };
        })
        : msgs;
      setMessages(displayMessages);
    } catch (err) {
      if (err.name !== 'AbortError') setError(err.message);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [integrationId, marketplace, pedidoId]);

  useEffect(() => {
    if (open && (username || (marketplace === 'mercadolivre' && integrationId && pedidoId))) {
      highlightSet.current = new Set(highlightedMessageIds);
      setMessages([]);
      loadMessages(username);
    } else {
      requestRef.current?.abort();
      setMessages([]);
      setLoading(false);
      setError(null);
    }
    return () => requestRef.current?.abort();
  }, [open, username, marketplace, integrationId, pedidoId, highlightedMessageIds, loadMessages]);

  // Scroll para o fim após carregar
  useEffect(() => {
    if (!loading && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages, loading]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-[420px] sm:w-[540px] flex flex-col h-full p-0" side="right">
        {/* Header */}
        <SheetHeader className="border-b px-4 py-3 flex-shrink-0">
          <div className="flex items-center justify-between">
            <div>
              <SheetTitle className="flex items-center gap-2">
                <MessageSquare className="h-4 w-4" />
                Chat — Pedido #{orderId || '—'}
              </SheetTitle>
              <p className="text-xs text-muted-foreground mt-1">{marketplace === 'mercadolivre' ? (username || 'Conversa do pedido') : `@${username || '—'}`}</p>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => loadMessages(username)}
              disabled={loading}
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            </Button>
          </div>
        </SheetHeader>

        {/* Mensagens */}
        <div ref={containerRef} className="flex-1 overflow-y-auto p-4 space-y-3 bg-muted/30">
          {loading && messages.length === 0 ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : error ? (
            <div className="text-center py-8 text-red-500">
              <p>Erro ao carregar mensagens:</p>
              <p className="text-sm font-mono mt-1">{error}</p>
              <Button variant="outline" size="sm" className="mt-3" onClick={() => loadMessages(username)}>
                Tentar novamente
              </Button>
            </div>
          ) : messages.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              {marketplace === 'mercadolivre'
                ? 'Nenhuma mensagem sincronizada para este pedido. Tente atualizar em instantes.'
                : 'Nenhuma mensagem encontrada.'}
            </div>
          ) : (
            renderMessages(messages, username, highlightSet.current)
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ─── Helpers de renderização ───────────────────────────────────────────────

function renderMessages(messages, username, highlightSet) {
  const grouped = groupMessagesByDate(messages);
  const elements = [];

  Object.entries(grouped).forEach(([date, msgs]) => {
    elements.push(
      <div key={`date-${date}`} className="text-center text-xs text-muted-foreground py-2 sticky top-0 bg-muted/30 backdrop-blur-sm z-10">
        <Badge variant="secondary" className="font-normal">
          {date === 'sem-data' ? 'Data não informada' : formatDateBadge(date)}
        </Badge>
      </div>
    );

    msgs.forEach((msg) => {
      elements.push(renderMessage(msg, username, highlightSet));
    });
  });

  return elements;
}

function renderMessage(msg, username, highlightSet) {
  const isCustomer = msg.from_user_name === username;
  const isNotification = msg.type === 'notification';
  const isBundle = msg.type === 'bundle_message';
  const isHighlighted = highlightSet.has(String(msg.id));

  // Bundle messages
  if (isBundle && Array.isArray(msg.bundle_messages)) {
    return (
      <div
        key={msg.id}
        className={`flex flex-col items-start gap-1 ${isHighlighted ? 'ring-2 ring-yellow-400 rounded-lg p-1' : ''}`}
      >
        <div className="bg-background rounded-lg p-3 max-w-[85%] border shadow-sm">
          <div className="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1">
            <span>📦 Mensagens agrupadas ({msg.bundle_messages.length})</span>
          </div>
          {msg.bundle_messages.map((bMsg) => {
            const bIsCustomer = bMsg.from_user_name === username;
            const bHighlighted = highlightSet.has(String(bMsg.id));
            return (
              <div
                key={bMsg.id}
                className={`mb-2 last:mb-0 p-2 rounded ${
                  bIsCustomer
                    ? 'bg-muted text-foreground'
                    : 'bg-blue-50 text-blue-900'
                } ${bHighlighted ? 'ring-2 ring-yellow-400' : ''}`}
              >
                <p className="text-sm whitespace-pre-wrap">{bMsg.display_content || bMsg.content || ''}</p>
              </div>
            );
          })}
          <div className="text-[10px] text-muted-foreground mt-2 text-right">
            {msg.created_at ? formatTs(msg.created_at) : ''}
          </div>
        </div>
      </div>
    );
  }

  // Notification
  if (isNotification) {
    return (
      <div key={msg.id} className="text-center text-xs text-muted-foreground py-1">
        {msg.display_content || msg.content || ''}
      </div>
    );
  }

  // Regular message
  return (
    <div
      key={msg.id}
      className={`flex flex-col ${isCustomer ? 'items-start' : 'items-end'} ${isHighlighted ? 'ring-2 ring-yellow-400 rounded-lg p-1' : ''}`}
    >
      <div
        className={`max-w-[85%] rounded-lg p-3 text-sm shadow-sm ${
          isCustomer
            ? 'bg-background text-foreground border'
            : 'bg-blue-500 text-white'
        }`}
      >
        {msg.sender_label && <span className={`mb-1 text-[10px] ${isCustomer ? 'text-muted-foreground' : 'text-blue-100'}`}>{msg.sender_label}</span>}
        <p className="whitespace-pre-wrap">{msg.display_content || msg.content || ''}</p>
      </div>
      <span className="text-[10px] text-muted-foreground mt-1">
        {msg.created_at ? formatTs(msg.created_at) : ''}
      </span>
    </div>
  );
}

function groupMessagesByDate(messages) {
  const groups = {};
  const sorted = [...messages].sort((left, right) => {
    const leftDate = left.created_at ? new Date(left.created_at).getTime() : Number.POSITIVE_INFINITY;
    const rightDate = right.created_at ? new Date(right.created_at).getTime() : Number.POSITIVE_INFINITY;
    const safeLeftDate = Number.isNaN(leftDate) ? Number.POSITIVE_INFINITY : leftDate;
    const safeRightDate = Number.isNaN(rightDate) ? Number.POSITIVE_INFINITY : rightDate;
    return safeLeftDate - safeRightDate || String(left.id || '').localeCompare(String(right.id || ''));
  });
  sorted.forEach((msg) => {
    const date = formatAppDateInput(msg.created_at);
    const group = date || 'sem-data';
    if (!groups[group]) groups[group] = [];
    groups[group].push(msg);
  });
  return groups;
}

function formatDateBadge(dateString) {
  const today = formatAppDateInput();
  const yesterday = shiftDateKey(today, -1);

  if (dateString === today) return 'Hoje';
  if (dateString === yesterday) return 'Ontem';
  return formatAppDate(dateString, { fallback: '' });
}

function formatTs(ts) {
  return formatAppDateTime(ts, { fallback: '' }).replace(',', '');
}

function shiftDateKey(dateKey, days) {
  const date = new Date(`${dateKey}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return formatAppDateInput(date);
}
