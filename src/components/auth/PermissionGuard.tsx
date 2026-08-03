import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuthStore } from '../../app/store';

export const checkPermission = (
  userPermissions: string[],
  requiredPermission: string,
  roleName?: string | null
): boolean => {
  if (roleName === 'Administrator') return true;
  if (userPermissions.includes('*:*')) return true;

  const [reqModule, reqAction] = requiredPermission.split(':');
  if (!reqModule || !reqAction) return false;

  return userPermissions.some((perm) => {
    const parts = perm.split(':');
    if (parts.length !== 2) return false;
    const [pModule, pAction] = parts;
    const moduleMatch = pModule === '*' || pModule === reqModule;
    const actionMatch = pAction === '*' || pAction === reqAction;
    return moduleMatch && actionMatch;
  });
};

interface PermissionGuardProps {
  requiredPermission: string;
  children: React.ReactNode;
  fallbackType?: 'hide' | 'disable' | 'redirect';
}

export default function PermissionGuard({
  requiredPermission,
  children,
  fallbackType = 'hide',
}: PermissionGuardProps) {
  const { permissions, user } = useAuthStore();
  const hasAccess = checkPermission(permissions, requiredPermission, user?.role?.name);

  if (hasAccess) {
    return <>{children}</>;
  }

  if (fallbackType === 'redirect') {
    return <Navigate to="/forbidden" replace />;
  }

  if (fallbackType === 'disable') {
    if (React.isValidElement(children)) {
      return React.cloneElement(children as React.ReactElement<any>, {
        disabled: true,
        title: "You do not have permission to perform this action",
      });
    }
  }

  // default 'hide'
  return null;
}
