// Type definitions for the Orders feature.
// Mirrors app/schemas/order.py and app/schemas/order_item.py on the backend.

export const ORDER_STATUSES = [
  'RECEIVED',
  'DESIGNING',
  'EDITING',
  'COLOR_CORRECTION',
  'PRINTING',
  'LAMINATION',
  'QUALITY_CHECK',
  'PACKING',
  'READY',
  'DELIVERED',
  'CANCELLED',
] as const;

export type OrderStatus = (typeof ORDER_STATUSES)[number];

// OrderItem.production_stage shares the exact same enum values as OrderStatus on the backend.
export type ProductionStage = OrderStatus;

// The backend has no immutability flag on OrderItem at all — product_name/product_category/
// unit_price are simply copied from Product once at creation and never re-synced (see
// app/models/order_item.py docstring). This is a client-side-only UX heuristic: once an item's
// production_stage reaches PACKING or later (or CANCELLED), treat its pricing fields as locked
// in the UI. The backend does not enforce this — a direct API call could still edit it.
const LOCKED_FROM_STAGE_INDEX = ORDER_STATUSES.indexOf('PACKING');

export const isProductionStageLocked = (stage: ProductionStage): boolean =>
  ORDER_STATUSES.indexOf(stage) >= LOCKED_FROM_STAGE_INDEX;

// GST does not exist on Order/OrderItem in the backend today (only on the separate Invoice
// model, out of scope this phase). This default mirrors Invoice's own default gst_percentage
// (app/schemas/invoice.py) purely so the client-side GST estimate preview isn't an arbitrary
// number — it is never sent to or read from the backend.
export const DEFAULT_GST_PERCENTAGE = 18;

export const PAYMENT_STATUSES = [
  'PENDING',
  'PARTIALLY_PAID',
  'FULLY_PAID',
  'OVERPAID',
] as const;

export type PaymentStatus = (typeof PAYMENT_STATUSES)[number];

export interface Photographer {
  id: string;
  name: string;
  studio_name: string;
  phone: string;
  email: string | null;
  city: string;
  category: string;
  is_active: boolean;
}

export interface Product {
  id: string;
  name: string;
  category: string;
  size: string | null;
  unit: string;
  description: string | null;
  base_price: number;
  is_active: boolean;
}

export interface OrderItem {
  id: string;
  order_id: string;
  product_id: string | null;
  product_name: string;
  product_category: string;
  unit_price: number;
  quantity: number;
  discount: number;
  subtotal: number;
  album_size: string | null;
  sheet_type: string | null;
  cover_type: string | null;
  remarks: string | null;
  production_stage: ProductionStage;
  started_at: string | null;
  completed_at: string | null;
  assigned_employee: string | null;
  production_notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface Order {
  id: string;
  photographer_id: string;
  order_number: string;
  job_name: string;
  event_type: string | null;
  booking_date: string;
  event_date: string | null;
  expected_delivery_date: string | null;
  total_amount: number;
  advance_paid: number;
  balance_amount: number;
  status: OrderStatus;
  payment_status: PaymentStatus;
  customer_notes: string | null;
  internal_notes: string | null;
  delivered_at: string | null;
  created_at: string;
  updated_at: string;
  version: number;
  items: OrderItem[];
}

export interface OrderCreatePayload {
  photographer_id: string;
  job_name: string;
  event_type?: string | null;
  booking_date: string;
  event_date?: string | null;
  expected_delivery_date?: string | null;
  advance_paid?: number;
  status?: OrderStatus;
  customer_notes?: string | null;
  internal_notes?: string | null;
}

export interface OrderUpdatePayload extends Partial<OrderCreatePayload> {
  version?: number;
}

export interface OrderItemCreatePayload {
  product_id: string;
  unit_price?: number | null;
  quantity: number;
  discount?: number;
  album_size?: string | null;
  sheet_type?: string | null;
  cover_type?: string | null;
  remarks?: string | null;
}

export interface OrderItemUpdatePayload {
  product_id?: string;
  unit_price?: number;
  quantity?: number;
  discount?: number;
  album_size?: string | null;
  sheet_type?: string | null;
  cover_type?: string | null;
  remarks?: string | null;
  version?: number;
}

export interface OrderFiltersState {
  search: string;
  status: OrderStatus | '';
  paymentStatus: PaymentStatus | '';
  photographerId: string;
  bookingDateFrom: string;
  bookingDateTo: string;
  expectedDeliveryFrom: string;
  expectedDeliveryTo: string;
}

export const DEFAULT_ORDER_FILTERS: OrderFiltersState = {
  search: '',
  status: '',
  paymentStatus: '',
  photographerId: '',
  bookingDateFrom: '',
  bookingDateTo: '',
  expectedDeliveryFrom: '',
  expectedDeliveryTo: '',
};
