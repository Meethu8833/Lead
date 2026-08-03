import * as React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../../../components/ui/Card';
import { formatCurrency, formatDate, formatPhone } from '../../../utils/helpers';
import { Order, Photographer } from '../types';
import { OrderStatusBadge, PaymentStatusBadge, ProductionStageBadge } from './OrderStatusBadge';

interface OrderSummaryCardProps {
  order: Order;
  photographer: Photographer | undefined;
}

const Field = ({ label, value }: { label: string; value: React.ReactNode }) => (
  <div className="flex flex-col gap-0.5">
    <span className="text-xs font-medium text-muted-foreground">{label}</span>
    <span className="text-sm text-foreground">{value ?? '-'}</span>
  </div>
);

export const OrderSummaryCard = ({ order, photographer }: OrderSummaryCardProps) => {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6" data-testid="order-summary-card">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle className="text-lg">Order Summary</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          <Field label="Order Number" value={order.order_number} />
          <Field label="Job Name" value={order.job_name} />
          <Field label="Event Type" value={order.event_type} />
          <Field label="Booking Date" value={formatDate(order.booking_date)} />
          <Field label="Event Date" value={formatDate(order.event_date)} />
          <Field label="Expected Delivery" value={formatDate(order.expected_delivery_date)} />
          <Field label="Status" value={<OrderStatusBadge status={order.status} />} />
          <Field label="Production Stage" value={<ProductionStageBadge status={order.status} />} />
          <Field label="Payment Status" value={<PaymentStatusBadge status={order.payment_status} />} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Photographer / Customer</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {photographer ? (
            <>
              <Field label="Name" value={photographer.name} />
              <Field label="Studio" value={photographer.studio_name} />
              <Field label="Phone" value={formatPhone(photographer.phone)} />
              <Field label="Email" value={photographer.email} />
              <Field label="City" value={photographer.city} />
            </>
          ) : (
            <span className="text-sm text-muted-foreground">Photographer details unavailable</span>
          )}
        </CardContent>
      </Card>

      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle className="text-lg">Totals</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <Field label="Grand Total" value={formatCurrency(order.total_amount)} />
          <Field label="Advance Paid" value={formatCurrency(order.advance_paid)} />
          <Field
            label="Balance"
            value={
              <span className={order.balance_amount > 0 ? 'text-destructive font-semibold' : 'text-emerald-600 dark:text-emerald-500 font-semibold'}>
                {formatCurrency(order.balance_amount)}
              </span>
            }
          />
          <Field label="Delivered At" value={order.delivered_at ? formatDate(order.delivered_at) : 'Not delivered'} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Notes</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Field label="Customer Notes" value={order.customer_notes} />
          <Field label="Internal Notes" value={order.internal_notes} />
        </CardContent>
      </Card>
    </div>
  );
};
