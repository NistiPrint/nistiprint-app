import { useAuth } from '@/contexts/AuthContext';
import { usePermissions } from '@/contexts/PermissionsContext';

export default function usePermissionsHook() {
  const { user } = useAuth();
  const { canEditField: checkField, canExecuteAction: checkAction } = usePermissions();
  return {
    canEditField: (fieldName) => Boolean(user && checkField(user.setor_id, fieldName)),
    canExecuteAction: (actionName) => Boolean(user && checkAction(user.setor_id, actionName)),
    userSetor: user?.setor_nome,
    isUserAdmin: user?.is_admin === true,
  };
}
