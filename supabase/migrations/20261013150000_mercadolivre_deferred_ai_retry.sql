-- Two model attempts per pack, with retries after the entire first pass.
ALTER TABLE public.mercadolivre_personalization_batches
  ADD COLUMN IF NOT EXISTS phase text NOT NULL DEFAULT 'FIRST_PASS',
  ADD COLUMN IF NOT EXISTS success_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS failed_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS retry_pending_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS running_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS retry_total integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS retry_processed integer NOT NULL DEFAULT 0;
ALTER TABLE public.mercadolivre_personalization_batches
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE public.mercadolivre_personalization_batch_items
  ADD COLUMN IF NOT EXISTS phase text NOT NULL DEFAULT 'FIRST_PASS',
  ADD COLUMN IF NOT EXISTS first_pass_done boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS retry_done boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS next_attempt_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS run_token uuid,
  ADD COLUMN IF NOT EXISTS persistence_payload jsonb,
  ADD COLUMN IF NOT EXISTS persistence_attempts integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS retry_kind text,
  ADD COLUMN IF NOT EXISTS provider text,
  ADD COLUMN IF NOT EXISTS pedido_ids bigint[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS metrics jsonb NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS attempt_started_at timestamptz;
ALTER TABLE public.mercadolivre_personalization_batch_items
  DROP CONSTRAINT IF EXISTS mercadolivre_personalization_batch_items_status_check;
ALTER TABLE public.mercadolivre_personalization_batch_items
  ADD CONSTRAINT mercadolivre_personalization_batch_items_status_check
  CHECK (status IN ('PENDING','RUNNING','RETRY_PENDING','COMPLETED','FAILED'));
CREATE INDEX IF NOT EXISTS ix_ml_ai_retry_due
  ON public.mercadolivre_personalization_batch_items(batch_id, status, next_attempt_at);

UPDATE public.mercadolivre_personalization_batch_items
   SET first_pass_done = first_pass_done OR status IN ('COMPLETED','FAILED'), attempts = least(attempts, 2);
UPDATE public.mercadolivre_personalization_batch_items i
   SET status = 'RETRY_PENDING', phase = 'RETRY', next_attempt_at = now(), retry_kind = 'MODEL'
  FROM public.mercadolivre_personalization_batches b
 WHERE i.batch_id = b.id AND b.status IN ('PENDING','RUNNING')
   AND i.status = 'FAILED' AND i.attempts < 2;
UPDATE public.mercadolivre_personalization_batches b
   SET status = CASE WHEN b.status = 'FAILED' AND c.retry_pending_count > 0 THEN 'PENDING' ELSE b.status END,
       phase = CASE WHEN b.status IN ('COMPLETED','FAILED') THEN 'DONE'
                    WHEN c.processed >= b.total AND c.retry_pending_count > 0 THEN 'RETRY'
                    ELSE 'FIRST_PASS' END,
       processed = c.processed, success_count = c.success_count, failed_count = c.failed_count,
       retry_pending_count = c.retry_pending_count, running_count = c.running_count,
       retry_total = c.retry_total
  FROM (SELECT batch_id, count(*) FILTER (WHERE first_pass_done)::integer processed,
               count(*) FILTER (WHERE status='COMPLETED')::integer success_count,
               count(*) FILTER (WHERE status='FAILED')::integer failed_count,
               count(*) FILTER (WHERE status='RETRY_PENDING')::integer retry_pending_count,
               count(*) FILTER (WHERE status='RUNNING')::integer running_count,
               count(*) FILTER (WHERE phase='RETRY')::integer retry_total
          FROM public.mercadolivre_personalization_batch_items GROUP BY batch_id) c
 WHERE c.batch_id=b.id;

CREATE OR REPLACE FUNCTION public.ml_ai_claim_batch(
 p_integration_id integer, p_batch_id uuid, p_token uuid
) RETURNS SETOF public.mercadolivre_personalization_batches
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE b public.mercadolivre_personalization_batches;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('ml-ai:'||p_integration_id::text,0));
 SELECT * INTO b FROM public.mercadolivre_personalization_batches
  WHERE id=p_batch_id AND marketplace_integration_id=p_integration_id FOR UPDATE;
 IF NOT FOUND OR b.status='COMPLETED' OR (b.status='FAILED' AND b.phase='DONE') THEN RETURN; END IF;
 IF b.available_at>now() OR (b.status='RUNNING' AND b.lease_until>now()) THEN RETURN; END IF;
 IF EXISTS (SELECT 1 FROM public.mercadolivre_personalization_batches
             WHERE marketplace_integration_id=p_integration_id AND id<>p_batch_id AND status='RUNNING') THEN RETURN; END IF;
 -- Upgrade interrupted executions from the previous worker without replaying
 -- results that its atomic persistence RPC already committed.
 UPDATE public.mercadolivre_personalization_batch_items i
    SET status='COMPLETED',first_pass_done=true,retry_done=(i.phase='RETRY'),
        run_token=NULL,persistence_payload=NULL,finished_at=coalesce(i.finished_at,now())
  WHERE i.batch_id=p_batch_id AND i.status<>'COMPLETED' AND EXISTS (
    SELECT 1 FROM public.mercadolivre_personalization_logs l
     WHERE l.batch_id=p_batch_id AND l.pack_id=i.pack_id
       AND l.status IN ('success','needs_review','no_personalization_found'));
 -- An interrupted request consumed its model attempt. Only a saved result may
 -- resume persistence without consuming a second model attempt.
 UPDATE public.mercadolivre_personalization_batch_items
    SET status=CASE WHEN persistence_payload IS NOT NULL THEN
                          CASE WHEN phase='FIRST_PASS' THEN 'PENDING' ELSE 'RETRY_PENDING' END
                    WHEN attempts>=2 THEN 'FAILED' ELSE 'RETRY_PENDING' END,
        phase=CASE WHEN persistence_payload IS NULL THEN 'RETRY' ELSE phase END,
        first_pass_done=first_pass_done OR persistence_payload IS NULL,
        retry_done=retry_done OR (persistence_payload IS NULL AND attempts>=2),
        retry_kind=CASE WHEN persistence_payload IS NOT NULL THEN 'PERSISTENCE' ELSE 'MODEL' END,
        next_attempt_at=now(), run_token=NULL,
        error_message=coalesce(error_message,'Execução interrompida; tentativa recuperada.'), updated_at=now()
  WHERE batch_id=p_batch_id AND status='RUNNING';
 UPDATE public.mercadolivre_personalization_batch_items
    SET status='FAILED', first_pass_done=true, retry_done=(phase='RETRY'), run_token=NULL,
        error_message=coalesce(error_message,'Limite de tentativas atingido.'), finished_at=now()
  WHERE batch_id=p_batch_id AND status IN ('PENDING','RETRY_PENDING')
    AND ((persistence_payload IS NULL AND attempts>=2)
      OR (persistence_payload IS NOT NULL AND persistence_attempts>=2));
 UPDATE public.mercadolivre_personalization_batches
    SET processed=(SELECT count(*) FROM public.mercadolivre_personalization_batch_items WHERE batch_id=p_batch_id AND first_pass_done),
        success_count=(SELECT count(*) FROM public.mercadolivre_personalization_batch_items WHERE batch_id=p_batch_id AND status='COMPLETED'),
        failed_count=(SELECT count(*) FROM public.mercadolivre_personalization_batch_items WHERE batch_id=p_batch_id AND status='FAILED'),
        retry_pending_count=(SELECT count(*) FROM public.mercadolivre_personalization_batch_items WHERE batch_id=p_batch_id AND status='RETRY_PENDING'),
        running_count=0,
        retry_total=(SELECT count(*) FROM public.mercadolivre_personalization_batch_items WHERE batch_id=p_batch_id AND phase='RETRY'),
        retry_processed=(SELECT count(*) FROM public.mercadolivre_personalization_batch_items WHERE batch_id=p_batch_id AND retry_done),
        status='RUNNING', run_token=p_token, lease_until=now()+interval '5 minutes', updated_at=now(),
        attempts=attempts+1, started_at=coalesce(started_at,now()), finished_at=NULL
  WHERE id=p_batch_id RETURNING * INTO b;
 RETURN NEXT b;
END $$;

CREATE OR REPLACE FUNCTION public.ml_ai_claim_item(p_batch_id uuid,p_pack_id text,p_token uuid)
RETURNS SETOF public.mercadolivre_personalization_batch_items
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE b public.mercadolivre_personalization_batches; i public.mercadolivre_personalization_batch_items;
BEGIN
 SELECT * INTO b FROM public.mercadolivre_personalization_batches
  WHERE id=p_batch_id AND status='RUNNING' AND run_token=p_token AND lease_until>now() FOR UPDATE;
 IF NOT FOUND THEN RETURN; END IF;
 SELECT * INTO i FROM public.mercadolivre_personalization_batch_items
  WHERE batch_id=p_batch_id AND pack_id=p_pack_id FOR UPDATE;
 IF NOT FOUND OR i.phase<>b.phase OR i.status NOT IN ('PENDING','RETRY_PENDING') OR i.next_attempt_at>now() THEN RETURN; END IF;
 IF (i.persistence_payload IS NULL AND i.attempts>=2)
    OR (i.persistence_payload IS NOT NULL AND i.persistence_attempts>=2) THEN RETURN; END IF;
 UPDATE public.mercadolivre_personalization_batch_items
    SET status='RUNNING',run_token=p_token,started_at=coalesce(started_at,now()),
        attempt_started_at=now(),finished_at=NULL,updated_at=now(),
        attempts=attempts+CASE WHEN persistence_payload IS NULL THEN 1 ELSE 0 END,
        persistence_attempts=persistence_attempts+CASE WHEN persistence_payload IS NOT NULL THEN 1 ELSE 0 END
  WHERE id=i.id RETURNING * INTO i;
 UPDATE public.mercadolivre_personalization_batches
    SET running_count=running_count+1, updated_at=now(),
        retry_pending_count=greatest(0,retry_pending_count-CASE WHEN i.phase='RETRY' THEN 1 ELSE 0 END)
  WHERE id=p_batch_id;
 RETURN NEXT i;
END $$;

CREATE OR REPLACE FUNCTION public.ml_ai_finish_item(
 p_batch_id uuid,p_pack_id text,p_token uuid,p_status text,
 p_error text DEFAULT NULL,p_next_at timestamptz DEFAULT NULL,
 p_metrics jsonb DEFAULT '{}',p_payload jsonb DEFAULT NULL,p_retry_kind text DEFAULT NULL
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE b public.mercadolivre_personalization_batches; i public.mercadolivre_personalization_batch_items;
BEGIN
 IF p_status NOT IN ('COMPLETED','FAILED','RETRY_PENDING') THEN RAISE EXCEPTION 'Invalid pack outcome'; END IF;
 SELECT * INTO b FROM public.mercadolivre_personalization_batches
  WHERE id=p_batch_id AND status='RUNNING' AND run_token=p_token AND lease_until>now() FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT * INTO i FROM public.mercadolivre_personalization_batch_items
  WHERE batch_id=p_batch_id AND pack_id=p_pack_id AND status='RUNNING' AND run_token=p_token FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 IF p_status IN ('FAILED','RETRY_PENDING') AND p_error IS NOT NULL THEN
   INSERT INTO public.mercadolivre_personalization_logs
     (marketplace_integration_id,batch_id,pack_id,status,error_message,metadata)
   VALUES (b.marketplace_integration_id,p_batch_id,p_pack_id,'error',p_error,
           coalesce(p_metrics,'{}')||jsonb_build_object('phase',i.phase,'attempt',i.attempts));
   UPDATE public.mercadolivre_chat_conversations
      SET ai_status='error',last_error=p_error,needs_review=true,updated_at=now()
    WHERE marketplace_integration_id=b.marketplace_integration_id AND pack_id=p_pack_id;
 END IF;
 UPDATE public.mercadolivre_personalization_batch_items
    SET status=p_status,error_message=p_error,first_pass_done=true,
        retry_done=retry_done OR (phase='RETRY' AND p_status<>'RETRY_PENDING'),
        phase=CASE WHEN p_status='RETRY_PENDING' THEN 'RETRY' ELSE phase END,
        next_attempt_at=coalesce(p_next_at,now()),finished_at=CASE WHEN p_status='RETRY_PENDING' THEN NULL ELSE now() END,
        run_token=NULL,updated_at=now(),provider=coalesce(p_metrics->>'provider',provider),
        pedido_ids=CASE WHEN jsonb_typeof(p_metrics->'pedido_ids')='array'
                       THEN ARRAY(SELECT jsonb_array_elements_text(p_metrics->'pedido_ids')::bigint) ELSE pedido_ids END,
        metrics=metrics||coalesce(p_metrics,'{}'),retry_kind=coalesce(p_retry_kind,retry_kind),
        persistence_payload=CASE WHEN p_status='RETRY_PENDING' THEN coalesce(p_payload,persistence_payload) ELSE NULL END,
        persistence_attempts=CASE WHEN p_payload IS NOT NULL THEN greatest(persistence_attempts,1) ELSE persistence_attempts END
  WHERE id=i.id;
 UPDATE public.mercadolivre_personalization_batches
    SET processed=processed+CASE WHEN i.first_pass_done THEN 0 ELSE 1 END, updated_at=now(),
        success_count=success_count+CASE WHEN p_status='COMPLETED' THEN 1 ELSE 0 END,
        failed_count=failed_count+CASE WHEN p_status='FAILED' THEN 1 ELSE 0 END,
        retry_pending_count=retry_pending_count+CASE WHEN p_status='RETRY_PENDING' THEN 1 ELSE 0 END,
        running_count=greatest(0,running_count-1),
        retry_total=retry_total+CASE WHEN p_status='RETRY_PENDING' AND i.phase='FIRST_PASS' THEN 1 ELSE 0 END,
        retry_processed=retry_processed+CASE WHEN i.phase='RETRY' AND NOT i.retry_done AND p_status<>'RETRY_PENDING' THEN 1 ELSE 0 END
  WHERE id=p_batch_id;
 RETURN true;
END $$;

CREATE OR REPLACE FUNCTION public.ml_ai_checkpoint_result(
 p_batch_id uuid,p_pack_id text,p_token uuid,p_payload jsonb,p_metrics jsonb
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE b public.mercadolivre_personalization_batches;
BEGIN
 SELECT * INTO b FROM public.mercadolivre_personalization_batches
  WHERE id=p_batch_id AND status='RUNNING' AND run_token=p_token AND lease_until>now() FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'AI batch lease lost'; END IF;
 IF (p_payload->>'p_integration_id')::integer IS DISTINCT FROM b.marketplace_integration_id
    OR (p_payload->>'p_pack_id') IS DISTINCT FROM p_pack_id
    OR (p_payload->>'p_batch_id')::uuid IS DISTINCT FROM p_batch_id THEN
   RAISE EXCEPTION 'Snapshot does not belong to batch';
 END IF;
 UPDATE public.mercadolivre_personalization_batch_items
    SET persistence_payload=p_payload,persistence_attempts=greatest(persistence_attempts,1),
        metrics=metrics||p_metrics,provider=p_metrics->>'provider',
        pedido_ids=ARRAY(SELECT jsonb_array_elements_text(p_payload->'p_log'->'pedido_ids')::bigint),updated_at=now()
  WHERE batch_id=p_batch_id AND pack_id=p_pack_id AND status='RUNNING' AND run_token=p_token;
 IF NOT FOUND THEN RAISE EXCEPTION 'Pack attempt lease lost'; END IF;
 RETURN true;
END $$;

CREATE OR REPLACE FUNCTION public.ml_ai_persist_result(
 p_batch_id uuid,p_pack_id text,p_token uuid,p_metrics jsonb DEFAULT '{}'
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE b public.mercadolivre_personalization_batches; i public.mercadolivre_personalization_batch_items;
        payload jsonb; result jsonb; started timestamptz:=clock_timestamp();
BEGIN
 SELECT * INTO b FROM public.mercadolivre_personalization_batches
  WHERE id=p_batch_id AND status='RUNNING' AND run_token=p_token AND lease_until>now() FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'AI batch lease lost'; END IF;
 SELECT * INTO i FROM public.mercadolivre_personalization_batch_items
  WHERE batch_id=p_batch_id AND pack_id=p_pack_id AND status='RUNNING' AND run_token=p_token FOR UPDATE;
 IF NOT FOUND OR i.persistence_payload IS NULL THEN RAISE EXCEPTION 'Saved pack response unavailable'; END IF;
 payload:=i.persistence_payload;
 result:=public.persist_mercadolivre_personalization_results(
   b.marketplace_integration_id,p_pack_id,payload->>'p_context_hash',payload->>'p_status',
   (payload->>'p_needs_review')::boolean,payload->'p_records',payload->'p_log',p_batch_id);
 IF (result->>'saved')::integer IS DISTINCT FROM jsonb_array_length(payload->'p_records')
    OR (result->>'status') IS DISTINCT FROM (payload->>'p_status') THEN RAISE EXCEPTION 'Incomplete AI persistence'; END IF;
 IF NOT public.ml_ai_finish_item(p_batch_id,p_pack_id,p_token,'COMPLETED',NULL,NULL,
   i.metrics||p_metrics||jsonb_build_object('persistence_ms',
      round(extract(epoch FROM clock_timestamp()-started)*1000)::integer,
      'duration_ms',coalesce((p_metrics->>'duration_ms')::integer,(i.metrics->>'duration_ms')::integer,0)+
          round(extract(epoch FROM clock_timestamp()-started)*1000)::integer)) THEN
   RAISE EXCEPTION 'Pack completion lease lost';
 END IF;
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION public.ml_ai_release_batch(p_batch_id uuid,p_token uuid)
RETURNS SETOF public.mercadolivre_personalization_batches
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE b public.mercadolivre_personalization_batches; next_at timestamptz; next_phase text;
BEGIN
 SELECT * INTO b FROM public.mercadolivre_personalization_batches
  WHERE id=p_batch_id AND status='RUNNING' AND run_token=p_token FOR UPDATE;
 IF NOT FOUND THEN RETURN; END IF;
 IF EXISTS (SELECT 1 FROM public.mercadolivre_personalization_batch_items WHERE batch_id=p_batch_id AND status='RUNNING') THEN
   UPDATE public.mercadolivre_personalization_batches SET lease_until=now(),available_at=now()+interval '30 seconds',updated_at=now()
    WHERE id=p_batch_id RETURNING * INTO b;
   RETURN NEXT b; RETURN;
 END IF;
 SELECT min(next_attempt_at) INTO next_at FROM public.mercadolivre_personalization_batch_items
  WHERE batch_id=p_batch_id AND status='PENDING' AND phase='FIRST_PASS';
 IF next_at IS NOT NULL THEN next_phase:='FIRST_PASS';
 ELSE
   SELECT min(next_attempt_at) INTO next_at FROM public.mercadolivre_personalization_batch_items
    WHERE batch_id=p_batch_id AND status='RETRY_PENDING';
   next_phase:='RETRY';
 END IF;
 UPDATE public.mercadolivre_personalization_batches
    SET status=CASE WHEN next_at IS NULL THEN 'COMPLETED' ELSE 'PENDING' END, updated_at=now(),
        phase=CASE WHEN next_at IS NULL THEN 'DONE' ELSE next_phase END,
        available_at=coalesce(next_at,now()),lease_until=NULL,run_token=NULL,
        finished_at=CASE WHEN next_at IS NULL THEN now() ELSE NULL END,
        error_message=CASE WHEN failed_count>0 THEN failed_count::text||' pacote(s) com falha definitiva.' ELSE NULL END
  WHERE id=p_batch_id RETURNING * INTO b;
 RETURN NEXT b;
END $$;

DO $$ DECLARE f regprocedure; BEGIN
 FOR f IN SELECT p.oid::regprocedure FROM pg_proc p JOIN pg_namespace n ON p.pronamespace=n.oid
           WHERE n.nspname='public' AND p.proname IN ('ml_ai_claim_batch','ml_ai_claim_item',
             'ml_ai_finish_item','ml_ai_checkpoint_result','ml_ai_persist_result','ml_ai_release_batch') LOOP
   EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC, anon, authenticated',f);
   EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role',f);
 END LOOP;
END $$;
