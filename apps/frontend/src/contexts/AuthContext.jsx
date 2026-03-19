import UserService from '@/services/UserService';
import { createContext, useContext, useEffect, useRef, useState } from 'react';

const AuthContext = createContext();

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const timeoutRef = useRef(null);

  useEffect(() => {
    checkAuthStatus();

    // Safety timeout to prevent infinite loading
    timeoutRef.current = setTimeout(() => {
       console.warn('Auth check timeout - forcing loading to false');
       // We can't reliably check current state of 'loading' here due to closure,
       // but if this runs, it means checkAuthStatus hasn't cleared it yet.
       setLoading((prevLoading) => {
         if (prevLoading) {
           setUser(null);
           return false;
         }
         return prevLoading;
       });
    }, 10000); // 10 seconds timeout

    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  const checkAuthStatus = async () => {
    try {
      // Check if there's a valid session by trying to get current user
      const response = await UserService.getCurrentUser();
      setUser(response);
    } catch (error) {
      // If 401, it's just that the user is not logged in. No need to log as error.
      if (error.response && error.response.status === 401) {
         // Quietly handle unauthenticated state
      } else {
         console.log('Error checking auth status:', error);
      }
      // No valid session
      setUser(null);
    } finally {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
      setLoading(false);
    }
  };

  const login = async (credentials) => {
    setLoading(true);
    try {
      const response = await UserService.login(credentials);
      setUser(response.usuario);
      setLoading(false);
      return response;
    } catch (error) {
      setLoading(false);
      throw error;
    }
  };

  const logout = async () => {
    try {
      await UserService.logout();
    } catch (error) {
      console.error('Erro no logout:', error);
    } finally {
      setUser(null);
      setLoading(false);
      // Clear all client-side storage
      localStorage.clear();
      sessionStorage.clear();
      // Force page reload to clear any cached state
      window.location.href = '/login';
    }
  };

  const isAuthenticated = () => {
    return !!user;
  };

  const isAdmin = () => {
    return user?.is_admin === true;
  };

  const hasPermission = (recurso, acao) => {
    if (isAdmin()) return true;
    // Check if user belongs to "Administrativo" sector and grant all permissions
    if (user && user.setor_nome === 'Administrativo') return true;
    if (!user || !user.permissoes) return false;

    const permissaoRecurso = user.permissoes[recurso];
    if (!permissaoRecurso) return false;

    if (acao === 'ler') return permissaoRecurso.ler;
    if (acao === 'criar') return permissaoRecurso.criar;
    if (acao === 'editar') return permissaoRecurso.editar;
    if (acao === 'excluir') return permissaoRecurso.excluir;

    return false;
  };

  const value = {
    user,
    loading,
    login,
    logout,
    isAuthenticated,
    isAdmin,
    hasPermission,
    checkAuthStatus,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};
