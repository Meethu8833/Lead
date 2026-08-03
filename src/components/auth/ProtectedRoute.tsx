import { Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '../../app/store';
import { checkPermission } from './PermissionGuard';

interface ProtectedRouteProps {
  children: React.ReactNode;
  requiredPermission?: string;
}

export default function ProtectedRoute({ children, requiredPermission }: ProtectedRouteProps) {
  const { authenticated, permissions, user, loading } = useAuthStore();
  const location = useLocation();

  if (loading) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-background text-foreground">
        <div className="flex flex-col items-center gap-2">
          <div className="h-10 w-10 animate-spin rounded-full border-4 border-primary border-t-transparent" />
          <p className="text-sm font-medium text-muted-foreground animate-pulse">Restoring session...</p>
        </div>
      </div>
    );
  }

  if (!authenticated) {
    // Redirect to /login but save the current location they were trying to access
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (requiredPermission) {
    const hasAccess = checkPermission(permissions, requiredPermission, user?.role?.name);
    if (!hasAccess) {
      return <Navigate to="/forbidden" replace />;
    }
  }

  return <>{children}</>;
}
