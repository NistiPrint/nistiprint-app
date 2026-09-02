-- A classificacao de modalidade acontece no banco, nao no worker.
-- Contrato: docs/specs/02-domains/despacho/spec.md
--
-- ## Por que mudou de lugar
--
-- O backfill de 20260803090200 classificou tudo o que existia. Todo pedido
-- ingerido *depois* voltou a entrar sem modalidade: 477148, 477149, 477151,
-- 477153, 477154, 477155 — inclusive um Flex obvio (canal 90033, "Entrega
-- Rapida"), com o dado correto gravado no snapshot.
--
-- A causa nao foi a regra nem o dado: foi o deploy. As duas correcoes no
-- extrator Python (ler `package_list`, e nao retornar cedo quando a chave e
-- nula) estao no repositorio e nao no worker em producao. Enquanto o processo
-- antigo estiver rodando, `metodo_envio_chave` fica NULL e
-- `classificar_pedido_modalidade` sequer e chamada.
--
-- A licao nao e "fazer o deploy". E que a classificacao estava presa a um
-- unico caminho de codigo, num sistema onde pedido entra por webhook de
-- marketplace, por ingest de ERP e por reprocessamento manual. Uma regra que
-- vale para todo pedido pertence ao lugar por onde todo pedido passa.
--
-- ## Como fica
--
--   pedido_snapshots AFTER INSERT/UPDATE OF platform_fields
--       -> extrai chave/rotulo -> grava em pedidos -> classifica
--
--   pedidos AFTER INSERT / UPDATE OF metodo_envio_chave, modalidade_logistica
--       -> classifica (cobre o fallback canonico de quem nao tem snapshot,
--          como o pedido vindo via Bling)
--
-- O extrator Python continua existindo e continua correto. Ele deixa de ser a
-- unica garantia: quando rodar, grava a chave e o trigger nao encontra
-- diferenca; quando nao rodar, o trigger resolve.
--
-- ## Recursao
--
-- `classificar_pedido_modalidade` escreve `modalidade_logistica_id`,
-- `modalidade_regra_id`, `modalidade_classificada_em` e
-- `compromisso_logistico_em` — nenhuma delas na lista de `UPDATE OF`. O
-- trigger de pedidos nao se re-dispara, e nada aqui escreve em
-- `pedido_snapshots`. Se alguem adicionar uma dessas colunas ao `UPDATE OF`,
-- cria um laco.

CREATE OR REPLACE FUNCTION public.extrair_metodo_envio(
    p_module_id       text,
    p_platform_fields jsonb
)
RETURNS TABLE (chave text, rotulo text, campo_origem text)
LANGUAGE sql
IMMUTABLE
AS $fn$
    SELECT
        CASE p_module_id
            -- Shopee: dentro do pacote, nao na raiz. Ler so a raiz era o bug
            -- original que deixou 100% dos pedidos sem classificacao.
            WHEN 'shopee' THEN
                COALESCE(
                    p_platform_fields -> 'shopee' -> 'package_list' -> 0 ->> 'logistics_channel_id',
                    p_platform_fields -> 'shopee' ->> 'logistics_channel_id'
                )
            WHEN 'mercadolivre' THEN
                COALESCE(
                    p_platform_fields -> 'mercadolivre' -> 'shipment' -> 'logistic' ->> 'type',
                    p_platform_fields -> 'mercadolivre' -> 'shipment' ->> 'logistic_type'
                )
        END,
        CASE p_module_id
            WHEN 'shopee' THEN
                COALESCE(
                    p_platform_fields -> 'shopee' -> 'package_list' -> 0 ->> 'shipping_carrier',
                    p_platform_fields -> 'shopee' ->> 'shipping_carrier'
                )
            WHEN 'mercadolivre' THEN
                COALESCE(
                    p_platform_fields -> 'mercadolivre' -> 'shipment' -> 'shipping_option' ->> 'name',
                    p_platform_fields -> 'mercadolivre' -> 'shipment' ->> 'mode'
                )
        END,
        CASE p_module_id
            WHEN 'shopee'       THEN 'logistics_channel_id'
            WHEN 'mercadolivre' THEN 'logistic.type'
        END;
$fn$;

COMMENT ON FUNCTION public.extrair_metodo_envio(text, jsonb) IS
  'Le a chave estavel de metodo de envio do payload cru. Mesmos caminhos do extrator Python; existe aqui para a classificacao nao depender de deploy do worker.';

-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.tg_snapshot_classifica_modalidade()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_module text;
    v_chave  text;
    v_rotulo text;
    v_campo  text;
BEGIN
    SELECT p.marketplace_module_id INTO v_module
      FROM public.pedidos p WHERE p.id = NEW.pedido_id;

    IF v_module IS NULL THEN
        RETURN NULL;
    END IF;

    SELECT e.chave, e.rotulo, e.campo_origem INTO v_chave, v_rotulo, v_campo
      FROM public.extrair_metodo_envio(v_module, NEW.platform_fields) e;

    IF v_chave IS NOT NULL THEN
        UPDATE public.pedidos
           SET metodo_envio_chave  = v_chave,
               metodo_envio_rotulo = COALESCE(v_rotulo, metodo_envio_rotulo)
         WHERE id = NEW.pedido_id
           AND metodo_envio_chave IS DISTINCT FROM v_chave;

        -- Deteccao de metodo novo continua alimentada mesmo sem o worker: e o
        -- que faz um canal inedito aparecer na aba Logistica sozinho.
        PERFORM public.registrar_metodo_envio_observado(
            v_module::varchar, NULL, v_campo::varchar, v_chave, v_rotulo, NEW.pedido_id
        );
    END IF;

    PERFORM public.classificar_pedido_modalidade(NEW.pedido_id);
    RETURN NULL;
END;
$fn$;

DROP TRIGGER IF EXISTS tg_snapshot_classifica_modalidade ON public.pedido_snapshots;
CREATE TRIGGER tg_snapshot_classifica_modalidade
    AFTER INSERT OR UPDATE OF platform_fields ON public.pedido_snapshots
    FOR EACH ROW EXECUTE FUNCTION public.tg_snapshot_classifica_modalidade();

-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.tg_pedido_classifica_modalidade()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
BEGIN
    PERFORM public.classificar_pedido_modalidade(NEW.id);
    RETURN NULL;
END;
$fn$;

DROP TRIGGER IF EXISTS tg_pedido_classifica_modalidade ON public.pedidos;
CREATE TRIGGER tg_pedido_classifica_modalidade
    AFTER INSERT OR UPDATE OF metodo_envio_chave, metodo_envio_rotulo, modalidade_logistica
    ON public.pedidos
    FOR EACH ROW EXECUTE FUNCTION public.tg_pedido_classifica_modalidade();

-- Reprocessa o que entrou depois do backfill e ficou sem classificacao.
-- Reescrever `platform_fields` com o proprio valor dispara o trigger novo sem
-- inventar um caminho de reprocessamento paralelo.
DO $do$
DECLARE r record; v integer := 0;
BEGIN
    FOR r IN
        SELECT ps.id, ps.pedido_id, ps.platform_fields
          FROM public.pedido_snapshots ps
          JOIN public.pedidos p ON p.id = ps.pedido_id
         WHERE p.despachado_em IS NULL
           AND p.situacao_pedido_id IN (2, 3, 4)
           AND p.modalidade_logistica_id IS NULL
    LOOP
        UPDATE public.pedido_snapshots SET platform_fields = r.platform_fields WHERE id = r.id;
        v := v + 1;
    END LOOP;
    RAISE NOTICE '[reclassificacao] % snapshots reprocessados', v;
END;
$do$;
