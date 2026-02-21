import { useAuth } from '@/contexts/AuthContext';

/**
 * Component to wrap content that requires specific permissions.
 * 
 * Usage:
 * <Can I="escrever" a="vendas">
 *   <button>Criar Pedido</button>
 * </Can>
 */
const Can = ({ I, a, children, fallback = null }) => {
  const { hasPermission } = useAuth();

  if (hasPermission(a, I)) {
    return children;
  }

  return fallback;
};

export default Can;
