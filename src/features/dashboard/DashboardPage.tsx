import * as React from 'react';
import { useAuthStore } from '../../app/store';
import { checkPermission } from '../../components/auth/PermissionGuard';
import { PageContainer, PageHeader } from '../../components/ui/LayoutHelpers';
import { ErrorState } from '../../components/ui/ErrorState';
import {
  useDashboardStats,
  useDashboardOrders,
  useDashboardPhotographers,
} from './hooks';
import { DashboardFilters } from './components/DashboardFilters';
import { DashboardSkeleton } from './components/DashboardSkeleton';
import { RevenueCards } from './components/RevenueCards';
import { ProductionOverview } from './components/ProductionOverview';
import { RecentOrdersTable } from './components/RecentOrdersTable';
import { TopCustomers } from './components/TopCustomers';
import { TopProducts } from './components/TopProducts';
import { DelayedOrders } from './components/DelayedOrders';
import { RevenueChart } from './components/RevenueChart';
import { OrderStatusChart } from './components/OrderStatusChart';
import { DashboardFiltersState } from './types';
import dayjs from 'dayjs';

export const DashboardPage = () => {
  const { permissions, user } = useAuthStore();

  // RBAC Checks for subcomponents
  const hasReportsView = checkPermission(permissions, 'reports:view', user?.role?.name);
  const hasOrdersView = checkPermission(permissions, 'orders:view', user?.role?.name);
  const hasPaymentsView = checkPermission(permissions, 'payments:view', user?.role?.name);

  // Queries
  const statsQuery = useDashboardStats();
  const ordersQuery = useDashboardOrders();
  const photographersQuery = useDashboardPhotographers();

  // Filters State
  const [filters, setFilters] = React.useState<DashboardFiltersState>({
    dateRange: 'month',
  });

  const isLoading =
    statsQuery.isLoading ||
    ordersQuery.isLoading ||
    photographersQuery.isLoading;

  const isError =
    statsQuery.isError ||
    ordersQuery.isError ||
    photographersQuery.isError;

  const isRefetching =
    statsQuery.isRefetching ||
    ordersQuery.isRefetching ||
    photographersQuery.isRefetching;

  const handleRefresh = async () => {
    await Promise.all([
      statsQuery.refetch(),
      ordersQuery.refetch(),
      photographersQuery.refetch(),
    ]);
  };

  const handleRetry = () => {
    statsQuery.refetch();
    ordersQuery.refetch();
    photographersQuery.refetch();
  };

  // Filter orders in memory based on current filters
  const filteredOrders = React.useMemo(() => {
    if (!ordersQuery.data) return [];

    return ordersQuery.data.filter((order) => {
      const bookingDate = dayjs(order.booking_date);
      const now = dayjs();

      if (filters.dateRange === 'today') {
        return bookingDate.isSame(now, 'day');
      }
      if (filters.dateRange === 'week') {
        const startOfWeek = now.subtract(7, 'day').startOf('day');
        return bookingDate.isAfter(startOfWeek) || bookingDate.isSame(startOfWeek);
      }
      if (filters.dateRange === 'month') {
        const startOfMonth = now.subtract(30, 'day').startOf('day');
        return bookingDate.isAfter(startOfMonth) || bookingDate.isSame(startOfMonth);
      }
      if (filters.dateRange === 'custom') {
        let isAfterStart = true;
        let isBeforeEnd = true;

        if (filters.startDate) {
          const start = dayjs(filters.startDate).startOf('day');
          isAfterStart = bookingDate.isAfter(start) || bookingDate.isSame(start);
        }
        if (filters.endDate) {
          const end = dayjs(filters.endDate).endOf('day');
          isBeforeEnd = bookingDate.isBefore(end) || bookingDate.isSame(end);
        }

        return isAfterStart && isBeforeEnd;
      }

      return true;
    });
  }, [ordersQuery.data, filters]);

  const activeCustomersCount = React.useMemo(() => {
    if (!photographersQuery.data) return 0;
    return photographersQuery.data.filter((p) => p.is_active).length;
  }, [photographersQuery.data]);

  if (isLoading) {
    return <DashboardSkeleton />;
  }

  if (isError) {
    return (
      <PageContainer className="flex items-center justify-center min-h-[50vh]">
        <ErrorState
          title="Failed to load dashboard"
          description="There was a problem communicating with the server. Please check your network connection and try again."
          onRetry={handleRetry}
        />
      </PageContainer>
    );
  }

  const stats = statsQuery.data;
  const photographers = photographersQuery.data || [];

  return (
    <PageContainer className="space-y-6" data-testid="dashboard-page">
      <PageHeader
        title="Business Dashboard"
        description="Monitor real-time business performance, production queues, and revenues."
        actions={
          <DashboardFilters
            filters={filters}
            onFilterChange={setFilters}
            onRefresh={handleRefresh}
            isRefreshing={isRefetching}
          />
        }
      />

      {/* Revenue KPI Cards */}
      {hasPaymentsView && stats && (
        <RevenueCards stats={stats} loading={isRefetching} />
      )}

      {/* Operations Overview KPIs */}
      {hasOrdersView && stats && (
        <ProductionOverview
          stats={stats}
          activeCustomersCount={activeCustomersCount}
          loading={isRefetching}
        />
      )}

      {/* Charts Row */}
      {hasReportsView && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {hasPaymentsView && (
            <div className="lg:col-span-2">
              <RevenueChart orders={filteredOrders} filters={filters} />
            </div>
          )}
          {hasOrdersView && (
            <div className={hasPaymentsView ? '' : 'lg:col-span-3'}>
              <OrderStatusChart orders={filteredOrders} />
            </div>
          )}
        </div>
      )}

      {/* Primary Details Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {hasOrdersView && (
          <div className="lg:col-span-2 flex flex-col gap-6">
            <h2 className="text-xl font-bold tracking-tight text-foreground select-none">
              Recent Orders
            </h2>
            <RecentOrdersTable
              orders={filteredOrders}
              photographers={photographers}
              loading={isRefetching}
            />
          </div>
        )}

        <div className="flex flex-col gap-6">
          {hasOrdersView && (
            <DelayedOrders orders={ordersQuery.data || []} photographers={photographers} />
          )}
        </div>
      </div>

      {/* Secondary Metrics Row */}
      {hasReportsView && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {hasPaymentsView && stats && (
            <TopCustomers
              topCustomers={stats.top_customers}
              orders={ordersQuery.data || []}
              photographers={photographers}
            />
          )}
          {hasOrdersView && stats && (
            <TopProducts topProducts={stats.top_products} orders={ordersQuery.data || []} />
          )}
        </div>
      )}
    </PageContainer>
  );
};
