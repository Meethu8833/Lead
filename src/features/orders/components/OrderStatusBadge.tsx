import { Badge } from '../../../components/ui/Badge';
import { StatusBadge } from '../../../components/ui/StatusBadge';
import { OrderStatus, PaymentStatus } from '../types';

const ORDER_STATUS_TO_BADGE: Record<OrderStatus, string> = {
  RECEIVED: 'pending',
  DESIGNING: 'processing',
  EDITING: 'processing',
  COLOR_CORRECTION: 'processing',
  PRINTING: 'processing',
  LAMINATION: 'processing',
  QUALITY_CHECK: 'processing',
  PACKING: 'processing',
  READY: 'approved',
  DELIVERED: 'completed',
  CANCELLED: 'cancelled',
};

export const OrderStatusBadge = ({ status }: { status: OrderStatus }) => (
  <StatusBadge status={ORDER_STATUS_TO_BADGE[status] || 'pending'} data-testid="order-status-badge">
    {status.replace(/_/g, ' ')}
  </StatusBadge>
);

export const ProductionStageBadge = ({ status }: { status: OrderStatus }) => (
  <Badge variant="secondary" className="capitalize" data-testid="order-production-stage-badge">
    {status.replace(/_/g, ' ').toLowerCase()}
  </Badge>
);

const PAYMENT_STATUS_VARIANT: Record<PaymentStatus, 'warning' | 'success' | 'info' | 'danger' | 'secondary'> = {
  PENDING: 'warning',
  PARTIALLY_PAID: 'info',
  FULLY_PAID: 'success',
  OVERPAID: 'success',
};

export const PaymentStatusBadge = ({ status }: { status: PaymentStatus }) => (
  <Badge
    variant={PAYMENT_STATUS_VARIANT[status] || 'secondary'}
    className="capitalize"
    data-testid="order-payment-status-badge"
  >
    {status.replace(/_/g, ' ').toLowerCase()}
  </Badge>
);
