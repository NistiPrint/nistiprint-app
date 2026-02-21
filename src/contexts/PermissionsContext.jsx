import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { PERMISSIONS as DEFAULT_PERMISSIONS } from '@/lib/permissions';
import { useAuth } from './AuthContext';

const PermissionsContext = createContext();

export const PermissionsProvider = ({ children }) => {
  const { user } = useAuth();
  const [permissions, setPermissions] = useState(DEFAULT_PERMISSIONS);
  const [loading, setLoading] = useState(true);

  const fetchPermissions = useCallback(async () => {
    try {
      const response = await fetch('/api/v2/configuracoes/demanda-permissions');
      if (response.ok) {
        const data = await response.json();
        if (data.success && data.config) {
            // Merge with defaults to ensure structure exists if partial config
            setPermissions(prev => {
                const newConfig = { ...prev };
                
                // Only override if the dynamic config actually has data
                if (data.config.fields && Object.keys(data.config.fields).length > 0) {
                    newConfig.fields = { ...prev.fields, ...data.config.fields };
                }
                
                if (data.config.actions && Object.keys(data.config.actions).length > 0) {
                    newConfig.actions = { ...prev.actions, ...data.config.actions };
                }
                
                // Add any other top-level keys from dynamic config
                Object.keys(data.config).forEach(key => {
                    if (key !== 'fields' && key !== 'actions') {
                        newConfig[key] = data.config[key];
                    }
                });
                
                return newConfig;
            });
        }
      }
    } catch (error) {
      console.error('Failed to fetch permissions:', error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPermissions();
  }, [fetchPermissions]);

  const canEditField = useCallback((userSetor, fieldName) => {
    if (!userSetor || !fieldName) return false;

    // Normalizar o nome do setor para comparação
    const normalizedSetor = userSetor.trim().toLowerCase();

    // Procurar primeiro pela chave exata
    let setorPermissions = permissions.fields[normalizedSetor] || [];

    // Se não encontrar, tentar encontrar por variação de capitalização
    if (!setorPermissions.length) {
      const matchingKey = Object.keys(permissions.fields).find(
        key => key.toLowerCase() === normalizedSetor
      );
      if (matchingKey) {
        setorPermissions = permissions.fields[matchingKey];
      }
    }

    return setorPermissions.includes(fieldName);
  }, [permissions]);

  const canExecuteAction = useCallback((userSetor, actionName) => {
    if (!userSetor || !actionName) return false;

    // Normalizar o nome do setor para comparação
    const normalizedSetor = userSetor.trim().toLowerCase();

    // Procurar primeiro pela chave exata
    let setorActions = permissions.actions[normalizedSetor] || [];

    // Se não encontrar, tentar encontrar por variação de capitalização
    if (!setorActions.length) {
      const matchingKey = Object.keys(permissions.actions).find(
        key => key.toLowerCase() === normalizedSetor
      );
      if (matchingKey) {
        setorActions = permissions.actions[matchingKey];
      }
    }

    return setorActions.includes(actionName);
  }, [permissions]);

  // Logic for visible columns (replicated/adapted from lib/permissions.js)
  const getVisibleColumns = useCallback((userSetor) => {
    if (!userSetor) return ['produto_miolo', 'total', 'acoes'];

    const visibleColumns = ['produto_miolo', 'total'];
    const COLUMN_FIELD_MAPPING = {
      'capas_impressas': 'capas_impressas_qtd',
      'capas_produzidas': 'capas_produzidas_qtd',
      'capas_prontas': 'capas_prontas_retirada_qtd',
      'miolos_prontos': 'miolos_prontos_retirada_qtd',
      'expedicao_capas': 'expedicao_capas_retiradas_qtd',
      'expedicao_miolos': 'expedicao_miolos_retirados_qtd'
    };

    Object.entries(COLUMN_FIELD_MAPPING).forEach(([columnName, fieldName]) => {
      if (canEditField(userSetor, fieldName)) {
        visibleColumns.push(columnName);
      }
    });

    visibleColumns.push('acoes');
    return visibleColumns;
  }, [canEditField]);

  const updatePermissions = async (newPermissions) => {
      try {
          const response = await fetch('/api/v2/configuracoes/demanda-permissions', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(newPermissions)
          });
          const data = await response.json();
          if (data.success) {
              setPermissions(newPermissions);
              return true;
          }
          return false;
      } catch (e) {
          console.error(e);
          return false;
      }
  };

  return (
    <PermissionsContext.Provider value={{ 
        permissions, 
        loading, 
        canEditField, 
        canExecuteAction, 
        getVisibleColumns,
        updatePermissions,
        refreshPermissions: fetchPermissions
    }}>
      {children}
    </PermissionsContext.Provider>
  );
};

export const usePermissions = () => {
  const context = useContext(PermissionsContext);
  if (!context) {
    throw new Error('usePermissions must be used within a PermissionsProvider');
  }
  return context;
};
