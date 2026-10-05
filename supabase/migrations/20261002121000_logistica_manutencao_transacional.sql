ALTER TABLE public.demandas_producao ADD COLUMN logistica_divergencia jsonb;

CREATE FUNCTION public.logistica_congelar_prazo_demanda() RETURNS trigger LANGUAGE plpgsql
SET search_path TO public, pg_temp AS $$
DECLARE prazo timestamptz;
BEGIN
  IF (NEW.publicado_em IS NOT NULL OR NEW.status NOT IN ('RASCUNHO','CANCELADO')) AND
    (TG_OP='INSERT' OR OLD.status='RASCUNHO' OR NOT COALESCE(NEW.escopo_despacho,'{}') ? 'prazo_oficial_em') THEN
    SELECT min(p.data_limite_envio) INTO prazo FROM public.demandas_pedidos dp JOIN public.pedidos p ON p.id=dp.pedido_id
      WHERE dp.demanda_id=NEW.id;
    NEW.escopo_despacho:=COALESCE(NEW.escopo_despacho,'{}')||jsonb_build_object('prazo_oficial_em',prazo);
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER logistica_freeze_demanda BEFORE INSERT OR UPDATE ON public.demandas_producao
  FOR EACH ROW EXECUTE FUNCTION public.logistica_congelar_prazo_demanda();
-- Registrar a referencia inicial antes de futuras alteracoes de SLA/agenda.
UPDATE public.demandas_producao SET escopo_despacho=COALESCE(escopo_despacho,'{}')
  WHERE status NOT IN ('RASCUNHO','CANCELADO','CONCLUIDO');

-- Algumas publicacoes criam a demanda antes de inserir seus vinculos.
-- Capturar o prazo apos o INSERT completo, sem congelar somente o primeiro pedido.
CREATE FUNCTION public.logistica_prazo_apos_vinculos() RETURNS trigger LANGUAGE plpgsql
SET search_path TO public, pg_temp AS $$
BEGIN
  UPDATE public.demandas_producao d SET escopo_despacho=COALESCE(d.escopo_despacho,'{}')||
    jsonb_build_object('prazo_oficial_em',(SELECT min(p.data_limite_envio) FROM public.demandas_pedidos dp
      JOIN public.pedidos p ON p.id=dp.pedido_id WHERE dp.demanda_id=d.id))
    WHERE EXISTS(SELECT 1 FROM novos_vinculos n WHERE n.demanda_id=d.id)
      AND (d.publicado_em IS NOT NULL OR d.status NOT IN ('RASCUNHO','CANCELADO'))
      AND (d.escopo_despacho->>'prazo_oficial_em') IS NULL;
  RETURN NULL;
END $$;
CREATE TRIGGER logistica_freeze_apos_vinculos AFTER INSERT ON public.demandas_pedidos
  REFERENCING NEW TABLE AS novos_vinculos FOR EACH STATEMENT EXECUTE FUNCTION public.logistica_prazo_apos_vinculos();

CREATE FUNCTION public.logistica_janelas_do_lote(p_modalidade_id integer,p_integration_id integer,p_corte timestamptz)
RETURNS jsonb LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
  SELECT COALESCE(jsonb_agg(jsonb_build_object('tipo_envio',j.tipo_envio,'em',j.coleta_em,
    'ponto_coleta_id',j.ponto_coleta_id,'ponto_nome',j.ponto_nome) ORDER BY j.coleta_em),'[]')
  FROM public.regras_da_modalidade(p_modalidade_id,p_integration_id) r
  CROSS JOIN generate_series((p_corte AT TIME ZONE 'America/Sao_Paulo')::date-1,
    (p_corte AT TIME ZONE 'America/Sao_Paulo')::date+14,interval '1 day') dia
  CROSS JOIN LATERAL public.logistica_janelas_efetivas(r.id,dia::date) j WHERE j.corte_em=p_corte;
$$;

CREATE FUNCTION public.logistica_atualizar_dependentes(p_integration_id integer DEFAULT NULL)
RETURNS integer LANGUAGE plpgsql SET search_path TO public, pg_temp AS $$
DECLARE qtd integer; d record; atual record; prazo timestamptz; janelas jsonb; registradas jsonb; dia_registrado date;
BEGIN
  WITH alvo AS (
    SELECT p.id,j.corte_em,j.coleta_em FROM public.pedidos p
    LEFT JOIN LATERAL public.coleta_do_pedido(p.modalidade_logistica_id,p.marketplace_integration_id,
      COALESCE(p.data_pagamento_marketplace,p.data_compra_marketplace,p.data_venda AT TIME ZONE 'America/Sao_Paulo')) j ON true
    WHERE p.situacao_pedido_id IN (2,3,4) AND p.despachado_em IS NULL
      AND EXISTS (SELECT 1 FROM public.modalidades_logisticas m WHERE m.id=p.modalidade_logistica_id AND m.tipo_prazo='FIXO')
      AND (p_integration_id IS NULL OR p.marketplace_integration_id=p_integration_id))
  UPDATE public.pedidos p SET data_coleta=a.coleta_em,compromisso_logistico_em=a.corte_em
    FROM alvo a WHERE p.id=a.id AND (p.data_coleta IS DISTINCT FROM a.coleta_em OR p.compromisso_logistico_em IS DISTINCT FROM a.corte_em);
  GET DIAGNOSTICS qtd=ROW_COUNT;
  UPDATE public.pedidos p SET compromisso_logistico_em=public.resolver_compromisso_logistico(m.id,p.marketplace_integration_id,
      COALESCE(p.data_pagamento_marketplace,p.data_compra_marketplace,p.data_venda AT TIME ZONE 'America/Sao_Paulo')),
    data_coleta=(public.logistica_contexto_coleta(p.marketplace_integration_id,m.codigo,
      COALESCE(p.data_pagamento_marketplace,p.data_compra_marketplace,p.data_venda AT TIME ZONE 'America/Sao_Paulo'),now(),m.id)->>'data_coleta')::timestamptz
    FROM public.modalidades_logisticas m WHERE m.id=p.modalidade_logistica_id AND m.tipo_prazo='RELATIVO'
      AND p.situacao_pedido_id IN (2,3,4) AND p.despachado_em IS NULL
      AND (p_integration_id IS NULL OR p.marketplace_integration_id=p_integration_id);
  FOR d IN SELECT DISTINCT dp.demanda_id,dm.status,dm.data_coleta,dm.escopo_despacho,
    EXISTS(SELECT 1 FROM public.demandas_pedidos dx JOIN public.pedidos px ON px.id=dx.pedido_id
      JOIN public.modalidades_logisticas mx ON mx.id=px.modalidade_logistica_id
      WHERE dx.demanda_id=dm.id AND mx.tipo_prazo='FIXO') AS tem_janela_fixa
    FROM public.demandas_pedidos dp
    JOIN public.demandas_producao dm ON dm.id=dp.demanda_id JOIN public.pedidos p ON p.id=dp.pedido_id
    WHERE p.situacao_pedido_id IN (2,3,4) AND (p_integration_id IS NULL OR p.marketplace_integration_id=p_integration_id)
  LOOP
    SELECT min(p.data_limite_envio) INTO prazo FROM public.demandas_pedidos dp JOIN public.pedidos p ON p.id=dp.pedido_id
      WHERE dp.demanda_id=d.demanda_id AND p.situacao_pedido_id IN (2,3,4);
    SELECT min(CASE WHEN m.tipo_prazo='RELATIVO' THEN
      (public.logistica_contexto_coleta(p.marketplace_integration_id,m.codigo,
        COALESCE(p.data_pagamento_marketplace,p.data_compra_marketplace,p.data_venda AT TIME ZONE 'America/Sao_Paulo'),now(),m.id)->>'data_coleta')::timestamptz
      ELSE j.coleta_em END) AS coleta_em,
      min(CASE WHEN m.tipo_prazo='RELATIVO' THEN public.resolver_compromisso_logistico(m.id,p.marketplace_integration_id,
        COALESCE(p.data_pagamento_marketplace,p.data_compra_marketplace,p.data_venda AT TIME ZONE 'America/Sao_Paulo')) ELSE j.corte_em END) AS corte_em INTO atual
      FROM public.demandas_pedidos dp JOIN public.pedidos p ON p.id=dp.pedido_id
      JOIN public.modalidades_logisticas m ON m.id=p.modalidade_logistica_id
      LEFT JOIN LATERAL public.coleta_do_pedido(p.modalidade_logistica_id,p.marketplace_integration_id,
        COALESCE(p.data_pagamento_marketplace,p.data_compra_marketplace,p.data_venda AT TIME ZONE 'America/Sao_Paulo')) j ON true
      WHERE dp.demanda_id=d.demanda_id AND p.situacao_pedido_id IN (2,3,4);
    dia_registrado:=NULL;
    -- Uma demanda publicada e comparada com a sua data congelada; a passagem
    -- natural do relogio nao significa que alguem mudou a agenda.
    IF d.status<>'RASCUNHO' AND d.tem_janela_fixa THEN
      dia_registrado:=(COALESCE(d.data_coleta,(d.escopo_despacho#>>'{janelas,0,em}')::timestamptz) AT TIME ZONE 'America/Sao_Paulo')::date;
      SELECT j.coleta_em,j.corte_em INTO atual
        FROM public.demandas_pedidos dp JOIN public.pedidos p ON p.id=dp.pedido_id
        CROSS JOIN public.regras_da_modalidade(p.modalidade_logistica_id,p.marketplace_integration_id) r
        CROSS JOIN generate_series(dia_registrado-1,dia_registrado,interval '1 day') dia
        CROSS JOIN LATERAL public.logistica_janelas_efetivas(r.id,dia::date) j
        WHERE dp.demanda_id=d.demanda_id AND (j.coleta_em AT TIME ZONE 'America/Sao_Paulo')::date=dia_registrado
        ORDER BY abs(extract(epoch FROM (j.coleta_em-COALESCE(d.data_coleta,(d.escopo_despacho#>>'{janelas,0,em}')::timestamptz)))) LIMIT 1;
    END IF;
    SELECT COALESCE(jsonb_agg(x.janela ORDER BY (x.janela->>'em')::timestamptz),'[]') INTO janelas FROM (
      SELECT DISTINCT janela FROM public.demandas_pedidos dp JOIN public.pedidos p ON p.id=dp.pedido_id
      CROSS JOIN LATERAL jsonb_array_elements(public.logistica_janelas_do_lote(p.modalidade_logistica_id,p.marketplace_integration_id,atual.corte_em)) janela
      WHERE dp.demanda_id=d.demanda_id) x;
    registradas:=d.escopo_despacho->'janelas';
    IF NOT d.tem_janela_fixa THEN
      dia_registrado:=(d.data_coleta AT TIME ZONE 'America/Sao_Paulo')::date;
      janelas:=COALESCE(registradas,'[]');
    END IF;
    UPDATE public.demandas_producao SET
      data_coleta=CASE WHEN status='RASCUNHO' THEN atual.coleta_em ELSE data_coleta END,
      escopo_despacho=CASE WHEN status='RASCUNHO' THEN COALESCE(escopo_despacho,'{}')||jsonb_build_object(
        'coleta_em',atual.coleta_em,'corte_em',atual.corte_em,'prazo_oficial_em',prazo,'janelas',janelas,
        'prazo_final_em',(SELECT max((value->>'em')::timestamptz) FROM jsonb_array_elements(janelas))) ELSE escopo_despacho END,
      logistica_divergencia=CASE WHEN status<>'RASCUNHO' AND
        ((dia_registrado IS NOT NULL AND COALESCE(data_coleta,(escopo_despacho#>>'{janelas,0,em}')::timestamptz) IS DISTINCT FROM atual.coleta_em) OR
          (registradas IS NOT NULL AND registradas IS DISTINCT FROM janelas) OR
          (escopo_despacho ? 'corte_em' AND (escopo_despacho->>'corte_em')::timestamptz IS DISTINCT FROM atual.corte_em) OR
          (escopo_despacho ? 'prazo_oficial_em' AND (escopo_despacho->>'prazo_oficial_em')::timestamptz IS DISTINCT FROM prazo))
        THEN jsonb_build_object('coleta_registrada',data_coleta,'coleta_atual',atual.coleta_em,
          'corte_registrado',escopo_despacho->'corte_em','corte_atual',atual.corte_em,
          'prazo_atual',prazo,'prazo_registrado',escopo_despacho->'prazo_oficial_em') END
      WHERE id=d.demanda_id AND status NOT IN ('CONCLUIDO','CANCELADO');
  END LOOP;
  UPDATE public.demandas_producao dm SET logistica_divergencia=NULL WHERE logistica_divergencia IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM public.demandas_pedidos dp JOIN public.pedidos p ON p.id=dp.pedido_id WHERE dp.demanda_id=dm.id
      AND p.situacao_pedido_id IN (2,3,4) AND p.coleta_confirmada_observada_em IS NULL);
  RETURN qtd;
END $$;

-- Contrato de leitura dos consumidores Python; o calendario e resolvido apenas no SQL.
CREATE FUNCTION public.logistica_contexto_coleta(p_integration_id integer,p_modalidade text,
  p_referencia timestamptz DEFAULT NULL,p_agora timestamptz DEFAULT now(),p_modalidade_id integer DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path TO public, pg_temp AS $$
DECLARE m public.modalidades_logisticas; r public.regras_logisticas_integracao; c record; j record;
  coleta timestamptz; corte timestamptz; final timestamptz; dados jsonb;
BEGIN
  SELECT ml.* INTO m FROM public.modalidades_logisticas ml JOIN public.installed_integrations ii ON ii.module_id=ml.module_id
    WHERE ii.id=p_integration_id AND ml.ativo AND
      CASE WHEN p_modalidade_id IS NOT NULL THEN ml.id=p_modalidade_id
        ELSE ml.codigo=CASE upper(COALESCE(p_modalidade,'STANDARD')) WHEN 'STANDARD' THEN 'COMUM' WHEN 'EXPRESS' THEN 'FLEX' ELSE upper(p_modalidade) END END LIMIT 1;
  SELECT * INTO r FROM public.regras_da_modalidade(m.id,p_integration_id) ORDER BY prioridade_uso DESC,id LIMIT 1;
  dados:=jsonb_build_object('marketplace_integration_id',p_integration_id,'modalidade',p_modalidade,'tem_regra',r.id IS NOT NULL);
  IF r.id IS NULL THEN RETURN dados||jsonb_build_object('janela_status','SEM_REGRA'); END IF;
  IF m.tipo_prazo='RELATIVO' THEN
    corte:=COALESCE(p_referencia,p_agora)+make_interval(mins=>COALESCE(r.offset_etiqueta_min,m.offset_etiqueta_min));
    coleta:=COALESCE(p_referencia,p_agora)+make_interval(mins=>COALESCE(r.offset_coleta_min,m.offset_coleta_min));
    final:=coleta;
  ELSE
    SELECT * INTO c FROM public.coleta_do_pedido(m.id,p_integration_id,p_referencia,p_agora);
    corte:=c.corte_em; coleta:=c.coleta_em; final:=c.prazo_final_em;
    IF coleta IS NULL THEN RETURN dados||jsonb_build_object('janela_status','SEM_ATENDIMENTO'); END IF;
    SELECT x.* INTO j FROM public.regras_da_modalidade(m.id,p_integration_id) rr
      CROSS JOIN generate_series((corte AT TIME ZONE 'America/Sao_Paulo')::date-1,(coleta AT TIME ZONE 'America/Sao_Paulo')::date+1,interval '1 day') dia
      CROSS JOIN LATERAL public.logistica_janelas_efetivas(rr.id,dia::date) x
      WHERE x.corte_em=corte AND x.coleta_em=coleta LIMIT 1;
    SELECT * INTO r FROM public.regras_logisticas_integracao WHERE id=j.regra_id;
  END IF;
  RETURN dados||jsonb_build_object('data_coleta',coleta,'proxima_coleta_at',coleta,
    'proxima_coleta_horario',to_char(coleta AT TIME ZONE 'America/Sao_Paulo','HH24:MI'),
    'proxima_coleta_tipo_envio',r.tipo_envio,'proxima_coleta_ponto_id',r.ponto_coleta_id,
    'proxima_coleta_ponto_nome',(SELECT nome FROM public.pontos_coleta WHERE id=r.ponto_coleta_id),
    'deadline_final_horario',to_char(final AT TIME ZONE 'America/Sao_Paulo','HH24:MI'),
    'horario_corte',to_char(corte AT TIME ZONE 'America/Sao_Paulo','HH24:MI'),
    'horario_coleta',to_char(coleta AT TIME ZONE 'America/Sao_Paulo','HH24:MI'),
    'janela_status',CASE WHEN (coleta AT TIME ZONE 'America/Sao_Paulo')::date=(p_agora AT TIME ZONE 'America/Sao_Paulo')::date THEN 'MESMO_DIA' ELSE 'PROXIMA' END,
    'minutos_ate_proxima_coleta',greatest(0,floor(extract(epoch FROM coleta-p_agora)/60)),
    'regra',jsonb_build_object('id',r.id,'horario_corte',to_char(corte AT TIME ZONE 'America/Sao_Paulo','HH24:MI'),
      'horario_coleta',to_char(coleta AT TIME ZONE 'America/Sao_Paulo','HH24:MI'),'tipo_envio',r.tipo_envio,'prioridade_uso',r.prioridade_uso));
END $$;
REVOKE ALL ON FUNCTION public.logistica_contexto_coleta(integer,text,timestamptz,timestamptz,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.logistica_contexto_coleta(integer,text,timestamptz,timestamptz,integer) TO service_role;

CREATE FUNCTION public.logistica_salvar_modalidade(p_id integer,p_dados jsonb,p_ator text DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql SET search_path TO public, pg_temp AS $$
DECLARE m public.modalidades_logisticas;
BEGIN
  PERFORM set_config('nistiprint.logistica_ator',COALESCE(p_ator,''),true);
  IF p_id IS NOT NULL THEN
    SELECT * INTO STRICT m FROM public.modalidades_logisticas WHERE id=p_id FOR UPDATE;
    m:=jsonb_populate_record(m,p_dados);
    UPDATE public.modalidades_logisticas SET codigo=m.codigo,module_id=m.module_id,nome=m.nome,tipo_prazo=m.tipo_prazo,
      politica_lote=m.politica_lote,nivel_interrupcao=m.nivel_interrupcao,entra_na_torre=m.entra_na_torre,
      entrega_rapida=m.entrega_rapida,ativo=m.ativo,cor=m.cor,ordem_exibicao=m.ordem_exibicao,
      offset_etiqueta_min=m.offset_etiqueta_min,offset_coleta_min=m.offset_coleta_min
      WHERE id=p_id RETURNING * INTO m;
  ELSE
    INSERT INTO public.modalidades_logisticas(module_id,codigo,nome,tipo_prazo,politica_lote,nivel_interrupcao,
      entra_na_torre,entrega_rapida,ativo,cor,ordem_exibicao,offset_etiqueta_min,offset_coleta_min)
    VALUES(p_dados->>'module_id',p_dados->>'codigo',p_dados->>'nome',COALESCE(p_dados->>'tipo_prazo','FIXO'),
      COALESCE(p_dados->>'politica_lote','LOTE'),COALESCE((p_dados->>'nivel_interrupcao')::smallint,0),
      COALESCE((p_dados->>'entra_na_torre')::boolean,true),COALESCE((p_dados->>'entrega_rapida')::boolean,false),
      COALESCE((p_dados->>'ativo')::boolean,true),p_dados->>'cor',COALESCE((p_dados->>'ordem_exibicao')::smallint,100),
      (p_dados->>'offset_etiqueta_min')::int,(p_dados->>'offset_coleta_min')::int) RETURNING * INTO m;
  END IF;
  PERFORM public.classificar_pedido_modalidade(p.id) FROM public.pedidos p
    WHERE p.marketplace_module_id=m.module_id AND p.situacao_pedido_id IN (2,3,4) AND p.despachado_em IS NULL;
  PERFORM public.logistica_atualizar_dependentes();
  RETURN to_jsonb(m);
END $$;

CREATE FUNCTION public.logistica_salvar_regra(p_id bigint,p_dados jsonb,p_ator text DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql SET search_path TO public, pg_temp AS $$
DECLARE r public.regras_logisticas_integracao; mids jsonb; mid integer; anterior_mid integer;
BEGIN
  PERFORM set_config('nistiprint.logistica_ator',COALESCE(p_ator,''),true);
  IF p_id IS NOT NULL THEN
    SELECT * INTO STRICT r FROM public.regras_logisticas_integracao WHERE id=p_id FOR UPDATE;
    anterior_mid:=r.modalidade_id;
    IF p_dados ? 'marketplace_integration_id' AND (p_dados->>'marketplace_integration_id')::int<>r.marketplace_integration_id THEN
      RAISE EXCEPTION 'A conta da janela e imutavel' USING ERRCODE='22023';
    END IF;
    r:=jsonb_populate_record(r,p_dados-'modalidade_ids');
    UPDATE public.regras_logisticas_integracao SET modalidade_id=r.modalidade_id,tipo_envio=r.tipo_envio,
      horario_corte=r.horario_corte,horario_coleta=r.horario_coleta,ponto_coleta_id=r.ponto_coleta_id,
      dias_semana=r.dias_semana,prioridade_uso=r.prioridade_uso,ativo=r.ativo,descricao=r.descricao,
      offset_etiqueta_min=r.offset_etiqueta_min,offset_coleta_min=r.offset_coleta_min,
      fonte_agenda=r.fonte_agenda,modo_corte=r.modo_corte,antecedencia_corte_min=r.antecedencia_corte_min,
      antecedencia_alerta_min=r.antecedencia_alerta_min,logistic_type=r.logistic_type,coleta_rapida=r.coleta_rapida
      WHERE id=p_id RETURNING * INTO r;
  ELSE
    r:=jsonb_populate_record(NULL::public.regras_logisticas_integracao,p_dados-'modalidade_ids');
    INSERT INTO public.regras_logisticas_integracao(marketplace_integration_id,modalidade_id,modalidade,tipo_envio,
      horario_corte,horario_coleta,ponto_coleta_id,dias_semana,prioridade_uso,ativo,descricao,
      offset_etiqueta_min,offset_coleta_min,fonte_agenda,modo_corte,antecedencia_corte_min,antecedencia_alerta_min,logistic_type,coleta_rapida)
    VALUES(r.marketplace_integration_id,r.modalidade_id,'STANDARD',r.tipo_envio,r.horario_corte,r.horario_coleta,
      r.ponto_coleta_id,COALESCE(r.dias_semana,ARRAY[1,2,3,4,5]),COALESCE(r.prioridade_uso,100),COALESCE(r.ativo,true),
      r.descricao,r.offset_etiqueta_min,r.offset_coleta_min,COALESCE(r.fonte_agenda,'MANUAL'),COALESCE(r.modo_corte,'FIXO'),
      r.antecedencia_corte_min,COALESCE(r.antecedencia_alerta_min,60),r.logistic_type,r.coleta_rapida) RETURNING * INTO r;
  END IF;
  IF p_dados ? 'modalidade_ids' THEN
    mids:=(p_dados->'modalidade_ids')||jsonb_build_array(r.modalidade_id);
    FOR mid IN SELECT DISTINCT value::int FROM jsonb_array_elements_text(mids) LOOP
      IF NOT EXISTS(SELECT 1 FROM public.modalidades_logisticas m JOIN public.installed_integrations ii ON ii.module_id=m.module_id
        WHERE m.id=mid AND ii.id=r.marketplace_integration_id AND (mid=r.modalidade_id OR m.tipo_prazo='FIXO')) THEN
        RAISE EXCEPTION 'Modalidade compartilhada incompativel' USING ERRCODE='22023';
      END IF;
    END LOOP;
    DELETE FROM public.regra_logistica_modalidades WHERE regra_id=r.id AND NOT modalidade_id IN (SELECT value::int FROM jsonb_array_elements_text(mids));
    INSERT INTO public.regra_logistica_modalidades(regra_id,modalidade_id)
      SELECT r.id,value::int FROM jsonb_array_elements_text(mids) ON CONFLICT DO NOTHING;
  ELSE
    IF anterior_mid IS DISTINCT FROM r.modalidade_id AND anterior_mid IS NOT NULL THEN
      DELETE FROM public.regra_logistica_modalidades WHERE regra_id=r.id AND modalidade_id=anterior_mid;
    END IF;
    INSERT INTO public.regra_logistica_modalidades(regra_id,modalidade_id) VALUES(r.id,r.modalidade_id) ON CONFLICT DO NOTHING;
  END IF;
  PERFORM public.logistica_atualizar_dependentes(r.marketplace_integration_id);
  RETURN to_jsonb(r);
END $$;

CREATE FUNCTION public.logistica_associar(p_module_id text,p_chave text,p_modalidade_id integer,
  p_condicoes jsonb DEFAULT '{}',p_id integer DEFAULT NULL,p_ator text DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql SET search_path TO public, pg_temp AS $$
DECLARE rid integer; antigo public.regras_classificacao_modalidade; n integer:=0; p record; cond jsonb:=COALESCE(p_condicoes,'{}');
BEGIN
  PERFORM set_config('nistiprint.logistica_ator',COALESCE(p_ator,''),true);
  IF nullif(btrim(p_chave),'') IS NULL THEN RAISE EXCEPTION 'Identificador obrigatorio' USING ERRCODE='22023'; END IF;
  IF jsonb_typeof(cond)<>'object' OR EXISTS(SELECT 1 FROM jsonb_object_keys(cond) k WHERE k NOT IN ('service','tags'))
    OR (cond ? 'service' AND jsonb_typeof(cond->'service')<>'string')
    OR (cond ? 'tags' AND jsonb_typeof(cond->'tags')<>'array') THEN
    RAISE EXCEPTION 'Condicoes aceitam servico e lista de tags' USING ERRCODE='22023';
  END IF;
  IF p_modalidade_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.modalidades_logisticas WHERE id=p_modalidade_id AND module_id=p_module_id AND ativo) THEN
    RAISE EXCEPTION 'Modalidade deve estar ativa e pertencer ao marketplace' USING ERRCODE='22023';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtext('logistica-associar'),hashtext(p_module_id||lower(btrim(p_chave))));
  IF p_id IS NOT NULL THEN
    SELECT * INTO STRICT antigo FROM public.regras_classificacao_modalidade WHERE id=p_id AND module_id=p_module_id AND integration_id IS NULL AND alvo='CHAVE' FOR UPDATE;
    rid:=antigo.id;
  ELSE
    SELECT id INTO rid FROM public.regras_classificacao_modalidade WHERE module_id=p_module_id AND integration_id IS NULL
      AND alvo='CHAVE' AND lower(btrim(valor))=lower(btrim(p_chave)) AND condicoes=cond ORDER BY id LIMIT 1;
  END IF;
  IF EXISTS(SELECT 1 FROM public.regras_classificacao_modalidade WHERE module_id=p_module_id AND integration_id IS NULL
    AND alvo='CHAVE' AND lower(btrim(valor))=lower(btrim(p_chave)) AND condicoes=cond AND ativo AND id IS DISTINCT FROM rid) THEN
    RAISE EXCEPTION 'Ja existe uma associacao ativa para este identificador e condicoes' USING ERRCODE='23505';
  END IF;
  IF rid IS NULL AND p_modalidade_id IS NOT NULL THEN
    INSERT INTO public.regras_classificacao_modalidade(module_id,modalidade_id,campo_origem,alvo,operador,valor,prioridade,condicoes)
      VALUES(p_module_id,p_modalidade_id,CASE p_module_id WHEN 'shopee' THEN 'logistics_channel_id' ELSE 'logistic.type' END,
        'CHAVE','IGUAL',btrim(p_chave),10,cond) RETURNING id INTO rid;
  ELSIF rid IS NOT NULL THEN
    UPDATE public.regras_classificacao_modalidade SET modalidade_id=COALESCE(p_modalidade_id,modalidade_id),
      ativo=p_modalidade_id IS NOT NULL,valor=btrim(p_chave),condicoes=cond,updated_at=now() WHERE id=rid;
  END IF;
  FOR p IN SELECT id FROM public.pedidos WHERE marketplace_module_id=p_module_id AND
    lower(btrim(metodo_envio_chave)) IN (lower(btrim(p_chave)),lower(btrim(antigo.valor)))
    AND situacao_pedido_id IN (2,3,4) AND despachado_em IS NULL AND NOT EXISTS (
      SELECT 1 FROM public.demandas_pedidos dp JOIN public.demandas_producao d ON d.id=dp.demanda_id
      WHERE dp.pedido_id=pedidos.id AND d.status NOT IN ('RASCUNHO','CANCELADO')) LOOP
    PERFORM public.classificar_pedido_modalidade(p.id); n:=n+1;
  END LOOP;
  PERFORM public.logistica_atualizar_dependentes();
  RETURN jsonb_build_object('regra_id',rid,'pedidos_reclassificados',n);
END $$;
CREATE OR REPLACE FUNCTION public.associar_canal_modalidade(p_module_id text,p_chave text,p_modalidade_id integer,p_campo_origem text DEFAULT NULL)
RETURNS TABLE(out_regra_id integer,out_pedidos_reclassificados integer) LANGUAGE sql SET search_path TO public, pg_temp AS $$
  SELECT (r->>'regra_id')::int,(r->>'pedidos_reclassificados')::int
  FROM public.logistica_associar(p_module_id,p_chave,p_modalidade_id) r;
$$;

CREATE FUNCTION public.logistica_salvar_excecao(p_regra_id bigint,p_dia date,p_dados jsonb,p_ator text DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql SET search_path TO public, pg_temp AS $$
DECLARE iid integer; j jsonb; r public.regras_logisticas_integracao; coleta timestamp; corte timestamp;
BEGIN
  PERFORM set_config('nistiprint.logistica_ator',COALESCE(p_ator,''),true);
  SELECT * INTO STRICT r FROM public.regras_logisticas_integracao WHERE id=p_regra_id FOR UPDATE;
  iid:=r.marketplace_integration_id;
  IF EXISTS (SELECT 1 FROM public.modalidades_logisticas WHERE id=r.modalidade_id AND tipo_prazo='RELATIVO') THEN
    RAISE EXCEPTION 'Prazo apos a venda nao usa agenda por data' USING ERRCODE='22023';
  END IF;
  IF p_dados IS NULL THEN
    DELETE FROM public.logistica_excecoes WHERE regra_id=p_regra_id AND dia=p_dia;
  ELSE
    IF jsonb_typeof(p_dados->'janelas') IS DISTINCT FROM 'array' OR nullif(btrim(p_dados->>'motivo'),'') IS NULL THEN
      RAISE EXCEPTION 'Informe janelas e motivo do ajuste' USING ERRCODE='22023';
    END IF;
    FOR j IN SELECT value FROM jsonb_array_elements(p_dados->'janelas') LOOP
      IF nullif(j->>'from','') IS NULL OR COALESCE((j->>'day_offset')::int,0) NOT BETWEEN 0 AND 1 THEN
        RAISE EXCEPTION 'Informe horario e dia da coleta validos' USING ERRCODE='22023';
      END IF;
      PERFORM (j->>'from')::time;
      PERFORM (nullif(j->>'to',''))::time;
      PERFORM (nullif(j->>'cutoff',''))::time;
      coleta:=p_dia+(j->>'from')::time+make_interval(days=>COALESCE((j->>'day_offset')::int,0));
      corte:=CASE r.modo_corte WHEN 'ANTES_COLETA' THEN coleta-make_interval(mins=>r.antecedencia_corte_min)
        WHEN 'MARKETPLACE' THEN p_dia+nullif(j->>'cutoff','')::time ELSE p_dia+COALESCE(nullif(j->>'cutoff','')::time,r.horario_corte) END;
      IF corte>coleta AND r.modo_corte='MARKETPLACE' THEN corte:=corte-interval '1 day'; END IF;
      IF corte IS NULL OR corte>coleta THEN RAISE EXCEPTION 'Informe corte valido anterior ou igual a coleta' USING ERRCODE='22023'; END IF;
    END LOOP;
    INSERT INTO public.logistica_excecoes(regra_id,dia,janelas,motivo) VALUES(p_regra_id,p_dia,p_dados->'janelas',p_dados->>'motivo')
      ON CONFLICT(regra_id,dia) DO UPDATE SET janelas=excluded.janelas,motivo=excluded.motivo,updated_at=now();
  END IF;
  PERFORM public.logistica_atualizar_dependentes(iid);
  RETURN jsonb_build_object('regra_id',p_regra_id,'dia',p_dia);
END $$;

CREATE FUNCTION public.logistica_agenda_periodo(p_integration_id integer,p_inicio date,p_fim date) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path TO public, pg_temp AS $$
BEGIN
  IF p_fim<p_inicio OR p_fim-p_inicio>31 THEN RAISE EXCEPTION 'Consulte no maximo 31 dias' USING ERRCODE='22023'; END IF;
  RETURN jsonb_build_object('janelas',(SELECT COALESCE(jsonb_agg(to_jsonb(x) ORDER BY x.dia,x.corte_em),'[]') FROM (
    SELECT d::date AS dia,r.modalidade_id,m.nome AS modalidade_nome,j.* FROM public.regras_logisticas_integracao r
    JOIN public.modalidades_logisticas m ON m.id=r.modalidade_id
    CROSS JOIN generate_series(p_inicio,p_fim,interval '1 day') d
    CROSS JOIN LATERAL public.logistica_janelas_efetivas(r.id,d::date) j
    WHERE r.marketplace_integration_id=p_integration_id) x),
    'sincronizacoes',(SELECT COALESCE(jsonb_agg(to_jsonb(a)-'agenda'),'[]') FROM public.logistica_agendas a WHERE integration_id=p_integration_id),
    'excecoes',(SELECT COALESCE(jsonb_agg(to_jsonb(e)),'[]') FROM public.logistica_excecoes e JOIN public.regras_logisticas_integracao r ON r.id=e.regra_id
      WHERE r.marketplace_integration_id=p_integration_id AND e.dia BETWEEN p_inicio AND p_fim),
    'divergencias',(SELECT COALESCE(jsonb_agg(jsonb_build_object('demanda_id',d.id,'demanda_codigo',d.demanda_id,'divergencia',d.logistica_divergencia)),'[]')
      FROM public.demandas_producao d WHERE d.logistica_divergencia IS NOT NULL AND EXISTS(SELECT 1 FROM public.demandas_pedidos dp JOIN public.pedidos p ON p.id=dp.pedido_id
        WHERE dp.demanda_id=d.id AND p.marketplace_integration_id=p_integration_id)));
END $$;

CREATE FUNCTION public.logistica_identificadores_observados(p_integration_id integer DEFAULT NULL) RETURNS jsonb
LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
 SELECT COALESCE(jsonb_agg(to_jsonb(x) ORDER BY x.ocorrencias DESC),'[]') FROM (
   SELECT o.module_id,o.campo_origem,o.valor_bruto AS chave,o.rotulo_bruto AS rotulo,o.ocorrencias,
     o.pedido_exemplo_id,(SELECT numero_pedido FROM public.pedidos WHERE id=o.pedido_exemplo_id) AS pedido_exemplo_numero,
     o.primeira_ocorrencia_em AS primeira_em,o.ultima_ocorrencia_em AS ultima_em,
     (SELECT count(*) FROM public.pedidos p WHERE p.marketplace_module_id=o.module_id AND lower(btrim(p.metodo_envio_chave))=o.valor_normalizado
       AND p.situacao_pedido_id IN (2,3,4) AND p.despachado_em IS NULL
       AND (p_integration_id IS NULL OR p.marketplace_integration_id=p_integration_id)) AS pedidos_pendentes,
     m.id AS modalidade_id,m.nome AS modalidade_nome,r.id AS regra_id,r.condicoes,
     COALESCE(pf.platform_fields#>'{mercadolivre,sla,service}',pf.platform_fields#>'{mercadolivre,sla,0,service}',pf.platform_fields#>'{shopee,shipping_carrier}') AS service,
     COALESCE(pf.platform_fields#>'{mercadolivre,shipment,tags}',pf.platform_fields#>'{shopee,tags}') AS tags
   FROM public.metodos_envio_observados o
   LEFT JOIN public.pedido_snapshots pf ON pf.pedido_id=o.pedido_exemplo_id
   LEFT JOIN LATERAL (SELECT rc.* FROM public.regras_classificacao_modalidade rc
     WHERE rc.module_id=o.module_id AND rc.alvo='CHAVE' AND rc.operador='IGUAL' AND rc.integration_id IS NULL
       AND lower(btrim(rc.valor))=o.valor_normalizado AND rc.ativo
       AND public.logistica_condicoes_casam(rc.condicoes,jsonb_build_object(
         'service',COALESCE(pf.platform_fields#>'{mercadolivre,sla,service}',pf.platform_fields#>'{mercadolivre,sla,0,service}',pf.platform_fields#>'{shopee,shipping_carrier}'),
         'tags',COALESCE(pf.platform_fields#>'{mercadolivre,shipment,tags}',pf.platform_fields#>'{shopee,tags}','[]')))
       ORDER BY (SELECT count(*) FROM jsonb_each(rc.condicoes)) DESC,rc.prioridade,rc.id LIMIT 1) r ON true
   LEFT JOIN public.modalidades_logisticas m ON m.id=r.modalidade_id AND m.ativo
   WHERE p_integration_id IS NULL OR o.module_id=(SELECT module_id FROM public.installed_integrations WHERE id=p_integration_id)
 ) x;
$$;
REVOKE ALL ON FUNCTION public.logistica_identificadores_observados(integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.logistica_identificadores_observados(integer) TO service_role;

CREATE FUNCTION public.logistica_reservar_sync(p_nome text,p_limite integer DEFAULT 40) RETURNS jsonb
LANGUAGE plpgsql SET search_path TO public, pg_temp AS $$
DECLARE c public.logistica_sync_cursores; ids jsonb;
BEGIN
  INSERT INTO public.logistica_sync_cursores(nome) VALUES(p_nome) ON CONFLICT DO NOTHING;
  SELECT * INTO c FROM public.logistica_sync_cursores WHERE nome=p_nome FOR UPDATE;
  IF c.bloqueado_ate>now() OR c.proxima_tentativa_em>now() THEN RETURN NULL; END IF;
  SELECT jsonb_agg(p.id ORDER BY p.id) INTO ids FROM (
    SELECT id FROM public.pedidos WHERE id>c.ultimo_id AND marketplace_module_id='mercadolivre' AND situacao_pedido_id IN (2,3,4)
      AND coleta_confirmada_observada_em IS NULL
      AND COALESCE(marketplace_lifecycle_stage,'') NOT IN ('shipped','delivered','shipping_exception','cancelled','returned')
      AND NOT COALESCE(is_fulfillment,false) ORDER BY id LIMIT greatest(1,least(p_limite,40))) p;
  IF ids IS NULL THEN
    UPDATE public.logistica_sync_cursores SET ultimo_id=0 WHERE nome=p_nome;
    SELECT jsonb_agg(p.id ORDER BY p.id) INTO ids FROM (SELECT id FROM public.pedidos WHERE marketplace_module_id='mercadolivre'
      AND coleta_confirmada_observada_em IS NULL
      AND COALESCE(marketplace_lifecycle_stage,'') NOT IN ('shipped','delivered','shipping_exception','cancelled','returned')
      AND situacao_pedido_id IN (2,3,4) AND NOT COALESCE(is_fulfillment,false) ORDER BY id LIMIT greatest(1,least(p_limite,40))) p;
  END IF;
  UPDATE public.logistica_sync_cursores SET bloqueado_ate=now()+interval '15 minutes' WHERE nome=p_nome;
  RETURN COALESCE(ids,'[]');
END $$;

CREATE FUNCTION public.logistica_reservar_agenda(p_integration_id integer) RETURNS boolean
LANGUAGE plpgsql SET search_path TO public, pg_temp AS $$
DECLARE c public.logistica_sync_cursores; chave text:='agenda:'||p_integration_id;
BEGIN
  INSERT INTO public.logistica_sync_cursores(nome) VALUES(chave) ON CONFLICT DO NOTHING;
  SELECT * INTO c FROM public.logistica_sync_cursores WHERE nome=chave FOR UPDATE;
  IF c.bloqueado_ate>now() OR c.proxima_tentativa_em>now() THEN RETURN false; END IF;
  UPDATE public.logistica_sync_cursores SET bloqueado_ate=now()+interval '5 minutes' WHERE nome=chave;
  RETURN true;
END $$;
REVOKE ALL ON FUNCTION public.logistica_reservar_agenda(integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.logistica_reservar_agenda(integer) TO service_role;

REVOKE ALL ON FUNCTION public.logistica_salvar_modalidade(integer,jsonb,text),public.logistica_salvar_regra(bigint,jsonb,text),
  public.logistica_associar(text,text,integer,jsonb,integer,text),public.associar_canal_modalidade(text,text,integer,text),
  public.logistica_salvar_excecao(bigint,date,jsonb,text),public.logistica_reservar_sync(text,integer),
  public.logistica_atualizar_dependentes(integer),public.logistica_agenda_periodo(integer,date,date) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.logistica_salvar_modalidade(integer,jsonb,text),public.logistica_salvar_regra(bigint,jsonb,text),
  public.logistica_associar(text,text,integer,jsonb,integer,text),public.associar_canal_modalidade(text,text,integer,text),
  public.logistica_salvar_excecao(bigint,date,jsonb,text),public.logistica_reservar_sync(text,integer),
  public.logistica_atualizar_dependentes(integer),public.logistica_agenda_periodo(integer,date,date) TO service_role;
-- Leituras ja expostas na torre precisam resolver o cache com as mesmas permissoes.
ALTER FUNCTION public.logistica_janelas_efetivas(bigint,date) SECURITY DEFINER;
