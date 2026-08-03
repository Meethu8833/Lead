import { describe, it, expect, beforeEach } from 'vitest';
import { useAuthStore } from '../app/store';
import { Employee } from '../types';

const mockEmployee: Employee = {
  id: '00000000-0000-0000-0000-000000000000',
  employee_code: 'EMP-001',
  first_name: 'John',
  last_name: 'Doe',
  email: 'john.doe@colourlabs.com',
  phone: '+1234567890',
  department: 'Production',
  designation: 'Technician',
  role_id: null,
  is_active: true,
  last_login: null,
  profile_photo_url: null,
  version: 1,
  created_at: '',
  updated_at: '',
  role: {
    id: 'role-123',
    name: 'Operator',
    description: 'Operator role',
    is_system: false,
    created_at: '',
  },
};

describe('Authentication Store (useAuthStore)', () => {
  beforeEach(() => {
    // Clear stores and storage before each test
    useAuthStore.getState().logout();
  });

  it('should initialize with default empty credentials', () => {
    const state = useAuthStore.getState();
    expect(state.accessToken).toBeNull();
    expect(state.refreshToken).toBeNull();
    expect(state.user).toBeNull();
    expect(state.permissions).toEqual([]);
    expect(state.authenticated).toBe(false);
  });

  it('should handle login and set tokens and authenticated state', () => {
    const accessToken = 'fake-access-token';
    const refreshToken = 'fake-refresh-token';
    
    useAuthStore.getState().login(accessToken, refreshToken, true);

    const state = useAuthStore.getState();
    expect(state.accessToken).toBe(accessToken);
    expect(state.refreshToken).toBe(refreshToken);
    expect(state.authenticated).toBe(true);
    expect(state.rememberMe).toBe(true);
    expect(localStorage.getItem('accessToken')).toBe(accessToken);
  });

  it('should load user profile and permissions', () => {
    const mockPermissions = ['orders:view', 'orders:create'];
    
    useAuthStore.getState().loadProfile(mockEmployee, mockPermissions);

    const state = useAuthStore.getState();
    expect(state.user).toEqual(mockEmployee);
    expect(state.permissions).toEqual(mockPermissions);
    expect(state.authenticated).toBe(true);
  });

  it('should clear tokens and user details on logout', () => {
    useAuthStore.getState().login('access', 'refresh', true);
    useAuthStore.getState().loadProfile(mockEmployee, ['orders:view']);

    useAuthStore.getState().logout();

    const state = useAuthStore.getState();
    expect(state.accessToken).toBeNull();
    expect(state.refreshToken).toBeNull();
    expect(state.user).toBeNull();
    expect(state.permissions).toEqual([]);
    expect(state.authenticated).toBe(false);
    expect(localStorage.getItem('accessToken')).toBeNull();
  });
});
