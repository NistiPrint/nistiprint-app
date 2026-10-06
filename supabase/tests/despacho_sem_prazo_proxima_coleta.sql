-- A regra de coleta e fallback operacional; nunca muda o prazo oficial salvo.
BEGIN;
INSERT INTO pedidos(numero_pedido,marketplace_module_id,marketplace_integration_id,
    modalidade_logistica_id,situacao_pedido_id,data_pagamento_marketplace,data_limite_envio)
VALUES ('sem-prazo-antes','shopee',6,1,2,now()-interval '1 day',NULL),
       ('sem-prazo-depois','shopee',6,1,2,now()+interval '1 day',NULL),
       ('prazo-oficial-prioridade','shopee',6,1,2,now()+interval '1 day',now());
DO $$
DECLARE alvo record; esperado text; dia date := (now() AT TIME ZONE 'America/Sao_Paulo')::date; ctx jsonb;
BEGIN
    FOR alvo IN SELECT p.id,p.numero_pedido,p.data_limite_envio,c.coleta_em
        FROM pedidos p LEFT JOIN LATERAL despacho_coleta_do_pedido(
            p.marketplace_module_id,p.modalidade_logistica_id,p.marketplace_integration_id,
            p.data_pagamento_marketplace,p.data_limite_envio,now()) c ON true
        WHERE p.numero_pedido IN ('sem-prazo-antes','sem-prazo-depois','prazo-oficial-prioridade')
    LOOP
        IF alvo.coleta_em IS NULL THEN RAISE EXCEPTION 'Fixture nao tem coleta disponivel'; END IF;
        esperado := despacho_bucket_prazo(COALESCE(alvo.data_limite_envio,alvo.coleta_em),dia);
        IF alvo.numero_pedido='prazo-oficial-prioridade' AND esperado<>'hoje'
        THEN RAISE EXCEPTION 'Coleta substituiu prazo oficial'; END IF;
        ctx := despacho_escopo_contexto(6,ARRAY[1],ARRAY[esperado],dia);
        IF NOT (ctx->'pedido_ids' @> to_jsonb(ARRAY[alvo.id]))
           OR NOT EXISTS(SELECT 1 FROM despacho_escopo_lote(6,ARRAY[1],ARRAY[esperado],dia) x WHERE x=alvo.id)
        THEN RAISE EXCEPTION 'Pedido % faltou no bucket %',alvo.numero_pedido,esperado; END IF;
        IF alvo.data_limite_envio IS NULL AND NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(ctx->'pedidos') item
             WHERE (item->>'id')::integer=alvo.id
               AND (item->>'data_coleta_prevista')::timestamptz=alvo.coleta_em)
        THEN RAISE EXCEPTION 'Coleta prevista nao chegou a lista do escopo'; END IF;
        IF alvo.data_limite_envio IS NULL AND EXISTS (
            SELECT 1 FROM despacho_escopo_lote(6,ARRAY[1],ARRAY['sem_prazo'],dia) x WHERE x=alvo.id)
        THEN RAISE EXCEPTION 'Pedido com coleta foi para sem_prazo'; END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM despacho_arvore(dia) a WHERE a.nivel=2
        AND a.qtd_pedidos<>jsonb_array_length(despacho_escopo_contexto(a.integration_id,
            CASE WHEN a.modalidade_id IS NULL THEN NULL ELSE ARRAY[a.modalidade_id] END,
            ARRAY[a.bucket_prazo],dia)->'pedido_ids'))
    THEN RAISE EXCEPTION 'Torre e escopo divergem com fallback'; END IF;
    IF despacho_bucket_operacional(NULL,NULL,NULL,dia)<>'sem_prazo'
    THEN RAISE EXCEPTION 'Ausencia de prazo e agenda deveria ser sem_prazo'; END IF;
END $$;
ROLLBACK;
