-- Resumo pós-restore. Compare com um novo inventário da origem feito na janela.
SELECT 'public_tables' AS metric, count(*)::text AS value
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
UNION ALL
SELECT 'auth_users', count(*)::text FROM auth.users
UNION ALL
SELECT 'public_functions', count(*)::text
FROM information_schema.routines
WHERE routine_schema = 'public' AND routine_type = 'FUNCTION'
UNION ALL
SELECT 'public_tables_with_rls', count(*)::text
FROM pg_tables t
JOIN pg_class c ON c.relname = t.tablename
JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = t.schemaname
WHERE t.schemaname = 'public' AND c.relrowsecurity;

SELECT extname, extversion FROM pg_extension ORDER BY extname;
SELECT pubname, schemaname, tablename
FROM pg_publication_tables
WHERE pubname = 'supabase_realtime'
ORDER BY schemaname, tablename;
SELECT id, name, public, file_size_limit FROM storage.buckets ORDER BY id;
SELECT jobname, schedule, command, active FROM cron.job ORDER BY jobname;

-- Compare estes números com uma execução idêntica no Cloud imediatamente antes
-- do dump final. As estimativas de pg_stat_user_tables não servem para aceite.
SELECT 'pedido_snapshots' AS table_name, count(*) AS row_count FROM public.pedido_snapshots
UNION ALL SELECT 'pedidos_shopee', count(*) FROM public.pedidos_shopee
UNION ALL SELECT 'marketplace_order_transitions', count(*) FROM public.marketplace_order_transitions
UNION ALL SELECT 'webhook_events', count(*) FROM public.webhook_events
UNION ALL SELECT 'pedidos', count(*) FROM public.pedidos
UNION ALL SELECT 'mensagem_chat_shopee', count(*) FROM public.mensagem_chat_shopee
UNION ALL SELECT 'pedidos_bling', count(*) FROM public.pedidos_bling
UNION ALL SELECT 'pedidos_mercadolivre', count(*) FROM public.pedidos_mercadolivre
UNION ALL SELECT 'pedido_integration_refs', count(*) FROM public.pedido_integration_refs
UNION ALL SELECT 'pedido_ingest_log', count(*) FROM public.pedido_ingest_log
UNION ALL SELECT 'itens_pedido', count(*) FROM public.itens_pedido
UNION ALL SELECT 'pending_order_reconciliations', count(*) FROM public.pending_order_reconciliations
ORDER BY table_name;
