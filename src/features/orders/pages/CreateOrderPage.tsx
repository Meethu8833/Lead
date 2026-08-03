import { useNavigate } from 'react-router-dom';
import { PageContainer, PageHeader } from '../../../components/ui/LayoutHelpers';
import { ErrorState } from '../../../components/ui/ErrorState';
import { Button } from '../../../components/ui/Button';
import { useNotificationStore } from '../../../app/store';
import { usePhotographersLookup, useCreateOrder } from '../hooks';
import { OrderForm } from '../components/OrderForm';
import { OrderFormSkeleton } from '../components/OrderSkeleton';
import { OrderFormValues } from '../validation';
import { OrderCreatePayload } from '../types';
import { ArrowLeft } from 'lucide-react';

export const CreateOrderPage = () => {
  const navigate = useNavigate();
  const { addToast } = useNotificationStore();
  const photographersQuery = usePhotographersLookup();
  const createOrderMutation = useCreateOrder();

  const handleSubmit = async (values: OrderFormValues) => {
    const payload: OrderCreatePayload = {
      photographer_id: values.photographer_id,
      job_name: values.job_name,
      event_type: values.event_type || null,
      booking_date: values.booking_date,
      event_date: values.event_date || null,
      expected_delivery_date: values.expected_delivery_date || null,
      advance_paid: values.advance_paid,
      customer_notes: values.customer_notes || null,
      internal_notes: values.internal_notes || null,
    };

    try {
      const created = await createOrderMutation.mutateAsync(payload);
      addToast({
        title: 'Order Created',
        message: `Order ${created.order_number} was created successfully. You can now add order items.`,
        type: 'success',
      });
      navigate(`/orders/${created.id}/edit`);
    } catch (err: any) {
      addToast({
        title: 'Create Failed',
        message: err.response?.data?.detail || 'Failed to create order. Please check the form and try again.',
        type: 'error',
      });
    }
  };

  if (photographersQuery.isLoading) {
    return <OrderFormSkeleton />;
  }

  if (photographersQuery.isError) {
    return (
      <PageContainer className="flex items-center justify-center min-h-[50vh]">
        <ErrorState
          title="Failed to load photographers"
          description="There was a problem communicating with the server. Please try again."
          onRetry={() => photographersQuery.refetch()}
        />
      </PageContainer>
    );
  }

  return (
    <PageContainer data-testid="create-order-page">
      <PageHeader
        title="Create Order"
        description="Book a new order for a photographer / customer."
        actions={
          <Button variant="outline" leftIcon={<ArrowLeft className="h-4 w-4" />} onClick={() => navigate('/orders')}>
            Back
          </Button>
        }
      />

      <OrderForm
        mode="create"
        photographers={photographersQuery.data || []}
        onSubmit={handleSubmit}
        isSubmitting={createOrderMutation.isPending}
      />
    </PageContainer>
  );
};
