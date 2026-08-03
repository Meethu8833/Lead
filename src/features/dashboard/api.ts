import { api } from '../../services/api';
import { DashboardStats, Order, Photographer } from './types';

export const dashboardApi = {
  getStats: async (): Promise<DashboardStats> => {
    const response = await api.get<DashboardStats>('/dashboard');
    return response.data;
  },

  getOrders: async (skip = 0, limit = 100): Promise<Order[]> => {
    const response = await api.get<Order[]>('/orders', {
      params: { skip, limit },
    });
    return response.data;
  },

  getPhotographers: async (skip = 0, limit = 100): Promise<Photographer[]> => {
    const response = await api.get<Photographer[]>('/photographers', {
      params: { skip, limit },
    });
    return response.data;
  },
};
