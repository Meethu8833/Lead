import * as React from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { PageContainer, PageHeader } from '../../../components/ui/LayoutHelpers';
import { ErrorState } from '../../../components/ui/ErrorState';
import { Button } from '../../../components/ui/Button';
import { useNotificationStore } from '../../../app/store';
import {
  useOrder,
  usePhotographersLookup,
  useActiveProductsLookup,
  useUpdateOrder,
  useAddOrderItem,
  useUpdateOrderItem,
  useRemoveOrderItem,
} from '../hooks';
import { OrderForm } from '../components/OrderForm';
import { AddItemDialog } from '../components/AddItemDialog';
import { OrderItemEditor } from '../components/OrderItemEditor';
import { OrderFormSkeleton } from '../components/OrderSkeleton';
import { OrderFormValues } from '../validation';
import { OrderItem, OrderItemCreatePayload, OrderItemUpdatePayload, OrderUpdatePayload } from '../types';
import { ArrowLeft } from 'lucide-react';

export const EditOrderPage = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { addToast } = useNotificationStore();

  const orderQuery = useOrder(id);
  const photographersQuery = usePhotographersLookup();
  const productsQuery = useActiveProductsLookup();

  const updateOrderMutation = useUpdateOrder(id || '');
  const addItemMutation = useAddOrderItem(id || '');
  const updateItemMutation = useUpdateOrderItem(id || '');
  const removeItemMutation = useRemoveOrderItem(id || '');

  const [isAddItemOpen, setIsAddItemOpen] = React.useState(false);
  const [editingItem, setEditingItem] = React.useState<OrderItem | null>(null);

  const isLoading = orderQuery.isLoading || photographersQuery.isLoading || productsQuery.isLoading;
  const isError = orderQuery.isError || photographersQuery.isError || productsQuery.isError;

  const handleSubmit = async (values: OrderFormValues) => {
    if (!orderQuery.data) return;
    const payload: OrderUpdatePayload = {
      photographer_id: values.photographer_id,
      job_name: values.job_name,
      event_type: values.event_type || null,
      booking_date: values.booking_date,
      event_date: values.event_date || null,
      expected_delivery_date: values.expected_delivery_date || null,
      advance_paid: values.advance_paid,
      customer_notes: values.customer_notes || null,
      internal_notes: values.internal_notes || null,
      version: orderQuery.data.version,
    };

    try {
      await updateOrderMutation.mutateAsync(payload);
      addToast({ title: 'Order Updated', message: `Order ${orderQuery.data.order_number} was updated successfully.`, type: 'success' });
    } catch (err: any) {
      const isConflict = err.response?.status === 409;
      addToast({
        title: isConflict ? 'Version Conflict' : 'Update Failed',
        message:
          err.response?.data?.detail ||
          (isConflict
            ? 'This order was modified elsewhere. Please reload before continuing.'
            : 'Failed to update order. Please try again.'),
        type: 'error',
      });
      if (isConflict) {
        orderQuery.refetch();
      }
    }
  };

  const handleAddItem = async (payload: OrderItemCreatePayload) => {
    try {
      await addItemMutation.mutateAsync(payload);
      addToast({ title: 'Item Added', message: 'The item was added to the order.', type: 'success' });
      setIsAddItemOpen(false);
    } catch (err: any) {
      addToast({
        title: 'Add Item Failed',
        message: err.response?.data?.detail || 'Failed to add item. Please try again.',
        type: 'error',
      });
    }
  };

  const handleRemoveItem = async (item: OrderItem) => {
    try {
      await removeItemMutation.mutateAsync(item.id);
      addToast({ title: 'Item Removed', message: `${item.product_name} was removed from the order.`, type: 'success' });
    } catch (err: any) {
      addToast({
        title: 'Remove Item Failed',
        message: err.response?.data?.detail || 'Failed to remove item. Please try again.',
        type: 'error',
      });
    }
  };

  const handleUpdateQuantity = async (item: OrderItem, quantity: number) => {
    try {
      await updateItemMutation.mutateAsync({ itemId: item.id, payload: { quantity } });
    } catch (err: any) {
      addToast({
        title: 'Update Failed',
        message: err.response?.data?.detail || 'Failed to update quantity.',
        type: 'error',
      });
    }
  };

  const handleUpdateUnitPrice = async (item: OrderItem, unitPrice: number) => {
    try {
      await updateItemMutation.mutateAsync({ itemId: item.id, payload: { unit_price: unitPrice } });
    } catch (err: any) {
      addToast({
        title: 'Update Failed',
        message: err.response?.data?.detail || 'Failed to update unit price.',
        type: 'error',
      });
    }
  };

  const handleSaveEditedItem = async (itemId: string, payload: OrderItemUpdatePayload) => {
    try {
      await updateItemMutation.mutateAsync({ itemId, payload });
      addToast({ title: 'Item Updated', message: 'The order item was updated.', type: 'success' });
      setEditingItem(null);
    } catch (err: any) {
      addToast({
        title: 'Update Failed',
        message: err.response?.data?.detail || 'Failed to update item. Please try again.',
        type: 'error',
      });
    }
  };

  const handleDuplicateItem = async (item: OrderItem) => {
    if (!item.product_id) {
      addToast({
        title: 'Cannot Duplicate',
        message: 'This item has no linked catalog product to duplicate.',
        type: 'error',
      });
      return;
    }
    try {
      await addItemMutation.mutateAsync({
        product_id: item.product_id,
        unit_price: item.unit_price,
        quantity: item.quantity,
        discount: item.discount,
        album_size: item.album_size || undefined,
        sheet_type: item.sheet_type || undefined,
        cover_type: item.cover_type || undefined,
        remarks: item.remarks || undefined,
      });
      addToast({ title: 'Item Duplicated', message: `A copy of ${item.product_name} was added to the order.`, type: 'success' });
    } catch (err: any) {
      addToast({
        title: 'Duplicate Failed',
        message: err.response?.data?.detail || 'Failed to duplicate item. Please try again.',
        type: 'error',
      });
    }
  };

  if (isLoading) {
    return <OrderFormSkeleton />;
  }

  if (isError || !orderQuery.data) {
    return (
      <PageContainer className="flex items-center justify-center min-h-[50vh]">
        <ErrorState
          title="Failed to load order"
          description="This order could not be found or there was a problem communicating with the server."
          onRetry={() => {
            orderQuery.refetch();
            photographersQuery.refetch();
            productsQuery.refetch();
          }}
        />
      </PageContainer>
    );
  }

  const order = orderQuery.data;
  const itemMutationLoading = addItemMutation.isPending || updateItemMutation.isPending || removeItemMutation.isPending;

  return (
    <PageContainer data-testid="edit-order-page">
      <PageHeader
        title={`Edit ${order.order_number}`}
        description={order.job_name}
        actions={
          <Button variant="outline" leftIcon={<ArrowLeft className="h-4 w-4" />} onClick={() => navigate(`/orders/${order.id}`)}>
            Back to Order
          </Button>
        }
      />

      <OrderForm
        mode="edit"
        order={order}
        photographers={photographersQuery.data || []}
        onSubmit={handleSubmit}
        isSubmitting={updateOrderMutation.isPending}
        onOpenAddItemDialog={() => setIsAddItemOpen(true)}
        onRemoveItem={handleRemoveItem}
        onUpdateItemQuantity={handleUpdateQuantity}
        onUpdateItemUnitPrice={handleUpdateUnitPrice}
        onEditItem={setEditingItem}
        onDuplicateItem={handleDuplicateItem}
        itemMutationLoading={itemMutationLoading}
      />

      <AddItemDialog
        isOpen={isAddItemOpen}
        onClose={() => setIsAddItemOpen(false)}
        onSubmit={handleAddItem}
        products={productsQuery.data || []}
        isSubmitting={addItemMutation.isPending}
      />

      <OrderItemEditor
        isOpen={!!editingItem}
        item={editingItem}
        products={productsQuery.data || []}
        onClose={() => setEditingItem(null)}
        onSave={handleSaveEditedItem}
        isSubmitting={updateItemMutation.isPending}
      />
    </PageContainer>
  );
};
