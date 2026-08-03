import { useQuery } from '@tanstack/react-query';
import { dashboardApi } from './api';

export const useDashboardStats = () => {
  return useQuery({
    queryKey: ['dashboard', 'stats'],
    queryFn: dashboardApi.getStats,
  });
};

export const useDashboardOrders = (skip = 0, limit = 100) => {
  return useQuery({
    queryKey: ['dashboard', 'orders', skip, limit],
    queryFn: () => dashboardApi.getOrders(skip, limit),
  });
};

export const useDashboardPhotographers = (skip = 0, limit = 100) => {
  return useQuery({
    queryKey: ['dashboard', 'photographers', skip, limit],
    queryFn: () => dashboardApi.getPhotographers(skip, limit),
  });
};
