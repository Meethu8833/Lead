import { ColumnDef, DataTable } from '../../../components/ui/DataTable';
import { StatusBadge } from '../../../components/ui/StatusBadge';
import { Badge } from '../../../components/ui/Badge';
import { Button } from '../../../components/ui/Button';
import { formatCurrency, formatDate } from '../../../utils/helpers';
import { Order, Photographer } from '../types';
import { Eye } from 'lucide-react';
import * as React from 'react';

interface RecentOrdersTableProps {
  orders: Order[];
  photographers: Photographer[];
  loading: boolean;
  onViewOrder?: (order: Order) => void;
}

export const RecentOrdersTable = ({
  orders,
  photographers,
  loading,
  onViewOrder,
}: RecentOrdersTableProps) => {
  // Create a fast lookup map for photographers
  const photographerMap = React.useMemo(() => {
    const map = new Map<string, Photographer>();
    photographers.forEach((p) => map.set(p.id, p));
    return map;
  }, [photographers]);

  // Client-side pagination state
  const [page, setPage] = React.useState(1);
  const [pageSize, setPageSize] = React.useState(5);

  // Client-side sorting state
  const [sorting, setSorting] = React.useState<{
    key: string;
    direction: 'asc' | 'desc';
  }>({
    key: 'booking_date',
    direction: 'desc',
  });

  const columns: ColumnDef<Order>[] = [
    {
      header: 'Order Number',
      accessorKey: 'order_number',
      sortable: true,
      className: 'font-semibold text-primary',
    },
    {
      header: 'Photographer',
      accessorKey: 'photographer_id',
      sortable: true,
      cell: (_, row) => {
        const photographer = photographerMap.get(row.photographer_id);
        return photographer ? photographer.name : 'Unknown';
      },
    },
    {
      header: 'Customer (Studio)',
      accessorKey: 'photographer_id',
      sortable: true,
      cell: (_, row) => {
        const photographer = photographerMap.get(row.photographer_id);
        return photographer ? photographer.studio_name : 'Unknown';
      },
    },
    {
      header: 'Status',
      accessorKey: 'status',
      sortable: true,
      cell: (val) => {
        const statusStr = String(val).toLowerCase();
        // Map order status to status badge standard
        let badgeStatus = 'pending';
        if (statusStr === 'delivered') badgeStatus = 'completed';
        if (statusStr === 'cancelled') badgeStatus = 'cancelled';
        if (statusStr === 'ready') badgeStatus = 'approved';
        if (['printing', 'lamination', 'designing', 'editing', 'color_correction', 'packing', 'quality_check'].includes(statusStr)) {
          badgeStatus = 'processing';
        }
        return <StatusBadge status={badgeStatus}>{String(val)}</StatusBadge>;
      },
    },
    {
      header: 'Production Stage',
      accessorKey: 'status',
      sortable: true,
      cell: (val) => {
        return (
          <Badge variant="secondary" className="capitalize">
            {String(val).replace('_', ' ').toLowerCase()}
          </Badge>
        );
      },
    },
    {
      header: 'Payment Status',
      accessorKey: 'payment_status',
      sortable: true,
      cell: (val) => {
        const payStatus = String(val).toUpperCase();
        let badgeVariant: 'warning' | 'success' | 'danger' | 'info' | 'secondary' = 'warning';
        if (payStatus === 'FULLY_PAID') badgeVariant = 'success';
        if (payStatus === 'PARTIALLY_PAID') badgeVariant = 'info';
        if (payStatus === 'OVERPAID') badgeVariant = 'success';
        if (payStatus === 'PENDING') badgeVariant = 'warning';

        return (
          <Badge variant={badgeVariant} className="capitalize">
            {payStatus.replace('_', ' ').toLowerCase()}
          </Badge>
        );
      },
    },
    {
      header: 'Expected Delivery',
      accessorKey: 'expected_delivery_date',
      sortable: true,
      cell: (val) => formatDate(val as string),
    },
    {
      header: 'Balance',
      accessorKey: 'balance_amount',
      sortable: true,
      cell: (val) => (
        <span className="font-medium text-foreground">
          {formatCurrency(Number(val))}
        </span>
      ),
    },
    {
      header: 'Actions',
      cell: (_, row) => (
        <Button
          variant="ghost"
          size="sm"
          leftIcon={<Eye className="h-4 w-4" />}
          onClick={() => onViewOrder && onViewOrder(row)}
          data-testid={`view-order-btn-${row.order_number}`}
        >
          View
        </Button>
      ),
    },
  ];

  // Sorting Handler
  const handleSort = (key: string, direction: 'asc' | 'desc') => {
    setSorting({ key, direction });
  };

  // Sort and Paginate data
  const processedData = React.useMemo(() => {
    let result = [...orders];

    // Apply sorting
    const key = sorting.key;
    const dir = sorting.direction;
    result.sort((a: any, b: any) => {
      let aVal = a[key];
      let bVal = b[key];

      // Resolve photographer properties if sorted by them
      if (key === 'photographer_id') {
        const photoA = photographerMap.get(a.photographer_id)?.name || '';
        const photoB = photographerMap.get(b.photographer_id)?.name || '';
        aVal = photoA;
        bVal = photoB;
      }

      if (aVal === bVal) return 0;
      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;

      const modifier = dir === 'asc' ? 1 : -1;
      if (typeof aVal === 'string' && typeof bVal === 'string') {
        return aVal.localeCompare(bVal) * modifier;
      }
      return (aVal < bVal ? -1 : 1) * modifier;
    });

    return result;
  }, [orders, sorting, photographerMap]);

  // Paginated chunk
  const paginatedData = React.useMemo(() => {
    const start = (page - 1) * pageSize;
    return processedData.slice(start, start + pageSize);
  }, [processedData, page, pageSize]);

  return (
    <div data-testid="recent-orders-table">
      <DataTable
        columns={columns}
        data={paginatedData}
        loading={loading}
        sorting={sorting}
        onSort={handleSort}
        pagination={{
          page,
          pageSize,
          totalItems: processedData.length,
          onPageChange: setPage,
          onPageSizeChange: setPageSize,
        }}
        className="w-full"
      />
    </div>
  );
};
