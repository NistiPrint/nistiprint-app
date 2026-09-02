-- `pedidos.modalidade_logistica` (texto) e `is_flex` viram projecao de
-- `modalidade_logistica_id`.
-- Contrato: docs/specs/02-domains/despacho/spec.md
--
-- Antes, a canonizacao Python escrevia o texto adivinhando por sinais textuais,
-- e a classificacao escrevia o id lendo o identificador estavel da plataforma.
-- Dois processos independentes gravando a mesma verdade em campos diferentes —
-- e discordando: 38 pedidos de Retirada e 2 de Turbo estavam marcados como
-- STANDARD. Um pedido nao pode ter duas modalidades.
--
-- A projecao so acontece quando existe id. Sem classificacao, o texto da
-- canonizacao permanece como estava: degradar, nao apagar.
--
-- `logistics_canonicalization` continua existindo como fallback de ingest sem
-- detalhe (pedido vindo via Bling nao carrega package_list), mas deixa de ser
-- autoridade sobre pedido classificado.

CREATE OR REPLACE FUNCTION public.tg_pedidos_sync_is_flex()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_codigo varchar(50);
BEGIN
    IF NEW.modalidade_logistica_id IS NULL THEN
        NEW.is_flex := false;
        RETURN NEW;
    END IF;

    SELECT codigo INTO v_codigo
      FROM public.modalidades_logisticas
     WHERE id = NEW.modalidade_logistica_id;

    NEW.is_flex        := (v_codigo = 'FLEX');
    NEW.is_fulfillment := (v_codigo = 'FULL');

    -- Vocabulario legado na saida. Impressao, alertas, consolidacao e sugestoes
    -- de lote leem esta coluna por nome; traduzir aqui e o que permite trocar a
    -- fonte sem tocar nesses cinco servicos no mesmo commit.
    --
    -- TURBO -> FLEX porque o legado nao tem conceito de Turbo, e Flex e o
    -- comportamento mais proximo (coleta no mesmo dia). Perde granularidade de
    -- proposito: quem precisa da distincao le modalidade_logistica_id.
    NEW.modalidade_logistica := CASE v_codigo
                                  WHEN 'COMUM' THEN 'STANDARD'
                                  WHEN 'FULL'  THEN 'FULFILLMENT'
                                  WHEN 'TURBO' THEN 'FLEX'
                                  ELSE v_codigo
                                END;
    RETURN NEW;
END;
$fn$;

DROP TRIGGER IF EXISTS tg_pedidos_sync_is_flex ON public.pedidos;
CREATE TRIGGER tg_pedidos_sync_is_flex
    BEFORE INSERT OR UPDATE OF modalidade_logistica_id ON public.pedidos
    FOR EACH ROW EXECUTE FUNCTION public.tg_pedidos_sync_is_flex();

COMMENT ON COLUMN public.pedidos.modalidade_logistica IS
  'Projecao legada de modalidade_logistica_id, mantida por trigger. Nao escrever direto: a fonte de verdade e a FK.';

-- Reprojetar o que ja esta classificado.
UPDATE public.pedidos SET modalidade_logistica_id = modalidade_logistica_id
 WHERE modalidade_logistica_id IS NOT NULL;
