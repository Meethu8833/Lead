import { api } from '../../services/api';
import {
  Order,
  OrderCreatePayload,
  OrderItem,
  OrderItemCreatePayload,
  OrderItemUpdatePayload,
  OrderUpdatePayload,
  Photographer,
  Product,
} from './types';

export const ordersApi = {
  list: async (skip = 0, limit = 200): Promise<Order[]> => {
    const response = await api.get<Order[]>('/orders', { params: { skip, limit } });
    return response.data;
  },

  getById: async (id: string): Promise<Order> => {
    const response = await api.get<Order>(`/orders/${id}`);
    return response.data;
  },

  create: async (payload: OrderCreatePayload): Promise<Order> => {
    const response = await api.post<Order>('/orders', payload);
    return response.data;
  },

  update: async (id: string, payload: OrderUpdatePayload): Promise<Order> => {
    const response = await api.put<Order>(`/orders/${id}`, payload);
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/orders/${id}`);
  },

  addItem: async (orderId: string, payload: OrderItemCreatePayload): Promise<OrderItem> => {
    const response = await api.post<OrderItem>(`/orders/${orderId}/items`, payload);
    return response.data;
  },

  updateItem: async (itemId: string, payload: OrderItemUpdatePayload): Promise<OrderItem> => {
    const response = await api.put<OrderItem>(`/order-items/${itemId}`, payload);
    return response.data;
  },

  removeItem: async (itemId: string): Promise<void> => {
    await api.delete(`/order-items/${itemId}`);
  },
};

// Lightweight lookups used to populate Orders form/filter selects.
// Kept local to the orders feature since no shared photographers/products
// feature module exists yet in the codebase.
export const ordersLookupApi = {
  listPhotographers: async (skip = 0, limit = 200): Promise<Photographer[]> => {
    const response = await api.get<Photographer[]>('/photographers', { params: { skip, limit } });
    return response.data;
  },

  listActiveProducts: async (skip = 0, limit = 200): Promise<Product[]> => {
    const response = await api.get<Product[]>('/products/search', {
      params: { is_active: true, skip, limit },
    });
    return response.data;
  },
};
