import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ordersApi, ordersLookupApi } from './api';
import {
  Order,
  OrderCreatePayload,
  OrderItem,
  OrderItemCreatePayload,
  OrderItemUpdatePayload,
  OrderUpdatePayload,
} from './types';

const ordersListKey = ['orders', 'list'] as const;
const orderDetailKey = (id: string) => ['orders', 'detail', id] as const;

export const useOrders = (skip = 0, limit = 200) =>
  useQuery({
    queryKey: [...ordersListKey, skip, limit],
    queryFn: () => ordersApi.list(skip, limit),
  });

export const useOrder = (id: string | undefined) =>
  useQuery({
    queryKey: orderDetailKey(id || ''),
    queryFn: () => ordersApi.getById(id as string),
    enabled: !!id,
  });

export const usePhotographersLookup = () =>
  useQuery({
    queryKey: ['orders', 'lookup', 'photographers'],
    queryFn: () => ordersLookupApi.listPhotographers(),
  });

export const useActiveProductsLookup = () =>
  useQuery({
    queryKey: ['orders', 'lookup', 'products'],
    queryFn: () => ordersLookupApi.listActiveProducts(),
  });

export const useCreateOrder = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: OrderCreatePayload) => ordersApi.create(payload),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ordersListKey });
      queryClient.setQueryData(orderDetailKey(created.id), created);
    },
  });
};

export const useUpdateOrder = (id: string) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: OrderUpdatePayload) => ordersApi.update(id, payload),
    onMutate: async (payload) => {
      await queryClient.cancelQueries({ queryKey: orderDetailKey(id) });
      const previous = queryClient.getQueryData<Order>(orderDetailKey(id));
      if (previous) {
        queryClient.setQueryData<Order>(orderDetailKey(id), { ...previous, ...payload } as Order);
      }
      return { previous };
    },
    onError: (_err, _payload, context) => {
      if (context?.previous) {
        queryClient.setQueryData(orderDetailKey(id), context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: orderDetailKey(id) });
      queryClient.invalidateQueries({ queryKey: ordersListKey });
    },
  });
};

export const useDeleteOrder = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => ordersApi.delete(id),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: ordersListKey });
      const previousLists = queryClient.getQueriesData<Order[]>({ queryKey: ordersListKey });
      previousLists.forEach(([key, data]) => {
        if (data) {
          queryClient.setQueryData<Order[]>(key, data.filter((order) => order.id !== id));
        }
      });
      return { previousLists };
    },
    onError: (_err, _id, context) => {
      context?.previousLists?.forEach(([key, data]) => {
        queryClient.setQueryData(key, data);
      });
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ordersListKey });
    },
  });
};

export const useAddOrderItem = (orderId: string) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: OrderItemCreatePayload) => ordersApi.addItem(orderId, payload),
    onSuccess: (item) => {
      const previous = queryClient.getQueryData<Order>(orderDetailKey(orderId));
      if (previous) {
        queryClient.setQueryData<Order>(orderDetailKey(orderId), {
          ...previous,
          items: [...previous.items, item],
        });
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: orderDetailKey(orderId) });
      queryClient.invalidateQueries({ queryKey: ordersListKey });
    },
  });
};

export const useUpdateOrderItem = (orderId: string) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, payload }: { itemId: string; payload: OrderItemUpdatePayload }) =>
      ordersApi.updateItem(itemId, payload),
    onMutate: async ({ itemId, payload }) => {
      await queryClient.cancelQueries({ queryKey: orderDetailKey(orderId) });
      const previous = queryClient.getQueryData<Order>(orderDetailKey(orderId));
      if (previous) {
        queryClient.setQueryData<Order>(orderDetailKey(orderId), {
          ...previous,
          items: previous.items.map((item) =>
            item.id === itemId ? ({ ...item, ...payload } as OrderItem) : item
          ),
        });
      }
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(orderDetailKey(orderId), context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: orderDetailKey(orderId) });
      queryClient.invalidateQueries({ queryKey: ordersListKey });
    },
  });
};

export const useRemoveOrderItem = (orderId: string) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (itemId: string) => ordersApi.removeItem(itemId),
    onMutate: async (itemId) => {
      await queryClient.cancelQueries({ queryKey: orderDetailKey(orderId) });
      const previous = queryClient.getQueryData<Order>(orderDetailKey(orderId));
      if (previous) {
        queryClient.setQueryData<Order>(orderDetailKey(orderId), {
          ...previous,
          items: previous.items.filter((item) => item.id !== itemId),
        });
      }
      return { previous };
    },
    onError: (_err, _itemId, context) => {
      if (context?.previous) {
        queryClient.setQueryData(orderDetailKey(orderId), context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: orderDetailKey(orderId) });
      queryClient.invalidateQueries({ queryKey: ordersListKey });
    },
  });
};
