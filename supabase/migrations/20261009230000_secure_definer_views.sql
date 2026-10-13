-- These views are consumed by trusted backend code. Make their privilege
-- behavior explicit and prevent direct Data API access by client roles.
-- service_role has SELECT on every direct dependency (verified against the
-- active Supabase catalog before applying this migration).

ALTER VIEW public.pedidos_com_external_id SET (security_invoker = true);
ALTER VIEW public.plataformas_compat SET (security_invoker = true);
ALTER VIEW public.v_auditoria_bom_componentes_invalidos SET (security_invoker = true);
ALTER VIEW public.v_auditoria_variacoes_tipo_divergente SET (security_invoker = true);
ALTER VIEW public.v_candidatos_verificacao_estoque SET (security_invoker = true);
ALTER VIEW public.v_itens_demanda_mapeamento SET (security_invoker = true);
ALTER VIEW public.v_pedido_demanda_rastreamento SET (security_invoker = true);
ALTER VIEW public.view_alocacoes_por_item SET (security_invoker = true);
ALTER VIEW public.view_auditoria_tipo_produto SET (security_invoker = true);
ALTER VIEW public.view_consolidado_previsao_materiais SET (security_invoker = true);
ALTER VIEW public.view_consolidado_producao SET (security_invoker = true);
ALTER VIEW public.view_ledger_completo SET (security_invoker = true);
ALTER VIEW public.view_mensagens_chat SET (security_invoker = true);
ALTER VIEW public.view_movimentacoes_consolidadas SET (security_invoker = true);
ALTER VIEW public.view_pedidos_para_consolidar SET (security_invoker = true);
ALTER VIEW public.view_vendas_personalizadas SET (security_invoker = true);
ALTER VIEW public.vw_despacho_carimbo_inconsistente SET (security_invoker = true);

REVOKE ALL ON TABLE
  public.pedidos_com_external_id,
  public.plataformas_compat,
  public.v_auditoria_bom_componentes_invalidos,
  public.v_auditoria_variacoes_tipo_divergente,
  public.v_candidatos_verificacao_estoque,
  public.v_itens_demanda_mapeamento,
  public.v_pedido_demanda_rastreamento,
  public.view_alocacoes_por_item,
  public.view_auditoria_tipo_produto,
  public.view_consolidado_previsao_materiais,
  public.view_consolidado_producao,
  public.view_ledger_completo,
  public.view_mensagens_chat,
  public.view_movimentacoes_consolidadas,
  public.view_pedidos_para_consolidar,
  public.view_vendas_personalizadas,
  public.vw_despacho_carimbo_inconsistente
FROM PUBLIC, anon, authenticated;

GRANT SELECT ON TABLE
  public.pedidos_com_external_id,
  public.plataformas_compat,
  public.v_auditoria_bom_componentes_invalidos,
  public.v_auditoria_variacoes_tipo_divergente,
  public.v_candidatos_verificacao_estoque,
  public.v_itens_demanda_mapeamento,
  public.v_pedido_demanda_rastreamento,
  public.view_alocacoes_por_item,
  public.view_auditoria_tipo_produto,
  public.view_consolidado_previsao_materiais,
  public.view_consolidado_producao,
  public.view_ledger_completo,
  public.view_mensagens_chat,
  public.view_movimentacoes_consolidadas,
  public.view_pedidos_para_consolidar,
  public.view_vendas_personalizadas,
  public.vw_despacho_carimbo_inconsistente
TO service_role;
