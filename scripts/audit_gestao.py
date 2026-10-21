"""Read-only reconciliation of canonical orders and Gestão projections.

Set NISTIPRINT_GESTAO_AUDIT_DSN to a PostgreSQL connection string. The script
does not print the DSN or individual buyers, addresses, names, or order data.
"""

import argparse
from datetime import date
import json
import os

import psycopg2
from psycopg2.extras import RealDictCursor


FACTS = """
WITH facts AS (
 SELECT f.pedido_id,f.sold_on,f.account_id,f.marketplace,f.payload,
   jsonb_array_length(f.payload->'items') fact_item_count,
   (SELECT count(*) FROM itens_pedido ip WHERE ip.pedido_id=f.pedido_id) canonical_item_count,
   (SELECT CASE WHEN count(*)>0 AND count(*)=count(i->>'subtotal')
     THEN sum((i->>'subtotal')::numeric) END
    FROM jsonb_array_elements(f.payload->'items') i) fact_value,
   (SELECT sum(ip.subtotal) FROM itens_pedido ip WHERE ip.pedido_id=f.pedido_id) canonical_value
 FROM gestao_fatos_pedido f WHERE f.sold_on BETWEEN %s AND %s
)
SELECT sold_on,marketplace,account_id,count(*) projected_orders,
 count(*) FILTER(WHERE (payload->>'eligible')::boolean) eligible_orders,
 sum(fact_value) FILTER(WHERE (payload->>'eligible')::boolean) fact_sales,
 count(*) FILTER(WHERE fact_value IS DISTINCT FROM canonical_value) item_value_mismatches,
 count(*) FILTER(WHERE fact_item_count IS DISTINCT FROM canonical_item_count) item_count_mismatches,
 count(*) FILTER(WHERE payload->>'stage'='unknown') unknown_stage,
 count(*) FILTER(WHERE btrim(payload->>'region') ~ '^[*xX#•-]+$') masked_region,
 count(*) FILTER(WHERE payload->>'region' IS NULL) missing_region,
 count(*) FILTER(WHERE EXISTS (
   SELECT 1 FROM jsonb_array_elements(payload->'items') i WHERE i->>'product_id' IS NOT NULL)) orders_with_mapped_item
FROM facts GROUP BY sold_on,marketplace,account_id ORDER BY sold_on,marketplace,account_id
"""

CANONICAL = """
SELECT coalesce(f.sold_on,(p.data_compra_marketplace AT TIME ZONE 'America/Sao_Paulo')::date,
  (p.data_venda AT TIME ZONE 'America/Sao_Paulo')::date,
  (p.created_at AT TIME ZONE 'America/Sao_Paulo')::date) sold_on,
 p.marketplace_integration_id account_id,count(*) canonical_orders,
 count(*) FILTER(WHERE f.pedido_id IS NULL) unprojected_orders,
 count(*) FILTER(WHERE o.pedido_id IS NOT NULL) pending_projection
FROM pedidos p LEFT JOIN gestao_fatos_pedido f ON f.pedido_id=p.id
LEFT JOIN gestao_outbox o ON o.pedido_id=p.id
WHERE coalesce(f.sold_on,(p.data_compra_marketplace AT TIME ZONE 'America/Sao_Paulo')::date,
  (p.data_venda AT TIME ZONE 'America/Sao_Paulo')::date,
  (p.created_at AT TIME ZONE 'America/Sao_Paulo')::date) BETWEEN %s AND %s
GROUP BY 1,2 ORDER BY 1,2
"""


def audit(connection, start, end):
    connection.set_session(readonly=True, autocommit=False)
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute('SET LOCAL statement_timeout = 30000')
        cursor.execute(FACTS, (start, end))
        facts = [dict(row) for row in cursor.fetchall()]
        cursor.execute(CANONICAL, (start, end))
        canonical = [dict(row) for row in cursor.fetchall()]
    connection.rollback()
    return {'period': {'start': start.isoformat(), 'end': end.isoformat()},
            'projected_by_day_account': facts, 'canonical_by_day_account': canonical,
            'totals': {'projected_orders': sum(row['projected_orders'] for row in facts),
                       'canonical_orders': sum(row['canonical_orders'] for row in canonical),
                       'unprojected_orders': sum(row['unprojected_orders'] for row in canonical),
                       'pending_projection': sum(row['pending_projection'] for row in canonical),
                       'item_value_mismatches': sum(row['item_value_mismatches'] for row in facts),
                       'item_count_mismatches': sum(row['item_count_mismatches'] for row in facts)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', type=date.fromisoformat, required=True)
    parser.add_argument('--end', type=date.fromisoformat, required=True)
    args = parser.parse_args()
    if args.start > args.end:
        parser.error('--start deve preceder --end')
    dsn = os.environ.get('NISTIPRINT_GESTAO_AUDIT_DSN')
    if not dsn:
        parser.error('Defina NISTIPRINT_GESTAO_AUDIT_DSN')
    with psycopg2.connect(dsn) as connection:
        print(json.dumps(audit(connection, args.start, args.end), ensure_ascii=False, default=str, indent=2))


if __name__ == '__main__':
    main()
