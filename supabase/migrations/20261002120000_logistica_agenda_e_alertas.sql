-- Agenda operacional e prazo oficial sao fontes independentes.
-- Ativacao automatica e opt-in por regra; nenhum horario existente muda.
ALTER TABLE public.regras_logisticas_integracao
  ADD COLUMN fonte_agenda text NOT NULL DEFAULT 'MANUAL' CHECK (fonte_agenda IN ('MANUAL','MARKETPLACE')),
  ADD COLUMN modo_corte text NOT NULL DEFAULT 'FIXO' CHECK (modo_corte IN ('FIXO','MARKETPLACE','ANTES_COLETA')),
  ADD COLUMN antecedencia_corte_min integer CHECK (antecedencia_corte_min >= 0),
  ADD COLUMN antecedencia_alerta_min integer NOT NULL DEFAULT 60 CHECK (antecedencia_alerta_min >= 0),
  ADD COLUMN logistic_type text,
  ADD COLUMN coleta_rapida boolean;
ALTER TABLE public.regras_classificacao_modalidade
  ADD COLUMN condicoes jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(condicoes) = 'object');
ALTER TABLE public.pedidos
  ADD COLUMN coleta_confirmada_observada_em timestamptz,
  ADD COLUMN logistica_consultada_em timestamptz;
ALTER TABLE public.modalidades_logisticas DROP CONSTRAINT IF EXISTS modalidades_logisticas_prazo_fixo_ck;

CREATE TABLE public.logistica_agendas (
  integration_id integer REFERENCES public.installed_integrations(id) ON DELETE CASCADE,
  logistic_type text NOT NULL,
  agenda jsonb NOT NULL DEFAULT '{}',
  consultada_em timestamptz,
  tentativa_em timestamptz,
  proxima_tentativa_em timestamptz,
  erro text,
  PRIMARY KEY (integration_id, logistic_type)
);
CREATE TABLE public.logistica_excecoes (
  regra_id bigint REFERENCES public.regras_logisticas_integracao(id) ON DELETE CASCADE,
  dia date NOT NULL,
  janelas jsonb NOT NULL CHECK (jsonb_typeof(janelas) = 'array'),
  motivo text NOT NULL CHECK (btrim(motivo) <> ''),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (regra_id, dia)
);
CREATE TABLE public.logistica_auditoria (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  entidade text NOT NULL, registro text NOT NULL, operacao text NOT NULL,
  anterior jsonb, atual jsonb, ator text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.logistica_sync_cursores (
  nome text PRIMARY KEY, ultimo_id bigint NOT NULL DEFAULT 0,
  bloqueado_ate timestamptz, proxima_tentativa_em timestamptz, ultima_consulta_em timestamptz
);
INSERT INTO public.logistica_sync_cursores(nome,ultima_consulta_em)
  VALUES('janelas-despacho',now()-interval '26 hours');
CREATE INDEX ix_pedidos_logistica_ativa ON public.pedidos (id)
  WHERE marketplace_module_id = 'mercadolivre' AND situacao_pedido_id IN (2,3,4) AND coleta_confirmada_observada_em IS NULL;

ALTER TABLE public.logistica_agendas ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.logistica_excecoes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.logistica_auditoria ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.logistica_sync_cursores ENABLE ROW LEVEL SECURITY;
GRANT ALL ON public.logistica_agendas, public.logistica_excecoes,
  public.logistica_auditoria, public.logistica_sync_cursores TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.logistica_auditoria_id_seq TO service_role;

CREATE FUNCTION public.logistica_auditar() RETURNS trigger LANGUAGE plpgsql
SET search_path TO public, pg_temp AS $$
BEGIN
  INSERT INTO public.logistica_auditoria(entidade, registro, operacao, anterior, atual, ator)
  VALUES (TG_TABLE_NAME, COALESCE(to_jsonb(NEW)->>'id',to_jsonb(OLD)->>'id',
    to_jsonb(NEW)->>'regra_id',to_jsonb(OLD)->>'regra_id'), TG_OP,
    CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END,
    CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END,
    nullif(current_setting('nistiprint.logistica_ator', true),''));
  RETURN COALESCE(NEW, OLD);
END $$;
CREATE TRIGGER logistica_audit_regra AFTER INSERT OR UPDATE OR DELETE ON public.regras_logisticas_integracao
  FOR EACH ROW EXECUTE FUNCTION public.logistica_auditar();
CREATE TRIGGER logistica_audit_modalidade AFTER INSERT OR UPDATE OR DELETE ON public.modalidades_logisticas
  FOR EACH ROW EXECUTE FUNCTION public.logistica_auditar();
CREATE TRIGGER logistica_audit_associacao AFTER INSERT OR UPDATE OR DELETE ON public.regras_classificacao_modalidade
  FOR EACH ROW EXECUTE FUNCTION public.logistica_auditar();
CREATE TRIGGER logistica_audit_excecao AFTER INSERT OR UPDATE OR DELETE ON public.logistica_excecoes
  FOR EACH ROW EXECUTE FUNCTION public.logistica_auditar();

CREATE FUNCTION public.logistica_validar_modalidade() RETURNS trigger LANGUAGE plpgsql
SET search_path TO public, pg_temp AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW.module_id <> OLD.module_id OR NEW.codigo <> OLD.codigo THEN
      RAISE EXCEPTION 'Codigo e marketplace da modalidade sao imutaveis' USING ERRCODE='22023';
    END IF;
    IF NEW.tipo_prazo <> OLD.tipo_prazo AND (
      EXISTS (SELECT 1 FROM public.regras_logisticas_integracao WHERE modalidade_id=OLD.id)
      OR EXISTS (SELECT 1 FROM public.regra_logistica_modalidades WHERE modalidade_id=OLD.id)
      OR EXISTS (SELECT 1 FROM public.demandas_producao WHERE modalidade_id=OLD.id)
      OR EXISTS (SELECT 1 FROM public.regras_classificacao_modalidade WHERE modalidade_id=OLD.id)
      OR EXISTS (SELECT 1 FROM public.pedidos WHERE modalidade_logistica_id=OLD.id)) THEN
      RAISE EXCEPTION 'Modalidade utilizada: cadastre outra para mudar o tipo de prazo' USING ERRCODE='22023';
    END IF;
  END IF;
  IF NEW.tipo_prazo='RELATIVO' AND (COALESCE(NEW.offset_etiqueta_min,0)<=0
    OR COALESCE(NEW.offset_coleta_min,0)<NEW.offset_etiqueta_min) THEN
    RAISE EXCEPTION 'Informe prazos positivos; coleta deve ocorrer apos a etiqueta' USING ERRCODE='22023';
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END $$;
CREATE TRIGGER logistica_validate_modalidade BEFORE INSERT OR UPDATE ON public.modalidades_logisticas
  FOR EACH ROW EXECUTE FUNCTION public.logistica_validar_modalidade();

ALTER TABLE public.regras_logisticas_integracao DROP CONSTRAINT IF EXISTS regras_logisticas_integracao_forma_ck;
CREATE OR REPLACE FUNCTION public.tg_regra_logistica_sync_modalidade() RETURNS trigger LANGUAGE plpgsql
SET search_path TO public, pg_temp AS $$
DECLARE m public.modalidades_logisticas; plataforma text; fechamento time;
BEGIN
  SELECT * INTO STRICT m FROM public.modalidades_logisticas WHERE id=NEW.modalidade_id;
  SELECT module_id INTO plataforma FROM public.installed_integrations WHERE id=NEW.marketplace_integration_id;
  IF plataforma IS DISTINCT FROM m.module_id THEN
    RAISE EXCEPTION 'Modalidade e integracao devem pertencer ao mesmo marketplace' USING ERRCODE='22023';
  END IF;
  NEW.modalidade := CASE m.codigo WHEN 'COMUM' THEN 'STANDARD' ELSE m.codigo END;
  IF m.tipo_prazo='RELATIVO' THEN
    IF COALESCE(NEW.offset_etiqueta_min,0)<=0 OR COALESCE(NEW.offset_coleta_min,0)<NEW.offset_etiqueta_min THEN
      RAISE EXCEPTION 'Informe prazos positivos de etiqueta e coleta' USING ERRCODE='22023';
    END IF;
    NEW.horario_corte:=NULL; NEW.horario_coleta:=NULL; NEW.horario_limite:=NULL;
    NEW.coleta_dia_offset:=0; NEW.dias_semana:=ARRAY[1,2,3,4,5,6,7];
    NEW.fonte_agenda:='MANUAL'; NEW.modo_corte:='FIXO'; NEW.antecedencia_corte_min:=NULL;
  ELSE
    NEW.offset_etiqueta_min:=NULL; NEW.offset_coleta_min:=NULL;
    IF NEW.fonte_agenda='MARKETPLACE' AND (plataforma<>'mercadolivre' OR nullif(btrim(NEW.logistic_type),'') IS NULL) THEN
      RAISE EXCEPTION 'Agenda automatica exige Mercado Livre e tipo logistico' USING ERRCODE='22023';
    END IF;
    IF NEW.modo_corte='FIXO' AND NEW.horario_corte IS NULL THEN
      RAISE EXCEPTION 'Informe a hora de corte fixa' USING ERRCODE='22023';
    END IF;
    IF NEW.modo_corte='ANTES_COLETA' AND NEW.antecedencia_corte_min IS NULL THEN
      RAISE EXCEPTION 'Informe os minutos antes da coleta' USING ERRCODE='22023';
    END IF;
    IF NEW.tipo_envio='PONTO_COLETA' THEN
      SELECT horario_fechamento INTO fechamento FROM public.pontos_coleta WHERE id=NEW.ponto_coleta_id;
      IF NEW.ponto_coleta_id IS NULL THEN
        RAISE EXCEPTION 'Selecione o ponto de coleta' USING ERRCODE='22023';
      END IF;
    END IF;
    IF NEW.fonte_agenda='MANUAL' AND COALESCE(NEW.horario_coleta,fechamento) IS NULL THEN
      RAISE EXCEPTION 'Informe coleta ou fechamento do ponto' USING ERRCODE='22023';
    END IF;
    IF NEW.modo_corte='MARKETPLACE' AND NEW.fonte_agenda<>'MARKETPLACE' THEN
      RAISE EXCEPTION 'Corte do marketplace exige agenda automatica' USING ERRCODE='22023';
    END IF;
    IF NEW.dias_semana IS NULL OR cardinality(NEW.dias_semana)=0 OR NOT NEW.dias_semana::integer[] <@ ARRAY[1,2,3,4,5,6,7] THEN
      RAISE EXCEPTION 'Selecione dias de atendimento validos' USING ERRCODE='22023';
    END IF;
    NEW.horario_limite:=COALESCE(NEW.horario_coleta,fechamento);
    IF NEW.modo_corte='FIXO' AND NEW.horario_limite IS NOT NULL THEN
      NEW.coleta_dia_offset:=CASE WHEN NEW.horario_limite<NEW.horario_corte THEN 1 ELSE 0 END;
    ELSIF NEW.modo_corte<>'FIXO' THEN
      NEW.coleta_dia_offset:=0;
    END IF;
  END IF;
  NEW.updated_at:=now();
  RETURN NEW;
END $$;

-- Um resolvedor de ocorrencias, usado por todas as leituras e pelo worker.
CREATE FUNCTION public.logistica_janelas_efetivas(p_regra_id bigint,p_dia date)
RETURNS TABLE(regra_id bigint,corte_em timestamptz,coleta_em timestamptz,fim_em timestamptz,
  fonte text,desatualizada boolean,tipo_envio text,ponto_coleta_id integer,ponto_nome text,logistic_type text)
LANGUAGE plpgsql STABLE SET search_path TO public, pg_temp AS $$
DECLARE r public.regras_logisticas_integracao; a public.logistica_agendas; excecao jsonb;
  js jsonb; j jsonb; dia_agenda jsonb; fechamento time; nome text;
  coleta timestamp; fim timestamp; corte timestamp; origem text; stale boolean:=false;
  weekday text; fallback boolean:=false;
BEGIN
  SELECT * INTO r FROM public.regras_logisticas_integracao WHERE id=p_regra_id AND ativo;
  IF NOT FOUND OR EXISTS (SELECT 1 FROM public.modalidades_logisticas WHERE id=r.modalidade_id AND (NOT ativo OR tipo_prazo='RELATIVO')) THEN RETURN; END IF;
  SELECT pc.horario_fechamento,pc.nome INTO fechamento,nome FROM public.pontos_coleta pc WHERE pc.id=r.ponto_coleta_id;
  SELECT e.janelas INTO excecao FROM public.logistica_excecoes e WHERE e.regra_id=r.id AND e.dia=p_dia;
  IF excecao IS NOT NULL THEN
    js:=excecao; origem:='EXCECAO';
  ELSIF r.fonte_agenda='MARKETPLACE' THEN
    SELECT ag.* INTO a FROM public.logistica_agendas ag WHERE ag.integration_id=r.marketplace_integration_id AND ag.logistic_type=r.logistic_type;
    weekday:=(ARRAY['monday','tuesday','wednesday','thursday','friday','saturday','sunday'])[extract(isodow FROM p_dia)::int];
    dia_agenda:=a.agenda->weekday;
    stale:=a.consultada_em IS NULL OR a.consultada_em<now()-interval '30 minutes' OR a.erro IS NOT NULL;
    IF dia_agenda IS NOT NULL THEN
      IF NOT COALESCE((dia_agenda->>'work')::boolean,false) THEN RETURN; END IF;
      js:=COALESCE(NULLIF(dia_agenda->'detail','null'::jsonb),'[]'); origem:='MARKETPLACE';
    ELSE fallback:=true; END IF;
  ELSE fallback:=true;
  END IF;
  IF fallback THEN
    IF NOT extract(isodow FROM p_dia)::int=ANY(r.dias_semana) OR COALESCE(r.horario_coleta,fechamento) IS NULL THEN RETURN; END IF;
    js:=jsonb_build_array(jsonb_build_object('from',COALESCE(r.horario_coleta,fechamento)::text,
      'cutoff',r.horario_corte::text,'day_offset',COALESCE(r.coleta_dia_offset,0)));
    origem:=CASE r.fonte_agenda WHEN 'MARKETPLACE' THEN 'CONTINGENCIA' ELSE 'MANUAL' END;
  END IF;
  FOR j IN SELECT value FROM jsonb_array_elements(js) LOOP
    IF origem='MARKETPLACE' AND r.coleta_rapida IS NOT NULL AND COALESCE((j->>'milkrun_same_day')::boolean,false)<>r.coleta_rapida THEN CONTINUE; END IF;
    IF nullif(j->>'from','') IS NULL THEN CONTINUE; END IF;
    coleta:=p_dia+(j->>'from')::time+make_interval(days=>COALESCE((j->>'day_offset')::int,0));
    fim:=CASE WHEN nullif(j->>'to','') IS NOT NULL THEN coleta::date+(j->>'to')::time ELSE coleta END;
    IF fim<coleta THEN fim:=fim+interval '1 day'; END IF;
    corte:=CASE r.modo_corte
      WHEN 'ANTES_COLETA' THEN coleta-make_interval(mins=>r.antecedencia_corte_min)
      WHEN 'MARKETPLACE' THEN CASE WHEN nullif(j->>'cutoff','') IS NOT NULL THEN p_dia+(j->>'cutoff')::time END
      ELSE p_dia+COALESCE(CASE WHEN origem='EXCECAO' THEN nullif(j->>'cutoff','')::time END,r.horario_corte) END;
    IF corte IS NULL THEN CONTINUE; END IF;
    IF corte>coleta AND r.modo_corte='MARKETPLACE' THEN corte:=corte-interval '1 day'; END IF;
    IF corte>coleta THEN CONTINUE; END IF;
    RETURN QUERY SELECT r.id,corte AT TIME ZONE 'America/Sao_Paulo',coleta AT TIME ZONE 'America/Sao_Paulo',
      fim AT TIME ZONE 'America/Sao_Paulo',origem,stale,r.tipo_envio::text,r.ponto_coleta_id,nome,r.logistic_type;
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION public.janelas_logisticas(p_modalidade_id integer,p_integration_id integer,p_dia date)
RETURNS TABLE(tipo_envio text,coleta_em timestamptz,ponto_coleta_id integer,ponto_nome text)
LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
  SELECT j.tipo_envio,j.coleta_em,j.ponto_coleta_id,j.ponto_nome
  FROM public.regras_da_modalidade(p_modalidade_id,p_integration_id) r
  CROSS JOIN LATERAL public.logistica_janelas_efetivas(r.id,p_dia) j ORDER BY j.coleta_em;
$$;
CREATE FUNCTION public.logistica_lotes(p_modalidade_id integer,p_integration_id integer,p_inicio date,p_fim date)
RETURNS TABLE(corte_em timestamptz,coleta_em timestamptz,prazo_final_em timestamptz)
LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
  SELECT j.corte_em,min(j.coleta_em),max(j.coleta_em)
  FROM public.regras_da_modalidade(p_modalidade_id,p_integration_id) r
  CROSS JOIN generate_series(p_inicio,p_fim,interval '1 day') d
  CROSS JOIN LATERAL public.logistica_janelas_efetivas(r.id,d::date) j
  GROUP BY j.corte_em ORDER BY j.corte_em;
$$;
CREATE OR REPLACE FUNCTION public.coleta_do_pedido(p_modalidade_id integer,p_integration_id integer,p_referencia timestamptz,p_agora timestamptz DEFAULT now())
RETURNS TABLE(corte_em timestamptz,coleta_em timestamptz,prazo_final_em timestamptz)
LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
  SELECT j.* FROM public.logistica_lotes(p_modalidade_id,p_integration_id,
    (p_agora AT TIME ZONE 'America/Sao_Paulo')::date-1,(p_agora AT TIME ZONE 'America/Sao_Paulo')::date+21) j
  WHERE j.corte_em>=COALESCE(p_referencia,p_agora) AND j.prazo_final_em>p_agora
  ORDER BY j.corte_em,j.coleta_em LIMIT 1;
$$;
CREATE OR REPLACE FUNCTION public.proxima_janela_logistica(p_modalidade_id integer,p_integration_id integer,p_agora timestamptz DEFAULT now())
RETURNS TABLE(corte_em timestamptz,coleta_em timestamptz)
LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
  SELECT j.corte_em,j.coleta_em FROM public.logistica_lotes(p_modalidade_id,p_integration_id,
    (p_agora AT TIME ZONE 'America/Sao_Paulo')::date-1,(p_agora AT TIME ZONE 'America/Sao_Paulo')::date+21) j
  WHERE j.corte_em>=p_agora ORDER BY j.corte_em LIMIT 1;
$$;
CREATE OR REPLACE FUNCTION public.resolver_compromisso_logistico(p_modalidade_id integer,
  p_integration_id integer,p_data_venda timestamptz,p_agora timestamptz DEFAULT now())
RETURNS timestamptz LANGUAGE plpgsql STABLE SET search_path TO public, pg_temp AS $$
DECLARE m public.modalidades_logisticas; minutos integer; resultado timestamptz;
BEGIN
  SELECT * INTO m FROM public.modalidades_logisticas WHERE id=p_modalidade_id AND ativo;
  IF NOT FOUND THEN RETURN NULL; END IF;
  IF m.tipo_prazo='RELATIVO' THEN
    SELECT r.offset_etiqueta_min INTO minutos FROM public.regras_da_modalidade(m.id,p_integration_id) r
      ORDER BY r.prioridade_uso DESC,r.id LIMIT 1;
    RETURN COALESCE(p_data_venda,p_agora)+make_interval(mins=>COALESCE(minutos,m.offset_etiqueta_min,0));
  END IF;
  SELECT j.corte_em INTO resultado FROM public.coleta_do_pedido(m.id,p_integration_id,p_data_venda,p_agora) j;
  RETURN resultado;
END $$;
CREATE OR REPLACE FUNCTION public.janelas_despacho_vencidas(p_agora timestamptz DEFAULT now(),p_desde interval DEFAULT interval '24 hours')
RETURNS TABLE(integration_id integer,modalidade_id integer,tipo text,janela_em timestamptz)
LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
  WITH limite AS (SELECT least(p_agora-p_desde,COALESCE(
    (SELECT ultima_consulta_em FROM public.logistica_sync_cursores WHERE nome='janelas-despacho'),p_agora-p_desde)) AS inicio)
  SELECT DISTINCT r.marketplace_integration_id,rm.modalidade_id,g.tipo,g.janela_em
  FROM public.regras_logisticas_integracao r
  JOIN public.regra_logistica_modalidades rm ON rm.regra_id=r.id
  JOIN public.modalidades_logisticas m ON m.id=rm.modalidade_id AND m.ativo AND m.entra_na_torre AND m.tipo_prazo='FIXO'
  CROSS JOIN limite l
  CROSS JOIN generate_series((l.inicio AT TIME ZONE 'America/Sao_Paulo')::date-1,
    (p_agora AT TIME ZONE 'America/Sao_Paulo')::date+1,interval '1 day') d
  CROSS JOIN LATERAL public.logistica_janelas_efetivas(r.id,d::date) j
  CROSS JOIN LATERAL (VALUES ('CORTE',j.corte_em),('COLETA',j.coleta_em)) g(tipo,janela_em)
  WHERE g.janela_em>l.inicio AND g.janela_em<=p_agora AND NOT EXISTS (
    SELECT 1 FROM public.janelas_despacho_execucoes e WHERE e.integration_id=r.marketplace_integration_id
      AND e.modalidade_id=rm.modalidade_id AND e.tipo=g.tipo AND e.janela_em=g.janela_em)
  ORDER BY g.janela_em;
$$;

-- Nulos de uma consulta incompleta nunca apagam o prazo oficial anterior.
CREATE FUNCTION public.logistica_preservar_fatos() RETURNS trigger LANGUAGE plpgsql
SET search_path TO public, pg_temp AS $$
BEGIN
  IF TG_OP='UPDATE' THEN
    IF NEW.data_limite_envio IS NULL THEN NEW.data_limite_envio:=OLD.data_limite_envio; END IF;
    IF NEW.data_envio_marketplace IS NULL AND current_setting('nistiprint.corrigir_timestamp_legado',true) IS DISTINCT FROM 'true' THEN
      NEW.data_envio_marketplace:=OLD.data_envio_marketplace;
    END IF;
    NEW.coleta_confirmada_observada_em:=COALESCE(OLD.coleta_confirmada_observada_em,NEW.coleta_confirmada_observada_em);
    IF OLD.despachado_em IS NOT NULL OR EXISTS (SELECT 1 FROM public.demandas_pedidos dp
      JOIN public.demandas_producao d ON d.id=dp.demanda_id WHERE dp.pedido_id=OLD.id AND d.status NOT IN ('RASCUNHO','CANCELADO')) THEN
      NEW.data_coleta:=OLD.data_coleta; NEW.compromisso_logistico_em:=OLD.compromisso_logistico_em;
      NEW.modalidade_logistica_id:=OLD.modalidade_logistica_id; NEW.modalidade_regra_id:=OLD.modalidade_regra_id;
    END IF;
  END IF;
  IF NEW.marketplace_lifecycle_stage IN ('shipped','delivered','shipping_exception') THEN
    NEW.coleta_confirmada_observada_em:=COALESCE(NEW.coleta_confirmada_observada_em,now());
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER logistica_preserve_facts BEFORE INSERT OR UPDATE ON public.pedidos
  FOR EACH ROW EXECUTE FUNCTION public.logistica_preservar_fatos();

CREATE FUNCTION public.logistica_alertas(p_agora timestamptz DEFAULT now()) RETURNS jsonb
LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
  SELECT COALESCE(jsonb_agg(to_jsonb(a) ORDER BY a.prazo_em,a.pedido_id),'[]') FROM (
    SELECT p.id AS pedido_id,p.numero_pedido,p.data_limite_envio AS prazo_em,
      p.situacao_pedido_id,CASE p.situacao_pedido_id WHEN 4 THEN 'Pronto, aguardando coleta' ELSE 'Em preparacao' END AS etapa,
      p.marketplace_integration_id,ii.instance_name AS marketplace_nome,
      COALESCE(r.antecedencia_alerta_min,60) AS antecedencia_min,
      extract(epoch FROM (p.data_limite_envio-p_agora))::integer AS segundos_restantes,
      dm.id AS demanda_id,dm.demanda_id AS demanda_codigo,
      dm.publicado_em IS NOT NULL OR dm.status NOT IN ('RASCUNHO','CANCELADO') AS demanda_publicada
    FROM public.pedidos p
    LEFT JOIN public.installed_integrations ii ON ii.id=p.marketplace_integration_id
    LEFT JOIN public.modalidades_logisticas m ON m.id=p.modalidade_logistica_id
    LEFT JOIN LATERAL (SELECT rr.antecedencia_alerta_min FROM public.regras_da_modalidade(p.modalidade_logistica_id,p.marketplace_integration_id) rr
      ORDER BY rr.prioridade_uso DESC,rr.id LIMIT 1) r ON true
    LEFT JOIN LATERAL (SELECT d.* FROM public.demandas_pedidos dp JOIN public.demandas_producao d ON d.id=dp.demanda_id
      WHERE dp.pedido_id=p.id AND d.status<>'CANCELADO' ORDER BY d.publicado_em DESC NULLS LAST,d.id DESC LIMIT 1) dm ON true
    WHERE p.situacao_pedido_id IN (2,3,4) AND NOT COALESCE(p.is_fulfillment,false)
      AND COALESCE(m.entra_na_torre,true) AND p.coleta_confirmada_observada_em IS NULL
      AND COALESCE(p.marketplace_lifecycle_stage,'') NOT IN ('shipped','delivered','shipping_exception','cancelled','returned')
      AND p.data_limite_envio<=p_agora+make_interval(mins=>COALESCE(r.antecedencia_alerta_min,60))
  ) a;
$$;

-- A classificacao usa os fatos do snapshot; condicoes sao conjuncao, nunca codigo por modalidade.
CREATE FUNCTION public.logistica_condicoes_casam(p_condicoes jsonb,p_fatos jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT NOT EXISTS (SELECT 1 FROM jsonb_each(p_condicoes) c WHERE
    CASE WHEN c.key='tags' THEN NOT COALESCE(p_fatos->'tags','[]') @> c.value
    ELSE p_fatos->c.key IS DISTINCT FROM c.value END);
$$;
CREATE OR REPLACE FUNCTION public.classificar_pedido_modalidade(p_pedido_id integer,p_agora timestamptz DEFAULT now()) RETURNS integer
LANGUAGE plpgsql SET search_path TO public, pg_temp AS $$
DECLARE p public.pedidos; regra public.regras_classificacao_modalidade; pf jsonb; fatos jsonb;
BEGIN
  SELECT * INTO p FROM public.pedidos WHERE id=p_pedido_id;
  IF NOT FOUND THEN RETURN NULL; END IF;
  -- Cadastro nunca reescreve o historico de uma demanda publicada ou pedido encerrado.
  IF p.situacao_pedido_id NOT IN (2,3,4) OR p.despachado_em IS NOT NULL OR EXISTS (
    SELECT 1 FROM public.demandas_pedidos dp JOIN public.demandas_producao d ON d.id=dp.demanda_id
    WHERE dp.pedido_id=p.id AND d.status NOT IN ('RASCUNHO','CANCELADO')) THEN RETURN p.modalidade_logistica_id; END IF;
  SELECT platform_fields INTO pf FROM public.pedido_snapshots WHERE pedido_id=p.id LIMIT 1;
  fatos:=jsonb_build_object('service',COALESCE(pf#>'{mercadolivre,sla,service}',pf#>'{mercadolivre,sla,0,service}',
    pf#>'{shopee,shipping_carrier}'),'tags',COALESCE(pf#>'{mercadolivre,shipment,tags}',pf#>'{shopee,tags}','[]'));
  SELECT r.* INTO regra FROM public.regras_classificacao_modalidade r
  JOIN public.modalidades_logisticas m ON m.id=r.modalidade_id AND m.ativo AND m.module_id=r.module_id
  CROSS JOIN LATERAL (SELECT CASE r.alvo WHEN 'CHAVE' THEN p.metodo_envio_chave WHEN 'ROTULO' THEN p.metodo_envio_rotulo ELSE p.modalidade_logistica END AS valor) v
  WHERE r.ativo AND r.module_id=p.marketplace_module_id AND (r.integration_id IS NULL OR r.integration_id=p.marketplace_integration_id)
    AND (nullif(btrim(p.metodo_envio_chave),'') IS NULL OR r.alvo='CHAVE')
    AND v.valor IS NOT NULL AND public.logistica_condicoes_casam(r.condicoes,fatos)
    AND CASE r.operador
      WHEN 'IGUAL' THEN CASE WHEN r.case_sensitive THEN v.valor=btrim(r.valor) ELSE lower(btrim(v.valor))=lower(btrim(r.valor)) END
      WHEN 'CONTEM' THEN CASE WHEN r.case_sensitive THEN position(r.valor in v.valor)>0 ELSE position(lower(r.valor) in lower(v.valor))>0 END
      WHEN 'PREFIXO' THEN CASE WHEN r.case_sensitive THEN v.valor LIKE r.valor||'%' ELSE lower(v.valor) LIKE lower(r.valor)||'%' END
      WHEN 'REGEX' THEN CASE WHEN r.case_sensitive THEN v.valor~r.valor ELSE v.valor~*r.valor END ELSE false END
  ORDER BY (SELECT count(*) FROM jsonb_each(r.condicoes)) DESC,(r.integration_id IS NULL),r.prioridade,r.id LIMIT 1;
  UPDATE public.pedidos SET modalidade_logistica_id=regra.modalidade_id,modalidade_regra_id=regra.id,modalidade_classificada_em=p_agora,
    data_coleta=CASE WHEN regra.id IS NOT NULL THEN CASE WHEN (SELECT tipo_prazo FROM public.modalidades_logisticas WHERE id=regra.modalidade_id)='RELATIVO'
      THEN COALESCE(p.data_venda AT TIME ZONE 'America/Sao_Paulo',p_agora)+make_interval(mins=>(SELECT COALESCE(rr.offset_coleta_min,m.offset_coleta_min)
        FROM public.modalidades_logisticas m LEFT JOIN LATERAL (SELECT offset_coleta_min FROM public.regras_da_modalidade(m.id,p.marketplace_integration_id)
          ORDER BY prioridade_uso DESC,id LIMIT 1) rr ON true WHERE m.id=regra.modalidade_id))
      ELSE (SELECT c.coleta_em FROM public.coleta_do_pedido(regra.modalidade_id,p.marketplace_integration_id,
        COALESCE(p.data_pagamento_marketplace,p.data_compra_marketplace,p.data_venda AT TIME ZONE 'America/Sao_Paulo'),p_agora) c) END END,
    compromisso_logistico_em=CASE WHEN regra.id IS NOT NULL THEN public.resolver_compromisso_logistico(regra.modalidade_id,p.marketplace_integration_id,p.data_venda AT TIME ZONE 'America/Sao_Paulo',p_agora) END
    WHERE id=p.id;
  RETURN regra.modalidade_id;
END $$;

-- Valores historicos aproximados sao marcados para reconciliacao, sem apagar o dado legado.
UPDATE public.pedido_snapshots SET logistics=logistics||jsonb_build_object('deadline_estimated',true)
  WHERE logistics->>'dispatch_deadline_source' LIKE '%buffering%'
    OR (platform_fields#>>'{mercadolivre,shipment,lead_time,buffering,date}' IS NOT NULL
      AND COALESCE(platform_fields#>>'{mercadolivre,sla,expected_date}',platform_fields#>>'{mercadolivre,sla,0,expected_date}') IS NULL);

CREATE FUNCTION public.logistica_preservar_snapshot() RETURNS trigger LANGUAGE plpgsql
SET search_path TO public, pg_temp AS $$
DECLARE chave text;
BEGIN
  IF TG_OP='UPDATE' AND COALESCE(nullif(NEW.logistics->>'deadline',''),nullif(NEW.logistics->>'expected_date',''),nullif(NEW.logistics->>'ship_by_date','')) IS NULL THEN
    FOREACH chave IN ARRAY ARRAY['deadline','expected_date','ship_by_date','dispatch_deadline_source','deadline_estimated'] LOOP
      IF OLD.logistics ? chave THEN NEW.logistics:=jsonb_set(NEW.logistics,ARRAY[chave],OLD.logistics->chave); END IF;
    END LOOP;
  END IF;
  IF NEW.logistics->>'dispatch_deadline_source'='mercadolivre.sla.expected_date' THEN
    NEW.logistics:=NEW.logistics||jsonb_build_object('deadline_estimated',false);
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER logistica_preserve_snapshot BEFORE INSERT OR UPDATE ON public.pedido_snapshots
  FOR EACH ROW EXECUTE FUNCTION public.logistica_preservar_snapshot();

-- Somente horarios comprovadamente derivados de date_closed sao corrigidos.
DO $$
DECLARE linha record; fechado timestamptz;
BEGIN
  PERFORM set_config('nistiprint.corrigir_timestamp_legado','true',true);
  FOR linha IN SELECT p.id,p.data_envio_marketplace,s.id AS snapshot_id,
      s.platform_fields#>>'{mercadolivre,order,date_closed}' AS date_closed
    FROM public.pedidos p JOIN public.pedido_snapshots s ON s.pedido_id=p.id
    WHERE p.marketplace_module_id='mercadolivre' AND p.data_envio_marketplace IS NOT NULL
      AND COALESCE(s.platform_fields#>>'{mercadolivre,shipment,date_shipped}',
        s.platform_fields#>>'{mercadolivre,shipment,status_history,date_shipped}') IS NULL
  LOOP
    BEGIN fechado:=linha.date_closed::timestamptz; EXCEPTION WHEN OTHERS THEN CONTINUE; END;
    IF fechado=linha.data_envio_marketplace THEN
      UPDATE public.pedidos SET data_envio_marketplace=NULL WHERE id=linha.id;
      UPDATE public.pedido_snapshots SET logistics=(logistics-'marketplace_shipped_at')||jsonb_build_object(
        'legacy_order_closed_at',linha.date_closed,'dispatch_timestamp_source','legacy_order_closed') WHERE id=linha.snapshot_id;
    END IF;
  END LOOP;
  PERFORM set_config('nistiprint.corrigir_timestamp_legado','false',true);
END $$;

-- As funcoes de escrita ficam disponiveis apenas ao backend.
REVOKE ALL ON FUNCTION public.logistica_alertas(timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.logistica_alertas(timestamptz) TO service_role;
