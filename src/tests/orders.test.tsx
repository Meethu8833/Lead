import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor, within } from '@testing-library/react';
import * as React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { useAuthStore } from '../app/store';
import { ordersApi, ordersLookupApi } from '../features/orders/api';
import { OrdersPage } from '../features/orders/pages/OrdersPage';
import { CreateOrderPage } from '../features/orders/pages/CreateOrderPage';
import { EditOrderPage } from '../features/orders/pages/EditOrderPage';
import { OrderDetailsPage } from '../features/orders/pages/OrderDetailsPage';
import { Employee } from '../types';
import { Order, Photographer, Product } from '../features/orders/types';

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

const mockPhotographers: Photographer[] = [
  {
    id: 'photo-1',
    name: 'John Doe',
    studio_name: 'Doe Studios',
    phone: '1234567890',
    email: 'john@doe.com',
    city: 'Mumbai',
    category: 'Wedding',
    is_active: true,
  },
  {
    id: 'photo-2',
    name: 'Jane Smith',
    studio_name: 'Smith Studio',
    phone: '9876543210',
    email: 'jane@smith.com',
    city: 'Pune',
    category: 'Portrait',
    is_active: true,
  },
];

const mockProducts: Product[] = [
  {
    id: 'product-1',
    name: 'Premium Album',
    category: 'Album',
    size: '12x12',
    unit: 'piece',
    description: null,
    base_price: 2500,
    is_active: true,
  },
];

const mockOrders: Order[] = [
  {
    id: 'order-1',
    photographer_id: 'photo-1',
    order_number: 'ORD-2026-000001',
    job_name: 'Wedding Event',
    event_type: 'Wedding',
    booking_date: '2026-08-01T10:00:00Z',
    event_date: '2026-08-02T10:00:00Z',
    expected_delivery_date: '2026-08-15T10:00:00Z',
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
    version: 1,
    items: [
      {
        id: 'item-1',
        order_id: 'order-1',
        product_id: 'product-1',
        product_name: 'Premium Album',
        product_category: 'Album',
        unit_price: 2500,
        quantity: 2,
        discount: 0,
        subtotal: 5000,
        album_size: null,
        sheet_type: null,
        cover_type: null,
        remarks: null,
        production_stage: 'PRINTING',
        started_at: null,
        completed_at: null,
        assigned_employee: null,
        production_notes: null,
        created_at: '2026-08-01T10:00:00Z',
        updated_at: '2026-08-01T10:00:00Z',
      },
    ],
  },
  {
    id: 'order-2',
    photographer_id: 'photo-2',
    order_number: 'ORD-2026-000002',
    job_name: 'Birthday Party',
    event_type: 'Birthday',
    booking_date: '2026-08-02T12:00:00Z',
    event_date: '2026-08-03T12:00:00Z',
    expected_delivery_date: '2026-08-10T12:00:00Z',
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
    version: 1,
    items: [],
  },
];

const renderWithProviders = (ui: React.ReactElement, initialEntries: string[] = ['/orders']) => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>{ui}</MemoryRouter>
    </QueryClientProvider>
  );
};

const loginAs = (permissions: string[]) => {
  useAuthStore.getState().login('token', 'refresh', false);
  useAuthStore.getState().loadProfile(mockEmployee, permissions);
};

describe('Orders Module', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useAuthStore.getState().logout();
  });

  describe('OrdersPage', () => {
    it('renders the loading skeleton while data is in flight', () => {
      vi.spyOn(ordersApi, 'list').mockReturnValue(new Promise(() => {}));
      vi.spyOn(ordersLookupApi, 'listPhotographers').mockReturnValue(new Promise(() => {}));
      loginAs(['orders:view']);

      renderWithProviders(<OrdersPage />);

      expect(screen.getByTestId('orders-list-skeleton')).toBeInTheDocument();
    });

    it('renders orders in the table on API success', async () => {
      vi.spyOn(ordersApi, 'list').mockResolvedValue(mockOrders);
      vi.spyOn(ordersLookupApi, 'listPhotographers').mockResolvedValue(mockPhotographers);
      loginAs(['orders:view', 'orders:create', 'orders:update', 'orders:delete']);

      renderWithProviders(<OrdersPage />);

      await waitFor(() => {
        expect(screen.queryByTestId('orders-list-skeleton')).toBeNull();
      });

      expect(screen.getByTestId('orders-table')).toBeInTheDocument();
      expect(screen.getByText('ORD-2026-000001')).toBeInTheDocument();
      expect(screen.getByText('ORD-2026-000002')).toBeInTheDocument();
      expect(screen.getByText('Doe Studios')).toBeInTheDocument();
      expect(screen.getByText('Smith Studio')).toBeInTheDocument();

      // Column headers required by spec
      const table = screen.getByTestId('orders-table');
      ['Order Number', 'Booking Date', 'Status', 'Production Stage', 'Payment Status', 'Expected Delivery', 'Grand Total', 'Balance', 'Actions'].forEach(
        (header) => {
          expect(within(table).getByText(header)).toBeInTheDocument();
        }
      );
    });

    it('renders an error state and retries on demand', async () => {
      const listSpy = vi
        .spyOn(ordersApi, 'list')
        .mockRejectedValueOnce(new Error('Network error'))
        .mockResolvedValueOnce(mockOrders);
      vi.spyOn(ordersLookupApi, 'listPhotographers').mockResolvedValue(mockPhotographers);
      loginAs(['orders:view']);

      renderWithProviders(<OrdersPage />);

      await waitFor(() => {
        expect(screen.getByTestId('error-state')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByTestId('error-state-retry-button'));

      await waitFor(() => {
        expect(screen.queryByTestId('error-state')).toBeNull();
        expect(screen.getByTestId('orders-table')).toBeInTheDocument();
      });

      expect(listSpy).toHaveBeenCalledTimes(2);
    });

    it('filters orders by search text', async () => {
      vi.spyOn(ordersApi, 'list').mockResolvedValue(mockOrders);
      vi.spyOn(ordersLookupApi, 'listPhotographers').mockResolvedValue(mockPhotographers);
      loginAs(['orders:view']);

      renderWithProviders(<OrdersPage />);

      await waitFor(() => expect(screen.getByTestId('orders-table')).toBeInTheDocument());

      const searchInput = screen.getByTestId('order-filter-search');
      fireEvent.change(searchInput, { target: { value: 'Birthday' } });

      await waitFor(() => {
        expect(screen.queryByText('ORD-2026-000001')).toBeNull();
        expect(screen.getByText('ORD-2026-000002')).toBeInTheDocument();
      });
    });

    it('filters orders by status', async () => {
      vi.spyOn(ordersApi, 'list').mockResolvedValue(mockOrders);
      vi.spyOn(ordersLookupApi, 'listPhotographers').mockResolvedValue(mockPhotographers);
      loginAs(['orders:view']);

      renderWithProviders(<OrdersPage />);

      await waitFor(() => expect(screen.getByTestId('orders-table')).toBeInTheDocument());

      fireEvent.change(screen.getByTestId('order-filter-status'), { target: { value: 'READY' } });

      await waitFor(() => {
        expect(screen.queryByText('ORD-2026-000001')).toBeNull();
        expect(screen.getByText('ORD-2026-000002')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByTestId('order-filter-clear'));

      await waitFor(() => {
        expect(screen.getByText('ORD-2026-000001')).toBeInTheDocument();
      });
    });

    it('hides create/edit/delete actions when the user lacks permission (RBAC)', async () => {
      vi.spyOn(ordersApi, 'list').mockResolvedValue(mockOrders);
      vi.spyOn(ordersLookupApi, 'listPhotographers').mockResolvedValue(mockPhotographers);
      loginAs(['orders:view']);

      renderWithProviders(<OrdersPage />);

      await waitFor(() => expect(screen.getByTestId('orders-table')).toBeInTheDocument());

      expect(screen.queryByTestId('create-order-btn')).toBeNull();
      expect(screen.queryByTestId('order-edit-btn-ORD-2026-000001')).toBeNull();
      expect(screen.queryByTestId('order-delete-btn-ORD-2026-000001')).toBeNull();
      expect(screen.getByTestId('order-view-btn-ORD-2026-000001')).toBeInTheDocument();
    });

    it('shows create/edit/delete actions when the user has permission (RBAC)', async () => {
      vi.spyOn(ordersApi, 'list').mockResolvedValue(mockOrders);
      vi.spyOn(ordersLookupApi, 'listPhotographers').mockResolvedValue(mockPhotographers);
      loginAs(['orders:view', 'orders:create', 'orders:update', 'orders:delete']);

      renderWithProviders(<OrdersPage />);

      await waitFor(() => expect(screen.getByTestId('orders-table')).toBeInTheDocument());

      expect(screen.getByTestId('create-order-btn')).toBeInTheDocument();
      expect(screen.getByTestId('order-edit-btn-ORD-2026-000001')).toBeInTheDocument();
      expect(screen.getByTestId('order-delete-btn-ORD-2026-000001')).toBeInTheDocument();
    });

    it('deletes an order after confirming in the DeleteOrderDialog', async () => {
      vi.spyOn(ordersApi, 'list').mockResolvedValue(mockOrders);
      vi.spyOn(ordersLookupApi, 'listPhotographers').mockResolvedValue(mockPhotographers);
      const deleteSpy = vi.spyOn(ordersApi, 'delete').mockResolvedValue(undefined);
      loginAs(['orders:view', 'orders:delete']);

      renderWithProviders(<OrdersPage />);

      await waitFor(() => expect(screen.getByTestId('orders-table')).toBeInTheDocument());

      fireEvent.click(screen.getByTestId('order-delete-btn-ORD-2026-000001'));

      const dialog = await screen.findByTestId('confirmation-dialog');
      expect(within(dialog).getByText(/ORD-2026-000001/)).toBeInTheDocument();

      fireEvent.click(screen.getByTestId('confirmation-confirm'));

      await waitFor(() => {
        expect(deleteSpy).toHaveBeenCalledWith('order-1');
      });
    });

    it('cancelling the delete confirmation does not call the API', async () => {
      vi.spyOn(ordersApi, 'list').mockResolvedValue(mockOrders);
      vi.spyOn(ordersLookupApi, 'listPhotographers').mockResolvedValue(mockPhotographers);
      const deleteSpy = vi.spyOn(ordersApi, 'delete').mockResolvedValue(undefined);
      loginAs(['orders:view', 'orders:delete']);

      renderWithProviders(<OrdersPage />);

      await waitFor(() => expect(screen.getByTestId('orders-table')).toBeInTheDocument());

      fireEvent.click(screen.getByTestId('order-delete-btn-ORD-2026-000001'));
      await screen.findByTestId('confirmation-dialog');

      fireEvent.click(screen.getByTestId('confirmation-cancel'));

      await waitFor(() => {
        expect(screen.queryByTestId('confirmation-dialog')).toBeNull();
      });
      expect(deleteSpy).not.toHaveBeenCalled();
    });
  });

  describe('CreateOrderPage', () => {
    it('shows validation errors when required fields are missing', async () => {
      vi.spyOn(ordersLookupApi, 'listPhotographers').mockResolvedValue(mockPhotographers);
      const createSpy = vi.spyOn(ordersApi, 'create');
      loginAs(['orders:view', 'orders:create']);

      renderWithProviders(<CreateOrderPage />, ['/orders/new']);

      await waitFor(() => expect(screen.getByTestId('order-form')).toBeInTheDocument());

      fireEvent.click(screen.getByTestId('order-form-submit'));

      await waitFor(() => {
        expect(screen.getByText('Photographer / Customer is required')).toBeInTheDocument();
        expect(screen.getByText('Job name is required')).toBeInTheDocument();
      });

      expect(createSpy).not.toHaveBeenCalled();
      expect(screen.getByTestId('order-form-items-hint')).toBeInTheDocument();
    });

    it('creates an order and redirects to the edit page', async () => {
      vi.spyOn(ordersLookupApi, 'listPhotographers').mockResolvedValue(mockPhotographers);
      const created = { ...mockOrders[0], id: 'order-new' };
      vi.spyOn(ordersApi, 'create').mockResolvedValue(created);
      vi.spyOn(ordersApi, 'getById').mockResolvedValue(created);
      vi.spyOn(ordersLookupApi, 'listActiveProducts').mockResolvedValue(mockProducts);
      loginAs(['orders:view', 'orders:create', 'orders:update']);

      render(
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <MemoryRouter initialEntries={['/orders/new']}>
            <Routes>
              <Route path="/orders/new" element={<CreateOrderPage />} />
              <Route path="/orders/:id/edit" element={<EditOrderPage />} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      );

      await waitFor(() => expect(screen.getByTestId('order-form')).toBeInTheDocument());

      fireEvent.change(screen.getByTestId('order-form-photographer'), { target: { value: 'photo-1' } });
      fireEvent.change(screen.getByTestId('order-form-job-name'), { target: { value: 'New Wedding Shoot' } });

      fireEvent.click(screen.getByTestId('order-form-submit'));

      await waitFor(() => {
        expect(screen.getByTestId('edit-order-page')).toBeInTheDocument();
      });
    });
  });

  describe('EditOrderPage', () => {
    it('loads existing order data and submits an update', async () => {
      vi.spyOn(ordersApi, 'getById').mockResolvedValue(mockOrders[0]);
      vi.spyOn(ordersLookupApi, 'listPhotographers').mockResolvedValue(mockPhotographers);
      vi.spyOn(ordersLookupApi, 'listActiveProducts').mockResolvedValue(mockProducts);
      const updateSpy = vi.spyOn(ordersApi, 'update').mockResolvedValue({ ...mockOrders[0], job_name: 'Updated Job' });
      loginAs(['orders:view', 'orders:update']);

      renderWithProviders(
        <Routes>
          <Route path="/orders/:id/edit" element={<EditOrderPage />} />
        </Routes>,
        ['/orders/order-1/edit']
      );

      await waitFor(() => expect(screen.getByTestId('order-form')).toBeInTheDocument());

      const jobNameInput = screen.getByTestId('order-form-job-name') as HTMLInputElement;
      expect(jobNameInput.value).toBe('Wedding Event');

      fireEvent.change(jobNameInput, { target: { value: 'Updated Job' } });
      fireEvent.click(screen.getByTestId('order-form-submit'));

      await waitFor(() => {
        expect(updateSpy).toHaveBeenCalledWith(
          'order-1',
          expect.objectContaining({ job_name: 'Updated Job', version: 1 })
        );
      });
    });

    it('opens the AddItemDialog and adds an item to the order', async () => {
      vi.spyOn(ordersApi, 'getById').mockResolvedValue(mockOrders[1]);
      vi.spyOn(ordersLookupApi, 'listPhotographers').mockResolvedValue(mockPhotographers);
      vi.spyOn(ordersLookupApi, 'listActiveProducts').mockResolvedValue(mockProducts);
      const addItemSpy = vi.spyOn(ordersApi, 'addItem').mockResolvedValue(mockOrders[0].items[0]);
      loginAs(['orders:view', 'orders:update']);

      renderWithProviders(
        <Routes>
          <Route path="/orders/:id/edit" element={<EditOrderPage />} />
        </Routes>,
        ['/orders/order-2/edit']
      );

      await waitFor(() => expect(screen.getByTestId('order-form')).toBeInTheDocument());

      fireEvent.click(screen.getByTestId('order-item-add-btn'));

      const dialog = await screen.findByTestId('add-item-dialog');
      fireEvent.focus(within(dialog).getByTestId('product-selector-search'));
      fireEvent.click(await within(dialog).findByTestId('product-selector-option-product-1'));
      fireEvent.click(within(dialog).getByTestId('add-item-submit'));

      await waitFor(() => {
        expect(addItemSpy).toHaveBeenCalledWith(
          'order-2',
          expect.objectContaining({ product_id: 'product-1', quantity: 1 })
        );
      });
    });
  });

  describe('OrderDetailsPage', () => {
    it('renders order summary, items and hides edit/delete without permission', async () => {
      vi.spyOn(ordersApi, 'getById').mockResolvedValue(mockOrders[0]);
      vi.spyOn(ordersLookupApi, 'listPhotographers').mockResolvedValue(mockPhotographers);
      loginAs(['orders:view']);

      renderWithProviders(
        <Routes>
          <Route path="/orders/:id" element={<OrderDetailsPage />} />
        </Routes>,
        ['/orders/order-1']
      );

      await waitFor(() => expect(screen.getByTestId('order-details-page')).toBeInTheDocument());

      expect(screen.getByTestId('order-summary-card')).toBeInTheDocument();
      expect(screen.getAllByText('ORD-2026-000001').length).toBeGreaterThan(0);
      expect(screen.getByText('Premium Album')).toBeInTheDocument();
      expect(screen.queryByTestId('order-details-edit-btn')).toBeNull();
      expect(screen.queryByTestId('order-details-delete-btn')).toBeNull();
    });
  });
});
