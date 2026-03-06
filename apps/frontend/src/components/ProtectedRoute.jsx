import { useAuth } from '@/contexts/AuthContext';
import { Navigate, useLocation } from 'react-router-dom';

const ProtectedRoute = ({ children, requireAdmin = false, permission = null }) => {
  const { isAuthenticated, isAdmin, hasPermission, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-32 w-32 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (!isAuthenticated()) {
    // Redirect to login page with return url
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (requireAdmin && !isAdmin()) {
    // Redirect to home if user is not admin but tries to access admin route
    return <Navigate to="/" replace />;
  }

  if (permission && !hasPermission(permission.a, permission.I)) {
    // Redirect to home if user doesn't have required permission
    return <Navigate to="/" replace />;
  }

  return children;
};

export default ProtectedRoute;
