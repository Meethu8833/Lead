import * as React from 'react';
import { useNavigate } from 'react-router-dom';
import { PageContainer, PageHeader } from '../../../components/ui/LayoutHelpers';
import { ErrorState } from '../../../components/ui/ErrorState';
import { Button } from '../../../components/ui/Button';
import { useAuthStore, useNotificationStore } from '../../../app/store';
import { checkPermission } from '../../../components/auth/PermissionGuard';
import { useOrders, usePhotographersLookup, useDeleteOrder } from '../hooks';
import { OrdersTable } from '../components/OrdersTable';
import { OrderFilters } from '../components/OrderFilters';
import { OrdersListSkeleton } from '../components/OrderSkeleton';
import { DeleteOrderDialog } from '../components/DeleteOrderDialog';
import { DEFAULT_ORDER_FILTERS, Order, OrderFiltersState } from '../types';
import { Plus } from 'lucide-react';

export const OrdersPage = () => {
  const navigate = useNavigate();
  const { permissions, user } = useAuthStore();
  const { addToast } = useNotificationStore();

  const canCreate = checkPermission(permissions, 'orders:create', user?.role?.name);
  const canUpdate = checkPermission(permissions, 'orders:update', user?.role?.name);
  const canDelete = checkPermission(permissions, 'orders:delete', user?.role?.name);

  const ordersQuery = useOrders();
  const photographersQuery = usePhotographersLookup();
  const deleteOrderMutation = useDeleteOrder();

  const [filters, setFilters] = React.useState<OrderFiltersState>(DEFAULT_ORDER_FILTERS);
  const [page, setPage] = React.useState(1);
  const [pageSize, setPageSize] = React.useState(10);
  const [sorting, setSorting] = React.useState<{ key: string; direction: 'asc' | 'desc' }>({
    key: 'booking_date',
    direction: 'desc',
  });
  const [orderPendingDelete, setOrderPendingDelete] = React.useState<Order | null>(null);

  const photographers = photographersQuery.data || [];
  const photographerMap = React.useMemo(() => {
    const map = new Map(photographers.map((p) => [p.id, p]));
    return map;
  }, [photographers]);

  const filteredOrders = React.useMemo(() => {
    const orders = ordersQuery.data || [];
    const search = filters.search.trim().toLowerCase();

    return orders.filter((order) => {
      if (search) {
        const photographer = photographerMap.get(order.photographer_id);
        const haystack = [
          order.order_number,
          order.job_name,
          order.event_type,
          photographer?.name,
          photographer?.studio_name,
        ]
          .filter(Boolean)
          .join(' ')
          .toLowerCase();
        if (!haystack.includes(search)) return false;
      }
      if (filters.status && order.status !== filters.status) return false;
      if (filters.paymentStatus && order.payment_status !== filters.paymentStatus) return false;
      if (filters.photographerId && order.photographer_id !== filters.photographerId) return false;
      if (filters.bookingDateFrom && order.booking_date < filters.bookingDateFrom) return false;
      if (filters.bookingDateTo && order.booking_date > `${filters.bookingDateTo}T23:59:59`) return false;
      if (
        filters.expectedDeliveryFrom &&
        (!order.expected_delivery_date || order.expected_delivery_date < filters.expectedDeliveryFrom)
      )
        return false;
      if (
        filters.expectedDeliveryTo &&
        (!order.expected_delivery_date || order.expected_delivery_date > `${filters.expectedDeliveryTo}T23:59:59`)
      )
        return false;
      return true;
    });
  }, [ordersQuery.data, filters, photographerMap]);

  const sortedOrders = React.useMemo(() => {
    const result = [...filteredOrders];
    const { key, direction } = sorting;
    const modifier = direction === 'asc' ? 1 : -1;

    result.sort((a: any, b: any) => {
      let aVal = a[key];
      let bVal = b[key];
      if (key === 'photographer_id') {
        aVal = photographerMap.get(a.photographer_id)?.name || '';
        bVal = photographerMap.get(b.photographer_id)?.name || '';
      }
      if (aVal === bVal) return 0;
      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;
      if (typeof aVal === 'string' && typeof bVal === 'string') {
        return aVal.localeCompare(bVal) * modifier;
      }
      return (aVal < bVal ? -1 : 1) * modifier;
    });
    return result;
  }, [filteredOrders, sorting, photographerMap]);

  const paginatedOrders = React.useMemo(() => {
    const start = (page - 1) * pageSize;
    return sortedOrders.slice(start, start + pageSize);
  }, [sortedOrders, page, pageSize]);

  React.useEffect(() => {
    setPage(1);
  }, [filters]);

  const handleRetry = () => {
    ordersQuery.refetch();
    photographersQuery.refetch();
  };

  const handleDeleteConfirm = async () => {
    if (!orderPendingDelete) return;
    try {
      await deleteOrderMutation.mutateAsync(orderPendingDelete.id);
      addToast({ title: 'Order Deleted', message: `Order ${orderPendingDelete.order_number} was deleted.`, type: 'success' });
      setOrderPendingDelete(null);
    } catch (err: any) {
      addToast({
        title: 'Delete Failed',
        message: err.response?.data?.detail || 'Failed to delete order. Please try again.',
        type: 'error',
      });
    }
  };

  const isError = ordersQuery.isError || photographersQuery.isError;

  if (ordersQuery.isLoading || photographersQuery.isLoading) {
    return <OrdersListSkeleton />;
  }

  if (isError) {
    return (
      <PageContainer className="flex items-center justify-center min-h-[50vh]">
        <ErrorState
          title="Failed to load orders"
          description="There was a problem communicating with the server. Please check your network connection and try again."
          onRetry={handleRetry}
        />
      </PageContainer>
    );
  }

  return (
    <PageContainer data-testid="orders-page">
      <PageHeader
        title="Orders"
        description="Manage bookings from creation through delivery."
        actions={
          canCreate && (
            <Button
              leftIcon={<Plus className="h-4 w-4" />}
              onClick={() => navigate('/orders/new')}
              data-testid="create-order-btn"
            >
              Create Order
            </Button>
          )
        }
      />

      <OrderFilters filters={filters} onFilterChange={setFilters} photographers={photographers} />

      <OrdersTable
        orders={paginatedOrders}
        photographers={photographers}
        loading={ordersQuery.isRefetching}
        sorting={sorting}
        onSort={(key, direction) => setSorting({ key, direction })}
        pagination={{
          page,
          pageSize,
          totalItems: sortedOrders.length,
          onPageChange: setPage,
          onPageSizeChange: setPageSize,
        }}
        onView={(order) => navigate(`/orders/${order.id}`)}
        onEdit={(order) => navigate(`/orders/${order.id}/edit`)}
        onDelete={(order) => setOrderPendingDelete(order)}
        canUpdate={canUpdate}
        canDelete={canDelete}
      />

      <DeleteOrderDialog
        order={orderPendingDelete}
        isOpen={!!orderPendingDelete}
        onConfirm={handleDeleteConfirm}
        onCancel={() => setOrderPendingDelete(null)}
        isLoading={deleteOrderMutation.isPending}
      />
    </PageContainer>
  );
};
