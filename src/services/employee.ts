import { api } from './api';
import { Employee } from '../types';

export interface PhoneUpdatePayload {
  phone: string;
}

export interface EmailUpdatePayload {
  email: string;
}

export const employeeService = {
  getProfile: async (): Promise<Employee> => {
    const response = await api.get<Employee>('/employees/me/profile');
    return response.data;
  },

  updateProfilePhoto: async (file: File): Promise<Employee> => {
    const formData = new FormData();
    formData.append('photo', file);
    const response = await api.post<Employee>('/employees/me/profile-photo', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  updatePhone: async (phone: string): Promise<Employee> => {
    const response = await api.put<Employee>('/employees/me/phone', { phone });
    return response.data;
  },

  updateEmail: async (email: string): Promise<Employee> => {
    const response = await api.put<Employee>('/employees/me/email', { email });
    return response.data;
  },

  getPermissions: async (): Promise<string[]> => {
    const response = await api.get<string[]>('/employees/me/permissions');
    return response.data;
  },
};
