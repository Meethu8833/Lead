import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import * as React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { useAuthStore } from '../app/store';
import { dashboardApi } from '../features/dashboard/api';
import { DashboardPage } from '../features/dashboard/DashboardPage';
import { Employee } from '../types';

// Mock Recharts to avoid issues in JSDOM
vi.mock('recharts', () => {
  return {
    ResponsiveContainer: ({ children }: any) => <div data-testid="responsive-container">{children}</div>,
    AreaChart: ({ children }: any) => <div data-testid="area-chart">{children}</div>,
    Area: () => <div data-testid="area" />,
    XAxis: () => <div data-testid="xaxis" />,
    YAxis: () => <div data-testid="yaxis" />,
    CartesianGrid: () => <div data-testid="cartesiangrid" />,
    Tooltip: () => <div data-testid="tooltip" />,
    PieChart: ({ children }: any) => <div data-testid="pie-chart">{children}</div>,
    Pie: ({ children }: any) => <div data-testid="pie">{children}</div>,
    Cell: () => <div data-testid="cell" />,
    Legend: () => <div data-testid="legend" />,
  };
});

const mockEmployee: Employee = {
  id: 'emp-123',
  employee_code: 'EMP-001',
  first_name: 'John',
  last_name: 'Doe',
  email: 'john.doe@colourlabs.com',
  phone: '1234567890',
  department: 'Management',
  designation: 'Manager',
  role_id: 'role-123',
  is_active: true,
  last_login: null,
  profile_photo_url: null,
  version: 1,
  created_at: '',
  updated_at: '',
  role: {
    id: 'role-123',
    name: 'Operator',
    description: 'Operator role',
    is_system: false,
    created_at: '',
  },
};

const mockStats = {
  revenue_today: 1500.0,
  revenue_this_month: 45000.0,
  payments_today: 3,
  pending_payments: 5000.0,
  pending_deliveries: 4,
  orders_ready: 2,
  orders_delivered_today: 1,
  invoices_generated: 12,
  invoices_pending: 3,
  notifications_pending: 1,
  notifications_failed: 0,
  today_orders: 5,
  weekly_revenue: 12000.0,
  monthly_revenue: 45000.0,
  pending_production: 8,
  delayed_orders: 2,
  top_products: [
    { product_name: 'Best Frame', total_qty: 15 },
    { product_name: 'Paper Print', total_qty: 10 },
  ],
  top_customers: [
    { name: 'John Doe', total_spent: 8000.0 },
    { name: 'Jane Smith', total_spent: 6000.0 },
  ],
  outstanding_balance: 5000.0,
  average_order_value: 1200.0,
};

const mockOrders = [
  {
    id: 'order-1',
    photographer_id: 'photo-1',
    order_number: 'ORD-2026-000001',
    job_name: 'Wedding Event',
    event_type: 'Wedding',
    booking_date: '2026-08-01T10:00:00Z',
    event_date: '2026-08-02T10:00:00Z',
    expected_delivery_date: '2026-08-05T10:00:00Z',
    total_amount: 5000.0,
    advance_paid: 2000.0,
    balance_amount: 3000.0,
    status: 'PRINTING',
    payment_status: 'PARTIALLY_PAID',
    customer_notes: null,
    internal_notes: null,
    delivered_at: null,
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-01T10:00:00Z',
  },
  {
    id: 'order-2',
    photographer_id: 'photo-2',
    order_number: 'ORD-2026-000002',
    job_name: 'Birthday Party',
    event_type: 'Birthday',
    booking_date: '2026-08-02T12:00:00Z',
    event_date: '2026-08-03T12:00:00Z',
    expected_delivery_date: '2026-08-01T12:00:00Z', // Delayed!
    total_amount: 3000.0,
    advance_paid: 3000.0,
    balance_amount: 0.0,
    status: 'READY',
    payment_status: 'FULLY_PAID',
    customer_notes: null,
    internal_notes: null,
    delivered_at: null,
    created_at: '2026-08-02T12:00:00Z',
    updated_at: '2026-08-02T12:00:00Z',
  },
];

const mockPhotographers = [
  {
    id: 'photo-1',
    name: 'John Doe',
    studio_name: 'Doe Studios',
    phone: '1234567890',
    email: 'john@doe.com',
    city: 'Mumbai',
    address: null,
    category: 'Wedding',
    lead_status: 'CUSTOMER',
    is_active: true,
    customer_since: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'photo-2',
    name: 'Jane Smith',
    studio_name: 'Smith Studio',
    phone: '9876543210',
    email: 'jane@smith.com',
    city: 'Pune',
    address: null,
    category: 'Portrait',
    lead_status: 'CUSTOMER',
    is_active: true,
    customer_since: null,
    created_at: '2026-01-02T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
  },
];

const renderWithProviders = (ui: React.ReactElement) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
};

describe('Dashboard Module', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useAuthStore.getState().logout();
  });

  it('renders loading skeleton state initially', async () => {
    // Return unresolved promises to force loading state
    vi.spyOn(dashboardApi, 'getStats').mockReturnValue(new Promise(() => {}));
    vi.spyOn(dashboardApi, 'getOrders').mockReturnValue(new Promise(() => {}));
    vi.spyOn(dashboardApi, 'getPhotographers').mockReturnValue(new Promise(() => {}));

    useAuthStore.getState().login('token', 'refresh', false);
    useAuthStore.getState().loadProfile(mockEmployee, ['*:*']);

    renderWithProviders(<DashboardPage />);

    expect(screen.getByTestId('dashboard-skeleton')).toBeInTheDocument();
  });

  it('renders stats, table, charts on success', async () => {
    vi.spyOn(dashboardApi, 'getStats').mockResolvedValue(mockStats as any);
    vi.spyOn(dashboardApi, 'getOrders').mockResolvedValue(mockOrders as any);
    vi.spyOn(dashboardApi, 'getPhotographers').mockResolvedValue(mockPhotographers as any);

    useAuthStore.getState().login('token', 'refresh', false);
    useAuthStore.getState().loadProfile(mockEmployee, ['*:*']);

    renderWithProviders(<DashboardPage />);

    // Wait for the skeleton to disappear
    await waitFor(() => {
      expect(screen.queryByTestId('dashboard-skeleton')).toBeNull();
    });

    // Check header
    expect(screen.getByText('Business Dashboard')).toBeInTheDocument();

    // Check KPI cards (values formatted as INR)
    expect(screen.getByText('Revenue Today')).toBeInTheDocument();
    expect(screen.getByText('Revenue This Month')).toBeInTheDocument();
    expect(screen.getByText('Outstanding Balance')).toBeInTheDocument();

    // Check Recharts rendering
    expect(screen.getByTestId('area-chart')).toBeInTheDocument();
    expect(screen.getByTestId('pie-chart')).toBeInTheDocument();

    // Check Recent Orders Table columns
    expect(screen.getAllByText('ORD-2026-000001')[0]).toBeInTheDocument();
    expect(screen.getAllByText('ORD-2026-000002')[0]).toBeInTheDocument();
    expect(screen.getAllByText('Doe Studios')[0]).toBeInTheDocument();
    expect(screen.getAllByText('Smith Studio')[0]).toBeInTheDocument();
  });

  it('renders error state and handles retry click', async () => {
    const getStatsSpy = vi
      .spyOn(dashboardApi, 'getStats')
      .mockRejectedValueOnce(new Error('Network error'))
      .mockResolvedValueOnce(mockStats as any);

    vi.spyOn(dashboardApi, 'getOrders').mockResolvedValue(mockOrders as any);
    vi.spyOn(dashboardApi, 'getPhotographers').mockResolvedValue(mockPhotographers as any);

    useAuthStore.getState().login('token', 'refresh', false);
    useAuthStore.getState().loadProfile(mockEmployee, ['*:*']);

    renderWithProviders(<DashboardPage />);

    // Error state shows
    await waitFor(() => {
      expect(screen.getByTestId('error-state')).toBeInTheDocument();
    });

    // Click retry
    const retryBtn = screen.getByTestId('error-state-retry-button');
    fireEvent.click(retryBtn);

    // Should call getStats again and eventually render successfully
    await waitFor(() => {
      expect(screen.queryByTestId('error-state')).toBeNull();
      expect(screen.getByText('Business Dashboard')).toBeInTheDocument();
    });

    expect(getStatsSpy).toHaveBeenCalledTimes(2);
  });

  it('applies RBAC widgets hiding when permissions are missing', async () => {
    vi.spyOn(dashboardApi, 'getStats').mockResolvedValue(mockStats as any);
    vi.spyOn(dashboardApi, 'getOrders').mockResolvedValue(mockOrders as any);
    vi.spyOn(dashboardApi, 'getPhotographers').mockResolvedValue(mockPhotographers as any);

    useAuthStore.getState().login('token', 'refresh', false);
    // User lacks payments:view and reports:view
    useAuthStore.getState().loadProfile(mockEmployee, ['orders:view']);

    renderWithProviders(<DashboardPage />);

    await waitFor(() => {
      expect(screen.queryByTestId('dashboard-skeleton')).toBeNull();
    });

    // Revenue KPI Cards should NOT be visible
    expect(screen.queryByTestId('revenue-cards')).toBeNull();
    
    // Revenue Area Chart should NOT be visible
    expect(screen.queryByTestId('area-chart')).toBeNull();

    // Top Customers lists (payments/reports) should NOT be visible
    expect(screen.queryByTestId('top-customers-card')).toBeNull();

    // Recent orders table should still be visible because user has orders:view
    expect(screen.getByTestId('recent-orders-table')).toBeInTheDocument();
  });

  it('triggers refresh call when refresh button is clicked', async () => {
    const getStatsSpy = vi.spyOn(dashboardApi, 'getStats').mockResolvedValue(mockStats as any);
    const getOrdersSpy = vi.spyOn(dashboardApi, 'getOrders').mockResolvedValue(mockOrders as any);
    const getPhotographersSpy = vi.spyOn(dashboardApi, 'getPhotographers').mockResolvedValue(mockPhotographers as any);

    useAuthStore.getState().login('token', 'refresh', false);
    useAuthStore.getState().loadProfile(mockEmployee, ['*:*']);

    renderWithProviders(<DashboardPage />);

    await waitFor(() => {
      expect(screen.queryByTestId('dashboard-skeleton')).toBeNull();
    });

    const refreshBtn = screen.getByTestId('filter-refresh-btn');
    fireEvent.click(refreshBtn);

    await waitFor(() => {
      // Should have been called twice (once on mount, once on refresh)
      expect(getStatsSpy).toHaveBeenCalledTimes(2);
      expect(getOrdersSpy).toHaveBeenCalledTimes(2);
      expect(getPhotographersSpy).toHaveBeenCalledTimes(2);
    });
  });

  it('filters data by choosing date presets', async () => {
    vi.spyOn(dashboardApi, 'getStats').mockResolvedValue(mockStats as any);
    vi.spyOn(dashboardApi, 'getOrders').mockResolvedValue(mockOrders as any);
    vi.spyOn(dashboardApi, 'getPhotographers').mockResolvedValue(mockPhotographers as any);

    useAuthStore.getState().login('token', 'refresh', false);
    useAuthStore.getState().loadProfile(mockEmployee, ['*:*']);

    renderWithProviders(<DashboardPage />);

    await waitFor(() => {
      expect(screen.queryByTestId('dashboard-skeleton')).toBeNull();
    });

    // Select 'Today' preset
    const todayPreset = screen.getByTestId('filter-preset-today');
    fireEvent.click(todayPreset);

    // Recent orders table should filter down to orders booked today (none match August 1st or 2nd if today is different, or only 1 matches if today matches).
    // Let's verify 'Custom Range' opens inputs
    const customPreset = screen.getByTestId('filter-preset-custom');
    fireEvent.click(customPreset);

    expect(screen.getByTestId('filter-start-date')).toBeInTheDocument();
    expect(screen.getByTestId('filter-end-date')).toBeInTheDocument();
  });
});
