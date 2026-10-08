import React, { createContext, useContext, useMemo } from 'react';
import { useAuth } from './AuthContext';

const PermissionsContext = createContext();

export const PermissionsProvider = ({ children }) => {
  const { user } = useAuth();
  const permissions = useMemo(() => ({
    fields: user?.permissoes_demanda?.fields || [],
    actions: user?.permissoes_demanda?.actions || [],
  }), [user?.permissoes_demanda]);

  const canEditField = (_sectorId, fieldName) => Boolean(
    user && fieldName && (user.is_admin || permissions.fields.includes(fieldName)),
  );
  const canExecuteAction = (_sectorId, actionName) => Boolean(
    user && actionName && (user.is_admin || permissions.actions.includes(actionName)),
  );

  const getVisibleColumns = (userSetor) => {
    const columns = ['produto_miolo', 'total'];
    const mapping = {
      capas_impressas: 'capas_impressas_qtd',
      capas_produzidas: 'capas_produzidas_qtd',
      capas_prontas: 'capas_prontas_retirada_qtd',
      miolos_prontos: 'miolos_prontos_retirada_qtd',
      expedicao_capas: 'expedicao_capas_retiradas_qtd',
      expedicao_miolos: 'expedicao_miolos_retirados_qtd',
    };
    Object.entries(mapping).forEach(([column, field]) => {
      if (canEditField(userSetor, field)) columns.push(column);
    });
    return [...columns, 'acoes'];
  };

  return (
    <PermissionsContext.Provider value={{
      permissions,
      loading: false,
      canEditField,
      canExecuteAction,
      getVisibleColumns,
      updatePermissions: async () => false,
      refreshPermissions: async () => false,
    }}>
      {children}
    </PermissionsContext.Provider>
  );
};

export const usePermissions = () => {
  const context = useContext(PermissionsContext);
  if (!context) throw new Error('usePermissions must be used within a PermissionsProvider');
  return context;
};
