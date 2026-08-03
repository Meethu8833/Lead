import * as React from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { PageContainer, PageHeader, Section } from '../../../components/ui/LayoutHelpers';
import { ErrorState } from '../../../components/ui/ErrorState';
import { Button } from '../../../components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '../../../components/ui/Card';
import { Timeline } from '../../../components/ui/Timeline';
import { useAuthStore, useNotificationStore } from '../../../app/store';
import { checkPermission } from '../../../components/auth/PermissionGuard';
import { useOrder, usePhotographersLookup, useDeleteOrder } from '../hooks';
import { OrderSummaryCard } from '../components/OrderSummaryCard';
import { OrderItemsTable } from '../components/OrderItemsTable';
import { OrderDetailsSkeleton } from '../components/OrderSkeleton';
import { DeleteOrderDialog } from '../components/DeleteOrderDialog';
import { formatDateTime } from '../../../utils/helpers';
import { Pencil, Trash2, ArrowLeft } from 'lucide-react';

export const OrderDetailsPage = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { permissions, user } = useAuthStore();
  const { addToast } = useNotificationStore();

  const canUpdate = checkPermission(permissions, 'orders:update', user?.role?.name);
  const canDelete = checkPermission(permissions, 'orders:delete', user?.role?.name);

  const orderQuery = useOrder(id);
  const photographersQuery = usePhotographersLookup();
  const deleteOrderMutation = useDeleteOrder();
  const [isDeleteOpen, setIsDeleteOpen] = React.useState(false);

  const isLoading = orderQuery.isLoading || photographersQuery.isLoading;
  const isError = orderQuery.isError || photographersQuery.isError;

  const handleDeleteConfirm = async () => {
    if (!orderQuery.data) return;
    try {
      await deleteOrderMutation.mutateAsync(orderQuery.data.id);
      addToast({ title: 'Order Deleted', message: `Order ${orderQuery.data.order_number} was deleted.`, type: 'success' });
      navigate('/orders');
    } catch (err: any) {
      addToast({
        title: 'Delete Failed',
        message: err.response?.data?.detail || 'Failed to delete order. Please try again.',
        type: 'error',
      });
      setIsDeleteOpen(false);
    }
  };

  if (isLoading) {
    return <OrderDetailsSkeleton />;
  }

  if (isError || !orderQuery.data) {
    return (
      <PageContainer className="flex items-center justify-center min-h-[50vh]">
        <ErrorState
          title="Failed to load order"
          description="This order could not be found or there was a problem communicating with the server."
          onRetry={() => orderQuery.refetch()}
        />
      </PageContainer>
    );
  }

  const order = orderQuery.data;
  const photographer = (photographersQuery.data || []).find((p) => p.id === order.photographer_id);

  return (
    <PageContainer data-testid="order-details-page">
      <PageHeader
        title={order.order_number}
        description={order.job_name}
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" leftIcon={<ArrowLeft className="h-4 w-4" />} onClick={() => navigate('/orders')}>
              Back
            </Button>
            {canUpdate && (
              <Button
                leftIcon={<Pencil className="h-4 w-4" />}
                onClick={() => navigate(`/orders/${order.id}/edit`)}
                data-testid="order-details-edit-btn"
              >
                Edit
              </Button>
            )}
            {canDelete && (
              <Button
                variant="danger"
                leftIcon={<Trash2 className="h-4 w-4" />}
                onClick={() => setIsDeleteOpen(true)}
                data-testid="order-details-delete-btn"
              >
                Delete
              </Button>
            )}
          </div>
        }
      />

      <OrderSummaryCard order={order} photographer={photographer} />

      <Section title="Order Items">
        <OrderItemsTable
          items={order.items}
          editable={false}
          onAddItem={() => {}}
          onRemoveItem={() => {}}
          onUpdateQuantity={() => {}}
          onUpdateUnitPrice={() => {}}
        />
      </Section>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Timeline</CardTitle>
          </CardHeader>
          <CardContent>
            <Timeline
              items={[
                { id: 'created', title: 'Order Created', timestamp: formatDateTime(order.created_at), status: 'completed' },
                { id: 'updated', title: 'Last Updated', timestamp: formatDateTime(order.updated_at), status: 'completed' },
                ...(order.delivered_at
                  ? [{ id: 'delivered', title: 'Delivered', timestamp: formatDateTime(order.delivered_at), status: 'completed' as const }]
                  : [{ id: 'delivered', title: 'Delivery Pending', status: 'upcoming' as const }]),
              ]}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Related Sections</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Payments, invoices, deliveries, notifications, and attachments will appear here in a future phase.
            </p>
          </CardContent>
        </Card>
      </div>

      <DeleteOrderDialog
        order={order}
        isOpen={isDeleteOpen}
        onConfirm={handleDeleteConfirm}
        onCancel={() => setIsDeleteOpen(false)}
        isLoading={deleteOrderMutation.isPending}
      />
    </PageContainer>
  );
};
