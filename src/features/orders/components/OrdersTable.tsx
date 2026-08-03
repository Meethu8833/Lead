import * as React from 'react';
import { ColumnDef, DataTable } from '../../../components/ui/DataTable';
import { Button } from '../../../components/ui/Button';
import { EmptyState } from '../../../components/ui/EmptyState';
import { formatCurrency, formatDate } from '../../../utils/helpers';
import { Order, Photographer } from '../types';
import { OrderStatusBadge, PaymentStatusBadge, ProductionStageBadge } from './OrderStatusBadge';
import { Eye, Pencil, Trash2, PackageSearch } from 'lucide-react';

interface OrdersTableProps {
  orders: Order[];
  photographers: Photographer[];
  loading: boolean;
  sorting: { key: string; direction: 'asc' | 'desc' };
  onSort: (key: string, direction: 'asc' | 'desc') => void;
  pagination: {
    page: number;
    pageSize: number;
    totalItems: number;
    onPageChange: (page: number) => void;
    onPageSizeChange?: (size: number) => void;
  };
  onView: (order: Order) => void;
  onEdit: (order: Order) => void;
  onDelete: (order: Order) => void;
  canUpdate: boolean;
  canDelete: boolean;
}

export const OrdersTable = ({
  orders,
  photographers,
  loading,
  sorting,
  onSort,
  pagination,
  onView,
  onEdit,
  onDelete,
  canUpdate,
  canDelete,
}: OrdersTableProps) => {
  const photographerMap = React.useMemo(() => {
    const map = new Map<string, Photographer>();
    photographers.forEach((p) => map.set(p.id, p));
    return map;
  }, [photographers]);

  const columns: ColumnDef<Order>[] = [
    {
      header: 'Order Number',
      accessorKey: 'order_number',
      sortable: true,
      className: 'font-semibold text-primary whitespace-nowrap',
    },
    {
      header: 'Booking Date',
      accessorKey: 'booking_date',
      sortable: true,
      cell: (val) => formatDate(val as string),
      className: 'whitespace-nowrap',
    },
    {
      header: 'Photographer / Customer',
      accessorKey: 'photographer_id',
      sortable: true,
      cell: (_, row) => {
        const photographer = photographerMap.get(row.photographer_id);
        if (!photographer) return <span className="text-muted-foreground">Unknown</span>;
        return (
          <div className="flex flex-col">
            <span className="font-medium text-foreground">{photographer.name}</span>
            <span className="text-xs text-muted-foreground">{photographer.studio_name}</span>
          </div>
        );
      },
    },
    {
      header: 'Status',
      accessorKey: 'status',
      sortable: true,
      cell: (val) => <OrderStatusBadge status={val} />,
    },
    {
      header: 'Production Stage',
      accessorKey: 'status',
      cell: (val) => <ProductionStageBadge status={val} />,
    },
    {
      header: 'Payment Status',
      accessorKey: 'payment_status',
      sortable: true,
      cell: (val) => <PaymentStatusBadge status={val} />,
    },
    {
      header: 'Expected Delivery',
      accessorKey: 'expected_delivery_date',
      sortable: true,
      cell: (val) => formatDate(val as string),
      className: 'whitespace-nowrap',
    },
    {
      header: 'Grand Total',
      accessorKey: 'total_amount',
      sortable: true,
      cell: (val) => <span className="font-medium">{formatCurrency(Number(val))}</span>,
    },
    {
      header: 'Balance',
      accessorKey: 'balance_amount',
      sortable: true,
      cell: (val) => {
        const numVal = Number(val);
        return (
          <span className={numVal > 0 ? 'font-medium text-destructive' : 'font-medium text-emerald-600 dark:text-emerald-500'}>
            {formatCurrency(numVal)}
          </span>
        );
      },
    },
    {
      header: 'Actions',
      className: 'text-right',
      cell: (_, row) => (
        <div className="flex items-center justify-end gap-1">
          <Button
            variant="ghost"
            size="sm"
            leftIcon={<Eye className="h-4 w-4" />}
            onClick={(e) => {
              e.stopPropagation();
              onView(row);
            }}
            data-testid={`order-view-btn-${row.order_number}`}
          >
            View
          </Button>
          {canUpdate && (
            <Button
              variant="ghost"
              size="sm"
              leftIcon={<Pencil className="h-4 w-4" />}
              onClick={(e) => {
                e.stopPropagation();
                onEdit(row);
              }}
              data-testid={`order-edit-btn-${row.order_number}`}
            >
              Edit
            </Button>
          )}
          {canDelete && (
            <Button
              variant="ghost"
              size="sm"
              leftIcon={<Trash2 className="h-4 w-4" />}
              onClick={(e) => {
                e.stopPropagation();
                onDelete(row);
              }}
              data-testid={`order-delete-btn-${row.order_number}`}
            >
              Delete
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div data-testid="orders-table">
      <DataTable
        columns={columns}
        data={orders}
        loading={loading}
        sorting={sorting}
        onSort={onSort}
        pagination={pagination}
        onRowClick={onView}
        stickyHeader
        emptyComponent={
          <EmptyState
            icon={<PackageSearch className="h-6 w-6" />}
            title="No orders found"
            description="No orders match the current filters. Try clearing filters or create a new order."
          />
        }
        className="w-full"
      />
    </div>
  );
};
