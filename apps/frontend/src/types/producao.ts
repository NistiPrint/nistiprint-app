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
// TIPOS AUXILIARES PARA DEMANDAS
// ============================================================================

export type TipoDemanda = 'PLATAFORMA' | 'B2B' | 'FULFILLMENT' | 'ESTOQUE_INTERNO';

export type ClassificacaoCliente = 'B2C' | 'B2B' | 'INTERNO';

export type DemandaStatus = 'AGUARDANDO' | 'EM_PRODUCAO' | 'COLETA_PARCIAL' | 'CONCLUIDO' | 'CANCELADO';

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
  horario_coleta?: string;
  
  // Tipo e classificação
  tipo_demanda: TipoDemanda;
  classificacao_cliente: ClassificacaoCliente;
  modalidade_logistica: ModalidadeLogistica;
  
  // Flags
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

export interface CanalVenda {
  id: number;
  nome: string;
  plataforma_id?: number;
  plataforma_nome?: string;
  descricao?: string;
  configuracao?: Record<string, any>;
  ativo: boolean;
  slug?: string;
  conta_bling_id?: string;
  horario_coleta?: string;
  flex: boolean;
  fulfillment: boolean;
  color?: string;
  created_at?: string;
  updated_at?: string;
}

// ============================================================================
// PLATAFORMAS
// ============================================================================

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
}

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
