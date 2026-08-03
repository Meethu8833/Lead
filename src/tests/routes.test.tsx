import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { useAuthStore } from '../app/store';
import ProtectedRoute from '../components/auth/ProtectedRoute';
import { Employee } from '../types';

const mockEmployee: Employee = {
  id: '00000000-0000-0000-0000-000000000000',
  employee_code: 'EMP-001',
  first_name: 'John',
  last_name: 'Doe',
  email: 'john.doe@colourlabs.com',
  phone: '+1234567890',
  department: 'Production',
  designation: 'Operator',
  role_id: null,
  is_active: true,
  last_login: null,
  profile_photo_url: null,
  version: 1,
  created_at: '',
  updated_at: '',
  role: {
    id: 'role-1',
    name: 'Operator',
    description: 'Operator role',
    is_system: false,
    created_at: '',
  },
};

describe('ProtectedRoute Route Guard', () => {
  beforeEach(() => {
    useAuthStore.getState().logout();
  });

  it('should redirect unauthenticated users to login', () => {
    render(
      <MemoryRouter initialEntries={['/protected']}>
        <Routes>
          <Route
            path="/protected"
            element={
              <ProtectedRoute>
                <div data-testid="protected-content">Protected Area</div>
              </ProtectedRoute>
            }
          />
          <Route path="/login" element={<div data-testid="login-content">Login Page</div>} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.queryByTestId('protected-content')).toBeNull();
    expect(screen.getByTestId('login-content')).toBeInTheDocument();
  });

  it('should allow authenticated users to view content', () => {
    useAuthStore.getState().login('fake-access', 'fake-refresh', false);
    useAuthStore.getState().loadProfile(mockEmployee, []);

    render(
      <MemoryRouter initialEntries={['/protected']}>
        <Routes>
          <Route
            path="/protected"
            element={
              <ProtectedRoute>
                <div data-testid="protected-content">Protected Area</div>
              </ProtectedRoute>
            }
          />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByTestId('protected-content')).toBeInTheDocument();
  });

  it('should redirect to forbidden if user lacks required permission', () => {
    useAuthStore.getState().login('fake-access', 'fake-refresh', false);
    useAuthStore.getState().loadProfile(mockEmployee, ['orders:view']);

    render(
      <MemoryRouter initialEntries={['/protected']}>
        <Routes>
          <Route
            path="/protected"
            element={
              <ProtectedRoute requiredPermission="payments:view">
                <div data-testid="protected-content">Protected Area</div>
              </ProtectedRoute>
            }
          />
          <Route path="/forbidden" element={<div data-testid="forbidden-content">Forbidden Page</div>} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.queryByTestId('protected-content')).toBeNull();
    expect(screen.getByTestId('forbidden-content')).toBeInTheDocument();
  });
});
