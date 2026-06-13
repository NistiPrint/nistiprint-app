import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { MessageSquare, Store } from 'lucide-react';

function pick(...values) {
  return values.find((value) => value !== undefined && value !== null && value !== '');
}

function Field({ label, value, mono = false }) {
  if (value === undefined || value === null || value === '') return null;
  return (
    <div className="flex items-start justify-between gap-3 border-b py-2 last:border-b-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={`max-w-[65%] text-right text-sm ${mono ? 'font-mono' : 'font-medium'}`}>
        {String(value)}
      </span>
    </div>
  );
}

export default function PedidoPlatformFieldsCard({ pedido }) {
  const fields = pedido?.platform_fields || {};
  const snapshot = pedido?.snapshot || {};
  const identity = snapshot.identity || {};
  const shopee = fields.shopee || {};
  const meli = fields.mercadolivre || {};
  const meliOrder = meli.order || {};
  const meliShipment = meli.shipment || {};

  const platform = pick(identity.marketplace, pedido?.logistica?.marketplace?.slug, pedido?.origem);
  const username = pick(
    fields.buyer_username,
    shopee.buyer_username,
    meliOrder.buyer?.nickname,
    pedido?.cliente?.username
  );
  const message = pick(fields.message_to_seller, shopee.raw?.message_to_seller);
  const shippingStatus = pick(meliShipment.status, meliOrder.shipping?.status);
  const paymentStatus = Array.isArray(meliOrder.payments) ? meliOrder.payments[0]?.status : undefined;

  const hasData = platform || username || message || shippingStatus || paymentStatus || identity.bling_order_number;
  if (!hasData) return null;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-lg">
          <Store className="h-5 w-5" />
          Dados da plataforma
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {platform && <Badge variant="outline">{String(platform).toUpperCase()}</Badge>}
          {username && (
            <Badge className="gap-1">
              <MessageSquare className="h-3 w-3" />
              {username}
            </Badge>
          )}
        </div>
        <div>
          <Field label="Pedido marketplace" value={identity.marketplace_order_id || pedido?.codigo_pedido_externo} mono />
          <Field label="Pedido Bling" value={identity.bling_order_number} mono />
          <Field label="ID Bling" value={identity.bling_order_id} mono />
          <Field label="Usuário/chat" value={username} />
          <Field label="Mensagem do comprador" value={message} />
          <Field label="Transportadora" value={fields.shipping_carrier || shopee.shipping_carrier || pedido?.logistica?.shipping_carrier} />
          <Field label="Status pagamento" value={paymentStatus} />
          <Field label="Status envio" value={shippingStatus} />
          <Field label="Shipment ID" value={meliShipment.id || meliOrder.shipping?.id} mono />
        </div>
      </CardContent>
    </Card>
  );
}
