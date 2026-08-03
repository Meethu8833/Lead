import { api } from './api';
import { TokenResponse, Employee } from '../types';

export interface LoginPayload {
  email: string;
  password: string;
}

export interface ForgotPasswordPayload {
  email: string;
}

export interface ResetPasswordPayload {
  token: string;
  new_password: string;
}

export interface ChangePasswordPayload {
  old_password: string;
  new_password: string;
}

export const authService = {
  login: async (payload: LoginPayload): Promise<TokenResponse> => {
    const response = await api.post<TokenResponse>('/auth/login', payload);
    return response.data;
  },

  logout: async (refreshToken: string): Promise<void> => {
    await api.post(`/auth/logout?refresh_token=${encodeURIComponent(refreshToken)}`);
  },

  logoutAll: async (): Promise<void> => {
    await api.post('/auth/logout-all');
  },

  refresh: async (refreshToken: string): Promise<TokenResponse> => {
    const response = await api.post<TokenResponse>(`/auth/refresh?refresh_token=${encodeURIComponent(refreshToken)}`);
    return response.data;
  },

  forgotPassword: async (payload: ForgotPasswordPayload): Promise<{ success: boolean; detail: string; token?: string }> => {
    const response = await api.post('/auth/forgot-password', payload);
    return response.data;
  },

  resetPassword: async (payload: ResetPasswordPayload): Promise<{ success: boolean; detail: string }> => {
    const response = await api.post('/auth/reset-password', payload);
    return response.data;
  },

  changePassword: async (payload: ChangePasswordPayload): Promise<{ success: boolean; detail: string }> => {
    const response = await api.post('/auth/change-password', payload);
    return response.data;
  },

  me: async (): Promise<Employee> => {
    const response = await api.get<Employee>('/auth/me');
    return response.data;
  },
};
