import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { useAuthStore } from '../app/store';
import PermissionGuard, { checkPermission } from '../components/auth/PermissionGuard';
import { Employee } from '../types';

const mockEmployee: Employee = {
  id: 'emp-id',
  employee_code: 'EMP-001',
  first_name: 'Regular',
  last_name: 'Employee',
  email: 'staff@company.com',
  phone: '+1234567',
  department: 'Sales',
  designation: 'Sales Agent',
  role_id: null,
  is_active: true,
  last_login: null,
  profile_photo_url: null,
  version: 1,
  created_at: '',
  updated_at: '',
  role: {
    id: 'role-regular',
    name: 'Sales',
    description: 'Sales role',
    is_system: false,
    created_at: '',
  },
};

const adminEmployee: Employee = {
  ...mockEmployee,
  first_name: 'Admin',
  role: {
    id: 'role-admin',
    name: 'Administrator',
    description: 'Admin role',
    is_system: true,
    created_at: '',
  },
};

describe('Role-Based Access Control (RBAC) Logic', () => {
  describe('checkPermission function', () => {
    it('should grant access to exact permission match', () => {
      const hasAccess = checkPermission(['orders:view', 'inventory:view'], 'orders:view');
      expect(hasAccess).toBe(true);
    });

    it('should deny access if permission is missing', () => {
      const hasAccess = checkPermission(['orders:view'], 'orders:create');
      expect(hasAccess).toBe(false);
    });

    it('should support wildcard action checking (e.g. orders:*)', () => {
      const hasAccess = checkPermission(['orders:*'], 'orders:view');
      expect(hasAccess).toBe(true);
    });

    it('should support wildcard module checking (e.g. *:view)', () => {
      const hasAccess = checkPermission(['*:view'], 'orders:view');
      expect(hasAccess).toBe(true);
    });

    it('should support absolute global wildcard checking (*:*)', () => {
      const hasAccess = checkPermission(['*:*'], 'inventory:create');
      expect(hasAccess).toBe(true);
    });

    it('should bypass checks for Administrator role', () => {
      const hasAccess = checkPermission([], 'orders:delete', 'Administrator');
      expect(hasAccess).toBe(true);
    });
  });

  describe('PermissionGuard React component', () => {
    beforeEach(() => {
      useAuthStore.getState().logout();
    });

    it('should render children when user has permission', () => {
      useAuthStore.getState().login('access', 'refresh', false);
      useAuthStore.getState().loadProfile(mockEmployee, ['orders:view']);

      render(
        <PermissionGuard requiredPermission="orders:view">
          <div data-testid="allowed">Visible Content</div>
        </PermissionGuard>
      );

      expect(screen.getByTestId('allowed')).toBeInTheDocument();
    });

    it('should render null (hide) when user lacks permission by default', () => {
      useAuthStore.getState().login('access', 'refresh', false);
      useAuthStore.getState().loadProfile(mockEmployee, ['inventory:view']);

      render(
        <PermissionGuard requiredPermission="orders:view">
          <div data-testid="allowed">Visible Content</div>
        </PermissionGuard>
      );

      expect(screen.queryByTestId('allowed')).toBeNull();
    });

    it('should disable children when fallbackType is "disable"', () => {
      useAuthStore.getState().login('access', 'refresh', false);
      useAuthStore.getState().loadProfile(mockEmployee, ['orders:view']); // lacks orders:create

      render(
        <PermissionGuard requiredPermission="orders:create" fallbackType="disable">
          <button data-testid="action-btn">Action Button</button>
        </PermissionGuard>
      );

      const btn = screen.getByTestId('action-btn');
      expect(btn).toBeInTheDocument();
      expect(btn).toBeDisabled();
    });

    it('should bypass rendering checks for admin users', () => {
      useAuthStore.getState().login('access', 'refresh', false);
      useAuthStore.getState().loadProfile(adminEmployee, []); // no permissions but role is Administrator

      render(
        <PermissionGuard requiredPermission="orders:delete">
          <div data-testid="admin-content">Admin Content</div>
        </PermissionGuard>
      );

      expect(screen.getByTestId('admin-content')).toBeInTheDocument();
    });
  });
});
