-- Correcao auditavel do recorte conferido pelo operador em 05/10/2026:
-- 71 Em Andamento, todos com envio ate 06/10; 15 estavam estimados em 07/10.
-- Nunca inventa ship_by_date no espelho da API.

CREATE OR REPLACE FUNCTION public.shopee_preservar_prazo_painel()
RETURNS trigger LANGUAGE plpgsql SET search_path TO public, pg_temp AS $$
DECLARE confirmado timestamptz;
BEGIN
    IF NEW.marketplace_module_id = 'shopee' THEN
        SELECT NULLIF(s.logistics->>'deadline', '')::timestamptz INTO confirmado
          FROM public.pedido_snapshots s
         WHERE s.pedido_id = NEW.id
           AND s.logistics->>'dispatch_deadline_source' = 'shopee.seller_panel.confirmed';
        IF confirmado IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.pedidos_shopee so
             WHERE so.codigo_pedido = NEW.marketplace_order_id AND so.ship_by_date IS NOT NULL
        ) THEN
            NEW.data_limite_envio := confirmado;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS shopee_preserve_panel_deadline ON public.pedidos;
CREATE TRIGGER shopee_preserve_panel_deadline BEFORE INSERT OR UPDATE ON public.pedidos
    FOR EACH ROW EXECUTE FUNCTION public.shopee_preservar_prazo_painel();

-- O upsert do worker tambem atualiza o snapshot. Uma estimativa antiga nao
-- pode apagar a confirmacao antes da gravacao seguinte do pedido.
CREATE OR REPLACE FUNCTION public.shopee_preservar_snapshot_painel()
RETURNS trigger LANGUAGE plpgsql SET search_path TO public, pg_temp AS $$
DECLARE chave text;
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.logistics->>'dispatch_deadline_source' = 'shopee.seller_panel.confirmed'
       AND NEW.logistics->>'dispatch_deadline_source' IS DISTINCT FROM 'shopee.ship_by_date'
       AND NOT EXISTS (
           SELECT 1 FROM public.pedidos p JOIN public.pedidos_shopee so
             ON so.codigo_pedido = p.marketplace_order_id
            WHERE p.id = NEW.pedido_id AND so.ship_by_date IS NOT NULL
       ) THEN
        FOREACH chave IN ARRAY ARRAY['deadline','dispatch_deadline_source','deadline_estimated','deadline_reconciliation'] LOOP
            IF OLD.logistics ? chave THEN
                NEW.logistics := jsonb_set(NEW.logistics, ARRAY[chave], OLD.logistics->chave);
            END IF;
        END LOOP;
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS shopee_preserve_panel_snapshot ON public.pedido_snapshots;
CREATE TRIGGER shopee_preserve_panel_snapshot BEFORE UPDATE ON public.pedido_snapshots
    FOR EACH ROW EXECUTE FUNCTION public.shopee_preservar_snapshot_painel();

DO $$
DECLARE alvo record;
BEGIN
    FOR alvo IN
        SELECT p.id, p.data_limite_envio AS anterior
          FROM public.vw_pedidos_pendentes_despacho p
          JOIN public.pedidos_shopee so ON so.codigo_pedido = p.marketplace_order_id
         WHERE p.marketplace_module_id = 'shopee'
           AND p.situacao_pedido_id = 2 AND so.ship_by_date IS NULL
           AND p.data_limite_envio = '2026-10-07T23:59:59-03:00'::timestamptz
           AND p.marketplace_order_id = ANY(ARRAY[
               '261005T9TABWHR','261005TBVFF3RC','261005TFV7WD87','261005TH0EJVU9',
               '261005THATESPP','261005THXF0VGG','261005TMABYJXQ','261006TNA2N38K',
               '261006TNPCGR7E','261006TPEPQRT8','261006TPQ1QY2H','261006TSF2W2VN',
               '261006TSMCMWVE','261006TTF8XHE5','261006TWAE5YNT'
           ])
    LOOP
        UPDATE public.pedido_snapshots
           SET logistics = logistics || jsonb_build_object(
               'deadline', '2026-10-06T23:59:59-03:00',
               'dispatch_deadline_source', 'shopee.seller_panel.confirmed',
               'deadline_estimated', false,
               'deadline_reconciliation', jsonb_build_object(
                   'previous_deadline', alvo.anterior, 'confirmed_at', now(),
                   'evidence', 'Operador confirmou em 05/10: todos os 71 pedidos em andamento enviam ate 06/10'
               )
           ), updated_at = now()
         WHERE pedido_id = alvo.id;
        UPDATE public.pedidos SET data_limite_envio = '2026-10-06T23:59:59-03:00',
               prazo_postagem_tentativas = 0, prazo_postagem_proxima_tentativa = NULL,
               prazo_postagem_motivo = NULL WHERE id = alvo.id;
    END LOOP;
END;
$$;
