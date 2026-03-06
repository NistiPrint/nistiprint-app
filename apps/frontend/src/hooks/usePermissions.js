import { useAuth } from '@/contexts/AuthContext';
import { usePermissions } from '@/contexts/PermissionsContext';

/**
 * Hook personalizado para gerenciar permissões de usuário
 */
const usePermissionsHook = () => {
  const { user } = useAuth();
  const { canEditField: canEditFieldDynamic, canExecuteAction: canExecuteActionDynamic } = usePermissions();
  
  /**
   * Verifica se o usuário pode editar um campo específico
   * @param {string} fieldName - Nome do campo a ser verificado
   * @returns {boolean} - Se o usuário tem permissão para editar o campo
   */
  const canEditFieldByUser = (fieldName) => {
    if (!user) return false;
    
    // Administradores podem editar todos os campos
    if (user.is_admin) return true;
    
    // Usuários do setor administrativo também têm permissões amplas
    if (user.setor_nome && user.setor_nome.toLowerCase() === 'administrativo') return true;
    
    // Verificar permissão específica para o setor do usuário usando a lógica dinâmica
    return canEditFieldDynamic(user.setor_nome, fieldName);
  };
  
  /**
   * Verifica se o usuário pode executar uma ação específica
   * @param {string} actionName - Nome da ação a ser verificada
   * @returns {boolean} - Se o usuário tem permissão para executar a ação
   */
  const canExecuteActionByUser = (actionName) => {
    if (!user) return false;
    
    // Administradores podem executar todas as ações
    if (user.is_admin) return true;
    
    // Usuários do setor administrativo também têm permissões amplas
    if (user.setor_nome && user.setor_nome.toLowerCase() === 'administrativo') return true;
    
    // Verificar permissão específica para o setor do usuário usando a lógica dinâmica
    return canExecuteActionDynamic(user.setor_nome, actionName);
  };
  
  return {
    canEditField: canEditFieldByUser,
    canExecuteAction: canExecuteActionByUser,
    userSetor: user?.setor_nome,
    isUserAdmin: user?.is_admin
  };
};

export default usePermissionsHook;