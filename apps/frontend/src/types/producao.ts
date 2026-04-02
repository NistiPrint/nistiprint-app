/**
 * Tipos relacionados ao Contexto de Produção
 * 
 * Este módulo define as interfaces para o contexto unificado de produção,
 * que sintetiza todas as relações entre plataformas, canais, integrações,
 * logística, pedidos e demandas.
 */

// ============================================================================
// CONTEXTOS DE PRODUÇÃO
// ============================================================================

export type ContextoProducaoTipo = 'PEDIDO_UNICO' | 'DEMANDA_CONSOLIDADA';

export type PlataformaTipo = 'MARKETPLACE' | 'ERP' | 'ECOMMERCE';

export interface ContextoPlataforma {
  nome: string;
  tipo: PlataformaTipo;
  pedido_externo_id: string;
}

export interface ContextoIntegracao {
  marketplace_integration_id?: number;
  bling_integration_id?: number;
  bling_loja_id?: number;
}

export type ModalidadeLogistica = 'STANDARD' | 'EXPRESS' | 'FULFILLMENT' | 'RETIRADA';

export type TipoEnvio = 'COLETA_LOCAL' | 'PONTO_COLETA';

export interface ContextoLogistica {
  modalidade: ModalidadeLogistica;
  tipo_envio: TipoEnvio;
  ponto_coleta_id?: number;
  ponto_coleta_nome?: string;
  horario_corte: string;  // HH:MM
  is_flex: boolean;
  is_fulfillment: boolean;
}

export type CategoriaTemporal = 'URGENTE' | 'HOJE' | 'AMANHA' | 'FUTURO';

export interface ContextoTemporal {
  data_pedido: string;  // ISO date
  data_limite_envio: string;  // ISO date
  data_promessa_cliente: string;  // ISO date
  categoria_temporal: CategoriaTemporal;
  deadline_final: string;  // HH:MM
}

export interface ContextoPriorizacao {
  score: number;
  fatores: string[];
  prioridade_manual: number;
}

export type StatusProducao = 'AGUARDANDO' | 'EM_PRODUCAO' | 'COLETA_PARCIAL' | 'CONCLUIDO';

export type StatusSincronizacao = 'PENDENTE' | 'SINCRONIZADO' | 'ERRO';

export interface ContextoStatus {
  producao: StatusProducao;
  sincronizacao: StatusSincronizacao;
}

export interface ContextoProducao {
  id: string;
  tipo: ContextoProducaoTipo;
  
  // Vínculos
  pedido_id?: number;
  demanda_id?: number;
  canal_venda_id: number;
  canal_venda_nome?: string;
  
  // Contextos
  plataforma: ContextoPlataforma;
  integracao: ContextoIntegracao;
  logistica: ContextoLogistica;
  temporal: ContextoTemporal;
  priorizacao: ContextoPriorizacao;
  status: ContextoStatus;
}

// ============================================================================
// REGRAS DE PRIORIZAÇÃO
// ============================================================================

export type AcaoPriorizacaoTipo = 'ADD_SCORE' | 'SET_PRIORIDADE' | 'MOVER_TOPO' | 'ADIAR';

export interface RegraPriorizacaoCondicoes {
  canal_venda_ids?: number[];
  plataforma_nomes?: string[];
  modalidade_logistica?: ModalidadeLogistica[];
  tipo_demanda?: string[];
  faixa_quantidade?: { min: number; max: number };
  horario_corte?: { antes: string; depois: string };
}

export interface RegraPriorizacaoAcao {
  tipo: AcaoPriorizacaoTipo;
  valor: number;
  fatores: string[];
}

export interface RegraPriorizacao {
  id: number;
  nome: string;
  descricao?: string;
  condicoes: RegraPriorizacaoCondicoes;
  acao: RegraPriorizacaoAcao;
  ativa: boolean;
  prioridade_regra: number;
  created_at?: string;
  updated_at?: string;
}

// ============================================================================
// SINALIZAÇÕES DE DEMANDA
// ============================================================================

export type SinalizacaoDemandaTipo = 
  | 'FLEX'
  | 'FULFILLMENT'
  | 'HORARIO_CORTE_PROXIMO'
  | 'PEDIDO_VINCULADO'
  | 'INTEGRACAO_ERRO'
  | 'ESTOQUE_INSUFICIENTE'
  | 'PRODUCAO_ATRASADA';

export type SinalizacaoSeveridade = 'INFO' | 'ATENCAO' | 'CRITICO';

export interface SinalizacaoDemanda {
  id: number;
  demanda_id: number;
  tipo: SinalizacaoDemandaTipo;
  severidade: SinalizacaoSeveridade;
  dados?: Record<string, any>;
  visivel: boolean;
  lido: boolean;
  created_at?: string;
}

// ============================================================================
// AUTOPREENCHIMENTO E UX
// ============================================================================

export interface DemandaFormDefaults {
  // Busca da regra logística do canal
  horario_coleta?: string;
  modalidade_logistica?: ModalidadeLogistica;
  ponto_coleta_id?: number;
  ponto_coleta_nome?: string;
  
  // Busca do canal
  canal_venda_id?: number;
  canal_venda_nome?: string;
  tipo_demanda?: string;
  
  // Busca do ponto de coleta
  horario_corte_ponto?: string;
  
  // Cálculo automático
  data_limite_execucao?: string;
  setores_envolvidos?: string[];
  
  // Preferências do usuário
  observacoes_template?: string;
}

export interface ValidationResult {
  valido: boolean;
  erros: string[];
  avisos: string[];
}

export interface UserPreference {
  vista_padrao: 'KANBAN' | 'LISTA' | 'CALENDARIO';
  ordenacao_padrao: 'PRIORIDADE' | 'HORARIO_CORTE' | 'DATA_ENTREGA' | 'DATA_CRIACAO';
  agrupamento_padrao?: 'CANAL' | 'MODALIDADE' | 'SETOR' | 'STATUS';
  auto_fill_enabled: boolean;
  show_suggestions: boolean;
  validate_on_blur: boolean;
}

export interface FilterPreset {
  id: string;
  nome: string;
  filtros: Record<string, any>;
  is_default: boolean;
}

export interface UserPreferences {
  user_id: string;
  preferences: UserPreference;
  filtros_salvos: FilterPreset[];
  atalhos_personalizados?: Record<string, string>;
  updated_at?: string;
}

// ============================================================================
// CHANNEL SNAPSHOT (Fase 4)
// ============================================================================

/**
 * Channel Snapshot
 *
 * Snapshot do estado do canal no momento da criação do pedido/demanda.
 * Usado para auditoria e garantir consistência histórica.
 *
 * Nova arquitetura (Fase 4):
 * - Pedidos e demandas capturam estado do canal via trigger
 * - is_flex e fulfillment são herdados no momento da criação
 * - horario_coleta é snapshotado para referência futura
 */
export interface ChannelSnapshot {
  flex: boolean;
  fulfillment: boolean;
  horario_coleta?: string;  // HH:MM
  color?: string;
  canal_nome?: string;
  canal_id?: number;
  overrides?: DemandaOverride[];  // Nova arquitetura: overrides
}

// ============================================================================
// OVERRIDES DE DEMANDA (Nova Arquitetura)
// ============================================================================

/**
 * Tipo de justificativa para override
 */
export type JustificativaTipo =
  | 'COLETA_ALTERNATIVA'      // Plataforma definiu horário alternativo no dia
  | 'MUDANCA_CLIENTE'         // Solicitação do cliente
  | 'ERRO_OPERACIONAL'        // Correção de erro operacional
  | 'OTIMIZACAO_LOGISTICA'    // Melhoria operacional/logística
  | 'OUTRO';                  // Outro motivo

/**
 * Contexto de origem da demanda
 */
export type ContextoOrigem =
  | 'PLANILHA'           // Gerada a partir de planilha
  | 'MULTIPLOS_PEDIDOS'  // Gerada a partir de múltiplos pedidos
  | 'DIRETA'             // Criação direta (formulário)
  | 'CONSOLIDADA';       // Demanda consolidada

/**
 * Override de campo herdado em demanda
 *
 * Nova arquitetura: permite personalizar valores herdados do canal
 * com rastreabilidade completa (quem, quando, por quê)
 */
export interface DemandaOverride {
  id: number;
  demanda_id: number;
  campo: 'horario_coleta' | 'modalidade_logistica' | 'data_limite_execucao' | 'is_flex' | 'fulfillment';
  valor_original: any;  // Valor herdado do canal
  valor_alterado: any;  // Valor personalizado
  justificativa?: string;  // Motivo da alteração (texto livre)
  justificativa_tipo?: JustificativaTipo;  // Tipo de justificativa (dropdown)
  usuario_id?: number;
  usuario_nome?: string;
  contexto_origem?: ContextoOrigem;
  created_at: string;
  updated_at?: string;
}

/**
 * Sugestões de valores para criação de demanda
 *
 * Retornado pela API /api/v2/demanda_producao/sugestoes
 */
export interface DemandaSugestoes {
  horario_coleta: string;  // HH:MM
  modalidade_logistica: string;  // STANDARD, EXPRESS, FULFILLMENT, RETIRADA
  data_limite_execucao?: string;  // YYYY-MM-DD
  is_flex: boolean;
  fulfillment: boolean;
  prazo_dias: number;
  horario_limite: string;  // HH:MM
  regra_origem: string;  // 'regras_logisticas_canal' ou 'padrao_sistema'
  alertas: string[];  // Alertas de validação
}

/**
 * Validação de override
 *
 * Retornado pela API /api/v2/demanda_producao/validar-override
 */
export interface OverrideValidacao {
  valid: boolean;
  alertas: string[];
  bloqueios: string[];
}

/**
 * Justificativa pré-definida para override
 */
export interface JustificativaTipoOption {
  value: JustificativaTipo;
  label: string;
  description: string;
}

// ============================================================================
// TIPOS AUXILIARES PARA DEMANDAS
// ============================================================================

export type TipoDemanda = 'PLATAFORMA' | 'B2B' | 'FULFILLMENT' | 'ESTOQUE_INTERNO';

export type ClassificacaoCliente = 'B2C' | 'B2B' | 'INTERNO';

export type DemandaStatus = 'AGUARDANDO' | 'EM_PRODUCAO' | 'COLETA_PARCIAL' | 'CONCLUIDO' | 'CANCELADO';

/**
 * Demanda de Produção (Nova Arquitetura - Fase 4)
 * 
 * Mudanças:
 * - channel_snapshot: snapshot do canal no momento da criação
 * - horario_coleta: deprecated (usar channel_snapshot.horario_coleta)
 */
export interface DemandaProducao {
  id: number;
  demanda_id: string;
  descricao: string;
  produto_id?: number;
  produto_nome?: string;
  quantidade: number;
  data_entrega?: string;
  prioridade: number;
  status: DemandaStatus;
  responsavel_id?: number;
  responsavel_nome?: string;

  // Vínculos
  canal_venda_id?: number;
  canal_venda_nome?: string;
  
  // DEPRECATED: usar channel_snapshot.horario_coleta
  horario_coleta?: string;

  // Tipo e classificação
  tipo_demanda: TipoDemanda;
  classificacao_cliente: ClassificacaoCliente;
  modalidade_logistica: ModalidadeLogistica;

  // Flags (herdadas do canal via trigger)
  is_flex: boolean;
  fulfillment: boolean;

  // Planejamento
  observacoes?: string;
  prioridade_manual: number;
  pedido_numero?: string;
  data_conclusao?: string;
  data_limite_execucao?: string;
  setores_envolvidos?: string[];
  categoria_temporal?: CategoriaTemporal;

  // Nova arquitetura Fase 4
  channel_snapshot?: ChannelSnapshot;

  // Metadados
  dados_adicionais?: Record<string, any>;
  created_at?: string;
  updated_at?: string;
}

export interface DemandaProducaoItem {
  id: number;
  demanda_id: number;
  produto_id?: number;
  produto_nome?: string;
  sku?: string;
  descricao: string;
  quantidade: number;
  
  // Controle de produção
  capas_impressas_qtd: number;
  capas_produzidas_qtd: number;
  capas_prontas_retirada_qtd: number;
  miolos_prontos_retirada_qtd: number;
  expedicao_capas_retiradas_qtd: number;
  expedicao_miolos_retirados_qtd: number;
  status_item: string;
  
  // Miolo
  miolo_nome?: string;
  id_produto_miolo?: number;
  produto_miolo_nome?: string;
  
  variacao?: string;
  dados_adicionais?: Record<string, any>;
  created_at?: string;
  updated_at?: string;
}

// ============================================================================
// REGRAS LOGÍSTICAS
// ============================================================================

export interface RegraLogisticaCanal {
  id: number;
  canal_venda_id: number;
  modalidade: ModalidadeLogistica;
  tipo_envio: TipoEnvio;
  horario_limite: string;  // HH:MM
  ponto_coleta_id?: number;
  ponto_coleta_nome?: string;
  prioridade_uso: number;
  created_at?: string;
  updated_at?: string;
}

// ============================================================================
// PONTOS DE COLETA
// ============================================================================

export interface PontoColeta {
  id: number;
  nome: string;
  horario_corte_padrao: string;  // HH:MM
  endereco?: string;
  ativo: boolean;
  created_at?: string;
  updated_at?: string;
}

// ============================================================================
// CANAIS DE VENDA
// ============================================================================

/**
 * Canal de Venda (Nova Arquitetura - Fase 3)
 * 
 * Mudanças:
 * - plataforma_id: agora optional (vínculo via channel_connections)
 * - conta_bling_id: deprecated (usar channel_connections.aggregator_store_id)
 * - flex, fulfillment, horario_coleta: mantidos como fonte primária
 */
export interface CanalVenda {
  id: number;
  nome: string;
  plataforma_id?: number;  // Optional na nova arquitetura
  plataforma_nome?: string;
  descricao?: string;
  configuracao?: Record<string, any>;
  ativo: boolean;
  slug?: string;
  
  // DEPRECATED: usar channel_connections.aggregator_store_id
  conta_bling_id?: string;
  
  // Fonte primária de horário de coleta
  horario_coleta?: string;
  
  // Flags de logística (herdadas via trigger para pedidos/demandas)
  flex: boolean;
  fulfillment: boolean;
  
  // UI
  color?: string;
  created_at?: string;
  updated_at?: string;
}

// ============================================================================
// PLATAFORMAS
// ============================================================================

/**
 * Plataforma (Nova Arquitetura - Fase 1)
 * 
 * Nota: Na nova arquitetura, plataformas são absorvidas por integration_modules.
 * Esta interface é mantida para backward compatibility.
 */
export interface Plataforma {
  id: number;
  nome: string;
  descricao?: string;
  tipo: PlataformaTipo;
  ativa: boolean;
  configuracao?: Record<string, any>;
  created_at?: string;
  updated_at?: string;
}

// ============================================================================
// INTEGRAÇÕES
// ============================================================================

/**
 * Integração Instalada (Nova Arquitetura - Fase 1)
 * 
 * Mudanças:
 * - platform_slug: novo campo, referência ao slug em integration_modules
 * - module_id: mantido para backward compatibility
 */
export interface InstalledIntegration {
  id: number;
  module_id: string;  // shopee, amazon, mercadolivre, shein, bling
  instance_name: string;
  user_id?: string;
  config?: Record<string, any>;
  is_active: boolean;
  last_sync?: string;
  sync_status: string;
  created_at?: string;
  updated_at?: string;
  // Novo campo Fase 1
  platform_slug?: string;
}

/**
 * Channel Connection (Nova Arquitetura - Fase 2)
 * 
 * Substitui IntegracaoCanaisConfig na nova arquitetura.
 * Vínculo explícito entre canal de venda e integração.
 */
export interface ChannelConnection {
  id: string;
  channel_id: number;  // canal_venda_id
  integration_id?: number;
  
  // Para integrações via agregador (ex: Bling)
  aggregator_store_id?: string;  // bling_loja_id
  aggregator_store_name?: string;
  
  // Dual-FK para transição (Fase 2)
  bling_integration_id?: number;
  marketplace_integration_id?: number;
  
  config?: Record<string, any>;
  is_active: boolean;
  last_sync?: string;
  sync_status?: string;
  created_at?: string;
  updated_at?: string;
}

/**
 * Integracao Canais Config (Legado - Fase 2)
 * 
 * DEPRECATED: Usar ChannelConnection na nova arquitetura.
 * Mantido para backward compatibility durante transição.
 */
export interface IntegracaoCanaisConfig {
  id: string;
  canal_venda_id: number;
  integration_id?: number;
  bling_integration_id?: number;
  marketplace_integration_id?: number;
  bling_loja_id?: number;
  plataforma_nome?: string;
  is_active: boolean;
  is_primary: boolean;
  config_json?: Record<string, any>;
  created_at?: string;
  updated_at?: string;
}

// ============================================================================
// TEMPLATES DE OBSERVAÇÕES
// ============================================================================

export interface TemplateObsCanal {
  id: number;
  canal_venda_id: number;
  nome: string;
  template: string;
  variaveis_suportadas: string[];
  is_default: boolean;
  created_at?: string;
}

// ============================================================================
// FILTROS CONTEXTUAIS - PEDIDOS
// ============================================================================

/**
 * Canal com horário de coleta próximo do horário atual.
 * Retornado pela função fn_canais_proximos_coleta().
 */
export interface CanalProximoColeta {
  id: number;
  nome: string;
  horario_coleta: string;  // HH:MM:SS ou HH:MM
  flex: boolean;
  fulfillment: boolean;
  color?: string;
  distancia_minutos: number;
  is_proximo: boolean;
  plataforma_id?: number;
  plataforma_nome?: string;
}

/**
 * Contagem de pedidos por canal para exibição nos filtros contextuais.
 */
export interface ContagemPedidosCanal {
  canal_venda_id: number;
  canal_venda_nome: string;
  total_pedidos: number;
  pedidos_sem_demanda: number;
  pedidos_com_demanda: number;
}

/**
 * Resposta da API de canais próximos de coleta.
 */
export interface CanaisProximosColetaResponse {
  canais_proximos: CanalProximoColeta[];
  horario_atual: string;  // HH:MM
  total_canais_ativos: number;
}
