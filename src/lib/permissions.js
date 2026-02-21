/**
 * Configuração de permissões por setor para o dashboard de demandas
 * Define quais campos e ações cada setor pode acessar
 */

export const PERMISSIONS = {
  // Campos que cada setor pode editar
  fields: {
    'cpd': [
      'capas_impressas_qtd',
      'capas_produzidas_qtd',
      'capas_prontas_retirada_qtd'
    ],
    'controle de produção': [
      'capas_impressas_qtd',
      'capas_produzidas_qtd',
      'capas_prontas_retirada_qtd'
    ],
    'capas': [
      'capas_produzidas_qtd'
    ],
    'miolos': [
      'miolos_prontos_retirada_qtd'
    ],
    'expedição': [
      'expedicao_capas_retiradas_qtd',
      'expedicao_miolos_retirados_qtd'
    ],
    'administrador': [
      'capas_impressas_qtd',
      'capas_produzidas_qtd',
      'capas_prontas_retirada_qtd',
      'miolos_prontos_retirada_qtd',
      'expedicao_capas_retiradas_qtd',
      'expedicao_miolos_retirados_qtd'
    ],
    'administrativo': [
      'capas_impressas_qtd',
      'capas_produzidas_qtd',
      'capas_prontas_retirada_qtd',
      'miolos_prontos_retirada_qtd',
      'expedicao_capas_retiradas_qtd',
      'expedicao_miolos_retirados_qtd'
    ]
  },

  // Ações que cada setor pode executar
  actions: {
    'cpd': [
      'delete_demand'
    ],
    'controle de produção': [
      'delete_demand',
      'revert_finalize_item'
    ],
    'capas': [],
    'miolos': [],
    'expedição': [
      'finalize_item',
      'collect_demand'
    ],
    'administrador': [
      'finalize_item',
      'collect_demand',
      'delete_demand',
      'revert_finalize_item'
    ],
    'administrativo': [
      'finalize_item',
      'collect_demand',
      'delete_demand',
      'revert_finalize_item'
    ],
    'controle de produção': [
      'delete_demand',
      'revert_finalize_item'
    ]
  },

  // Grupos de campos para organização visual
  fieldGroups: {
    'cpd': {
      title: 'Impressão e Preparação',
      description: 'Campos relacionados à impressão e preparação das capas',
      fields: ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd']
    },
    'controle de produção': {
      title: 'Impressão e Preparação',
      description: 'Campos relacionados à impressão e preparação das capas',
      fields: ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd']
    },
    'capas': {
      title: 'Produção de Capas',
      description: 'Campos relacionados à produção das capas',
      fields: ['capas_produzidas_qtd']
    },
    'miolos': {
      title: 'Produção de Miolos',
      description: 'Campo relacionado aos miolos prontos para retirada',
      fields: ['miolos_prontos_retirada_qtd']
    },
    'expedição': {
      title: 'Expedição',
      description: 'Campos relacionados à retirada e expedição final',
      fields: ['expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd']
    }
  }
};

/**
 * Verifica se um usuário tem permissão para editar um campo específico
 * @param {string} userSetor - Setor do usuário
 * @param {string} fieldName - Nome do campo
 * @returns {boolean}
 */
export const canEditField = (userSetor, fieldName) => {
  if (!userSetor || !fieldName) return false;

  // Normalizar o nome do setor para comparação
  const normalizedSetor = userSetor.trim().toLowerCase();

  // Procurar primeiro pela chave exata
  let setorPermissions = PERMISSIONS.fields[normalizedSetor] || [];

  // Se não encontrar, tentar encontrar por variação de capitalização
  if (!setorPermissions.length) {
    const matchingKey = Object.keys(PERMISSIONS.fields).find(
      key => key.toLowerCase() === normalizedSetor
    );
    if (matchingKey) {
      setorPermissions = PERMISSIONS.fields[matchingKey];
    }
  }

  return setorPermissions.includes(fieldName);
};

/**
 * Verifica se um usuário tem permissão para executar uma ação específica
 * @param {string} userSetor - Setor do usuário
 * @param {string} actionName - Nome da ação
 * @returns {boolean}
 */
export const canExecuteAction = (userSetor, actionName) => {
  if (!userSetor || !actionName) return false;

  // Normalizar o nome do setor para comparação
  const normalizedSetor = userSetor.trim().toLowerCase();

  // Procurar primeiro pela chave exata
  let setorActions = PERMISSIONS.actions[normalizedSetor] || [];

  // Se não encontrar, tentar encontrar por variação de capitalização
  if (!setorActions.length) {
    const matchingKey = Object.keys(PERMISSIONS.actions).find(
      key => key.toLowerCase() === normalizedSetor
    );
    if (matchingKey) {
      setorActions = PERMISSIONS.actions[matchingKey];
    }
  }

  return setorActions.includes(actionName);
};

/**
 * Retorna todos os campos que um setor pode editar
 * @param {string} userSetor - Setor do usuário
 * @returns {string[]}
 */
export const getEditableFields = (userSetor) => {
  if (!userSetor) return [];

  return PERMISSIONS.fields[userSetor] || [];
};

/**
 * Retorna os grupos de campos visíveis para um setor
 * @param {string} userSetor - Setor do usuário
 * @returns {object}
 */
export const getVisibleFieldGroups = (userSetor) => {
  if (!userSetor) return {};

  // Normalizar o nome do setor para comparação
  const normalizedSetor = userSetor.trim().toLowerCase();
  const isAdmin = normalizedSetor === 'administrador' || normalizedSetor === 'administrativo';

  const visibleGroups = {};

  Object.entries(PERMISSIONS.fieldGroups).forEach(([setor, group]) => {
    const normalizedGroupSetor = setor.toLowerCase();
    if (normalizedGroupSetor === normalizedSetor || isAdmin) {
      visibleGroups[setor] = group;
    }
  });

  return visibleGroups;
};

/**
 * Verifica se um setor pode ver um grupo específico de campos
 * @param {string} userSetor - Setor do usuário
 * @param {string} groupSetor - Setor do grupo
 * @returns {boolean}
 */
export const canSeeFieldGroup = (userSetor, groupSetor) => {
  if (!userSetor || !groupSetor) return false;

  // Normalizar os nomes dos setores para comparação
  const normalizedUserSetor = userSetor.trim().toLowerCase();
  const normalizedGroupSetor = groupSetor.trim().toLowerCase();

  const isAdmin = normalizedUserSetor === 'administrador' || normalizedUserSetor === 'administrativo';

  return normalizedUserSetor === normalizedGroupSetor || isAdmin;
};

/**
 * Mapeamento de colunas da tabela para campos de permissões
 */
const COLUMN_FIELD_MAPPING = {
  'capas_impressas': 'capas_impressas_qtd',
  'capas_produzidas': 'capas_produzidas_qtd',
  'capas_prontas': 'capas_prontas_retirada_qtd',
  'miolos_prontos': 'miolos_prontos_retirada_qtd',
  'expedicao_capas': 'expedicao_capas_retiradas_qtd',
  'expedicao_miolos': 'expedicao_miolos_retirados_qtd'
};

/**
 * Retorna as colunas visíveis para um setor na tabela de demandas
 * Colunas sempre visíveis: produto_miolo, total, acoes
 * Outras colunas são visíveis se o setor pode editar o campo correspondente
 * @param {string} userSetor - Setor do usuário
 * @returns {string[]} Lista de nomes de colunas visíveis
 */
export const getVisibleColumns = (userSetor) => {
  if (!userSetor) return ['produto_miolo', 'total', 'acoes'];

  const visibleColumns = ['produto_miolo', 'total'];

  // Adiciona colunas baseadas nas permissões de edição
  Object.entries(COLUMN_FIELD_MAPPING).forEach(([columnName, fieldName]) => {
    if (canEditField(userSetor, fieldName)) {
      visibleColumns.push(columnName);
    }
  });

  visibleColumns.push('acoes');

  return visibleColumns;
};

/**
 * Verifica se uma coluna específica é visível para um setor
 * @param {string} userSetor - Setor do usuário
 * @param {string} columnName - Nome da coluna
 * @returns {boolean}
 */
export const canSeeColumn = (userSetor, columnName) => {
  if (!userSetor || !columnName) return false;

  const visibleColumns = getVisibleColumns(userSetor);
  return visibleColumns.includes(columnName);
};
