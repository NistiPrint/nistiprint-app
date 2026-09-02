-- Duas regras opostas sobre a mesma tabela impediam qualquer kit de existir:
--
--   validar_componente_ficha_tecnica  -> PROIBE PRODUTO_ACABADO como componente
--   validar_componente_kit            -> EXIGE  PRODUTO_ACABADO como componente
--
-- A primeira e correta para producao: uma agenda nao e insumo de outra agenda.
-- A segunda e correta para venda: um combo E dois produtos acabados vendidos
-- juntos. Faltava a excecao. Verificado em teste: antes desta migration, criar
-- um kit falhava com "Produto acabado nao pode ser componente de BOM".
CREATE OR REPLACE FUNCTION public.validar_componente_ficha_tecnica()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
DECLARE
  v_tipo_componente text;
  v_formato_pai     text;
BEGIN
  SELECT tipo_produto::text INTO v_tipo_componente
    FROM public.produtos WHERE id = NEW.componente_id;

  SELECT formato INTO v_formato_pai
    FROM public.produtos WHERE id = NEW.produto_pai_id;

  IF v_tipo_componente = 'PRODUTO_ACABADO' AND coalesce(v_formato_pai, '') <> 'kit' THEN
    RAISE EXCEPTION 'Produto acabado so pode ser componente de um kit (componente_id=%, pai=%)',
      NEW.componente_id, NEW.produto_pai_id
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$fn$;
