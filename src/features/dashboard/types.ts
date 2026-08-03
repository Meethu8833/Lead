export interface TopProduct {
  product_name: string;
  total_qty: number;
}

export interface TopCustomer {
  name: string;
  total_spent: number;
}

export interface DashboardStats {
  revenue_today: number;
  revenue_this_month: number;
  payments_today: number;
  pending_payments: number;
  pending_deliveries: number;
  orders_ready: number;
  orders_delivered_today: number;
  invoices_generated: number;
  invoices_pending: number;
  notifications_pending: number;
  notifications_failed: number;

  // New KPIs
  today_orders: number;
  weekly_revenue: number;
  monthly_revenue: number;
  pending_production: number;
  delayed_orders: number;
  top_products: TopProduct[];
  top_customers: TopCustomer[];
  outstanding_balance: number;
  average_order_value: number;
}

export interface OrderItem {
  id: string;
  order_id: string;
  product_name: string;
  product_category: string;
  quantity: number;
  unit_price: number;
  discount: number;
  subtotal: number;
  production_stage: string;
  is_deleted: boolean;
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
  status: string; // OrderStatus enum
  payment_status: string; // PaymentStatus enum
  customer_notes: string | null;
  internal_notes: string | null;
  delivered_at: string | null;
  created_at: string;
  updated_at: string;
  items?: OrderItem[];
}

export interface Photographer {
  id: string;
  name: string;
  studio_name: string;
  phone: string;
  email: string | null;
  city: string;
  address: string | null;
  category: string;
  lead_status: string;
  is_active: boolean;
  customer_since: string | null;
  created_at: string;
  updated_at: string;
}

export interface DashboardFiltersState {
  dateRange: 'today' | 'week' | 'month' | 'custom';
  startDate?: string; // YYYY-MM-DD
  endDate?: string;   // YYYY-MM-DD
}
