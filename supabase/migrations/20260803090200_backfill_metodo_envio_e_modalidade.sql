-- Backfill: extrair a chave de metodo de envio dos snapshots e reclassificar.
-- Contrato: docs/specs/02-domains/despacho/spec.md, "Ao cadastrar a modalidade
-- e a regra, o backlog reclassifica retroativamente os pedidos ainda nao
-- despachados."
--
-- O dado sempre esteve no banco. `pedido_snapshots.platform_fields` guarda o
-- detalhe cru desde o inicio; o que faltava era alguem ler o caminho certo.
-- Este backfill le esse caminho em SQL, sem depender de re-fetch na API do
-- marketplace, e so entao chama o classificador.
--
-- Nao filtra por `despachado_em`: pedido ja despachado tambem ganha a chave,
-- porque `metodos_envio_observados` e relatorio de administracao e precisa da
-- contagem real, nao so da fatia pendente.

-- --------------------------------------------------------------------------
-- 1. Chave e rotulo a partir do snapshot mais recente de cada pedido
-- --------------------------------------------------------------------------

WITH snap AS (
    SELECT DISTINCT ON (ps.pedido_id)
           ps.pedido_id,
           ps.platform_fields AS pf
      FROM public.pedido_snapshots ps
     ORDER BY ps.pedido_id, ps.id DESC
),
extraido AS (
    SELECT
        p.id AS pedido_id,
        p.marketplace_module_id AS module_id,
        CASE p.marketplace_module_id
            -- Shopee: o campo vive dentro do pacote, nao na raiz do pedido.
            -- Era exatamente essa a origem do bug.
            WHEN 'shopee' THEN
                s.pf -> 'shopee' -> 'package_list' -> 0 ->> 'logistics_channel_id'
            WHEN 'mercadolivre' THEN
                COALESCE(
                    s.pf -> 'mercadolivre' -> 'shipment' -> 'logistic' ->> 'type',
                    s.pf -> 'mercadolivre' -> 'shipment' ->> 'logistic_type'
                )
        END AS chave,
        CASE p.marketplace_module_id
            WHEN 'shopee' THEN
                COALESCE(
                    s.pf -> 'shopee' -> 'package_list' -> 0 ->> 'shipping_carrier',
                    s.pf -> 'shopee' ->> 'shipping_carrier'
                )
            WHEN 'mercadolivre' THEN
                COALESCE(
                    s.pf -> 'mercadolivre' -> 'shipment' -> 'shipping_option' ->> 'name',
                    s.pf -> 'mercadolivre' -> 'shipment' ->> 'mode'
                )
        END AS rotulo
      FROM public.pedidos p
      JOIN snap s ON s.pedido_id = p.id
     WHERE p.marketplace_module_id IN ('shopee', 'mercadolivre')
)
UPDATE public.pedidos p
   SET metodo_envio_chave  = e.chave,
       metodo_envio_rotulo = COALESCE(e.rotulo, p.metodo_envio_rotulo)
  FROM extraido e
 WHERE p.id = e.pedido_id
   AND e.chave IS NOT NULL
   AND p.metodo_envio_chave IS DISTINCT FROM e.chave;

-- --------------------------------------------------------------------------
-- 2. Registrar os valores observados
-- --------------------------------------------------------------------------
-- A deteccao de metodo novo nunca acumulou nada, porque a chave nunca chegou
-- ate aqui. Popular agora com o trafego real ja ingerido da o retrato correto
-- de partida: qualquer valor que aparecer depois disso e de fato novo.

INSERT INTO public.metodos_envio_observados (
    module_id, integration_id, campo_origem,
    valor_bruto, valor_normalizado, rotulo_bruto,
    pedido_exemplo_id, ocorrencias, status
)
SELECT
    p.marketplace_module_id,
    min(p.marketplace_integration_id),
    CASE p.marketplace_module_id
        WHEN 'shopee' THEN 'logistics_channel_id'
        ELSE 'logistic.type'
    END,
    p.metodo_envio_chave,
    lower(btrim(p.metodo_envio_chave)),
    min(p.metodo_envio_rotulo),
    min(p.id),
    count(*)::integer,
    'NOVO'
  FROM public.pedidos p
 WHERE p.metodo_envio_chave IS NOT NULL
   AND p.marketplace_module_id IS NOT NULL
 GROUP BY p.marketplace_module_id, p.metodo_envio_chave
ON CONFLICT (module_id, campo_origem, valor_normalizado) DO UPDATE
   SET ocorrencias  = GREATEST(public.metodos_envio_observados.ocorrencias, EXCLUDED.ocorrencias),
       rotulo_bruto = COALESCE(public.metodos_envio_observados.rotulo_bruto, EXCLUDED.rotulo_bruto);

-- --------------------------------------------------------------------------
-- 3. Reclassificar
-- --------------------------------------------------------------------------
-- Pedido nao despachado primeiro e sem lote: sao ~2 mil linhas e a funcao e um
-- SELECT indexado por regra. Um LOOP explicito, e nao um UPDATE ... FROM,
-- porque `classificar_pedido_modalidade` tambem mantem
-- `metodos_envio_observados` e o compromisso logistico.

DO $$
DECLARE
    r record;
    v_total integer := 0;
    v_ok    integer := 0;
BEGIN
    FOR r IN
        SELECT id FROM public.pedidos
         WHERE despachado_em IS NULL
           AND marketplace_module_id IS NOT NULL
         ORDER BY id
    LOOP
        v_total := v_total + 1;
        IF public.classificar_pedido_modalidade(r.id) IS NOT NULL THEN
            v_ok := v_ok + 1;
        END IF;
    END LOOP;

    RAISE NOTICE '[backfill-modalidade] % pedidos avaliados, % classificados', v_total, v_ok;
END;
$$;
