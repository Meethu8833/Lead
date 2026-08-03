import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import dayjs from 'dayjs';
import { Card, CardContent, CardHeader, CardTitle } from '../../../components/ui/Card';
import { Input } from '../../../components/ui/Input';
import { Select } from '../../../components/ui/Select';
import { Textarea } from '../../../components/ui/Textarea';
import { CurrencyInput } from '../../../components/ui/CurrencyInput';
import { Button } from '../../../components/ui/Button';
import { OrderItemsTable } from './OrderItemsTable';
import { TotalsCard, computeOrderItemTotals } from './TotalsCard';
import { GSTSummary } from './GSTSummary';
import { useAuthStore } from '../../../app/store';
import { checkPermission } from '../../../components/auth/PermissionGuard';
import { orderFormSchema, OrderFormValues } from '../validation';
import { Order, OrderItem, Photographer } from '../types';
import { Save } from 'lucide-react';

const toDateInputValue = (value: string | null | undefined) => (value ? dayjs(value).format('YYYY-MM-DD') : '');

interface OrderFormProps {
  mode: 'create' | 'edit';
  order?: Order;
  photographers: Photographer[];
  onSubmit: (values: OrderFormValues) => Promise<void>;
  isSubmitting?: boolean;

  // Order items management — only meaningful once the order exists (edit mode),
  // since backend items are a sub-resource created via POST /orders/{id}/items.
  onRemoveItem?: (item: OrderItem) => Promise<void>;
  onUpdateItemQuantity?: (item: OrderItem, quantity: number) => Promise<void>;
  onUpdateItemUnitPrice?: (item: OrderItem, unitPrice: number) => Promise<void>;
  onEditItem?: (item: OrderItem) => void;
  onDuplicateItem?: (item: OrderItem) => Promise<void>;
  onOpenAddItemDialog?: () => void;
  itemMutationLoading?: boolean;
}

export const OrderForm = ({
  mode,
  order,
  photographers,
  onSubmit,
  isSubmitting = false,
  onRemoveItem,
  onUpdateItemQuantity,
  onUpdateItemUnitPrice,
  onEditItem,
  onDuplicateItem,
  onOpenAddItemDialog,
  itemMutationLoading = false,
}: OrderFormProps) => {
  const { permissions, user } = useAuthStore();
  const canUpdateOrder = checkPermission(permissions, 'orders:update', user?.role?.name);
  const itemsEditable = mode === 'edit' && !!order && canUpdateOrder;

  const {
    register,
    handleSubmit,
    control,
    watch,
    formState: { errors },
  } = useForm<OrderFormValues>({
    resolver: zodResolver(orderFormSchema),
    defaultValues: {
      photographer_id: order?.photographer_id || '',
      job_name: order?.job_name || '',
      event_type: order?.event_type || '',
      booking_date: toDateInputValue(order?.booking_date) || dayjs().format('YYYY-MM-DD'),
      event_date: toDateInputValue(order?.event_date),
      expected_delivery_date: toDateInputValue(order?.expected_delivery_date),
      advance_paid: order?.advance_paid ?? 0,
      customer_notes: order?.customer_notes || '',
      internal_notes: order?.internal_notes || '',
    },
  });

  const submitHandler = handleSubmit(onSubmit);

  return (
    <form onSubmit={submitHandler} className="space-y-6" data-testid="order-form">
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Order Details</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Controller
            control={control}
            name="photographer_id"
            render={({ field }) => (
              <Select
                label="Photographer / Customer"
                required
                placeholder="Select a photographer"
                fullWidth
                value={field.value}
                onChange={field.onChange}
                error={errors.photographer_id?.message}
                options={photographers.map((p) => ({ label: `${p.name} (${p.studio_name})`, value: p.id }))}
                data-testid="order-form-photographer"
              />
            )}
          />

          <Input
            label="Job Name"
            required
            fullWidth
            {...register('job_name')}
            error={errors.job_name?.message}
            data-testid="order-form-job-name"
          />

          <Input
            label="Event Type"
            fullWidth
            placeholder="e.g. Wedding, Birthday"
            {...register('event_type')}
            error={errors.event_type?.message}
            data-testid="order-form-event-type"
          />

          <Input
            label="Booking Date"
            type="date"
            required
            fullWidth
            {...register('booking_date')}
            error={errors.booking_date?.message}
            data-testid="order-form-booking-date"
          />

          <Input
            label="Event Date"
            type="date"
            fullWidth
            {...register('event_date')}
            error={errors.event_date?.message}
            data-testid="order-form-event-date"
          />

          <Input
            label="Expected Delivery"
            type="date"
            fullWidth
            {...register('expected_delivery_date')}
            error={errors.expected_delivery_date?.message}
            data-testid="order-form-expected-delivery"
          />

          <Controller
            control={control}
            name="advance_paid"
            render={({ field }) => (
              <CurrencyInput
                label="Advance Paid"
                fullWidth
                value={field.value}
                onChangeValue={(val) => field.onChange(val ?? 0)}
                error={errors.advance_paid?.message}
                data-testid="order-form-advance-paid"
              />
            )}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Notes</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Textarea
            label="Customer Notes"
            fullWidth
            {...register('customer_notes')}
            error={errors.customer_notes?.message}
            data-testid="order-form-customer-notes"
          />
          <Textarea
            label="Internal Notes"
            fullWidth
            {...register('internal_notes')}
            error={errors.internal_notes?.message}
            data-testid="order-form-internal-notes"
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Order Items</CardTitle>
        </CardHeader>
        <CardContent>
          {mode === 'edit' && order ? (
            <OrderItemsTable
              items={order.items}
              editable={itemsEditable}
              onAddItem={() => onOpenAddItemDialog?.()}
              onRemoveItem={(item) => onRemoveItem?.(item)}
              onUpdateQuantity={(item, qty) => onUpdateItemQuantity?.(item, qty)}
              onUpdateUnitPrice={(item, price) => onUpdateItemUnitPrice?.(item, price)}
              onEditItem={(item) => onEditItem?.(item)}
              onDuplicateItem={(item) => onDuplicateItem?.(item)}
              isMutating={itemMutationLoading}
            />
          ) : (
            <p className="text-sm text-muted-foreground" data-testid="order-form-items-hint">
              Save the order first to start adding order items.
            </p>
          )}
        </CardContent>
      </Card>

      {mode === 'edit' && order && (
        <>
          <TotalsCard items={order.items} advancePaid={watch('advance_paid') || 0} />
          <GSTSummary taxableValue={computeOrderItemTotals(order.items).netTotal} />
        </>
      )}

      <div className="flex justify-end">
        <Button type="submit" leftIcon={<Save className="h-4 w-4" />} isLoading={isSubmitting} data-testid="order-form-submit">
          {mode === 'create' ? 'Create Order' : 'Save Changes'}
        </Button>
      </div>
    </form>
  );
};
