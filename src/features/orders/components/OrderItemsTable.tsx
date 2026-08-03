import * as React from 'react';
import { ColumnDef, DataTable } from '../../../components/ui/DataTable';
import { Button } from '../../../components/ui/Button';
import { Badge } from '../../../components/ui/Badge';
import { EmptyState } from '../../../components/ui/EmptyState';
import { useAuthStore } from '../../../app/store';
import { checkPermission } from '../../../components/auth/PermissionGuard';
import { formatCurrency } from '../../../utils/helpers';
import { OrderItem, isProductionStageLocked } from '../types';
import { QuantityEditor } from './QuantityEditor';
import { CurrencyInput } from '../../../components/ui/CurrencyInput';
import { Plus, Trash2, PackagePlus, Pencil, Copy, Lock, History } from 'lucide-react';

interface OrderItemsTableProps {
  items: OrderItem[];
  editable: boolean;
  onAddItem: () => void;
  onRemoveItem: (item: OrderItem) => void;
  onUpdateQuantity: (item: OrderItem, quantity: number) => void;
  onUpdateUnitPrice: (item: OrderItem, unitPrice: number) => void;
  onEditItem?: (item: OrderItem) => void;
  onDuplicateItem?: (item: OrderItem) => void;
  isMutating?: boolean;
}

export const OrderItemsTable = ({
  items,
  editable,
  onAddItem,
  onRemoveItem,
  onUpdateQuantity,
  onUpdateUnitPrice,
  onEditItem,
  onDuplicateItem,
  isMutating = false,
}: OrderItemsTableProps) => {
  // Defense in depth: even if a parent passes editable=true, this component re-checks
  // orders:update itself so item editing can never be enabled for a user who lacks permission.
  const { permissions, user } = useAuthStore();
  const canUpdate = checkPermission(permissions, 'orders:update', user?.role?.name);
  const isEditable = editable && canUpdate;

  const grandTotal = React.useMemo(
    () => items.reduce((sum, item) => sum + Number(item.subtotal), 0),
    [items]
  );

  const columns: ColumnDef<OrderItem>[] = [
    {
      header: 'Product',
      accessorKey: 'product_name',
      cell: (_, row) => (
        <div className="flex flex-col">
          <div className="flex items-center gap-1.5">
            <span className="font-medium text-foreground">{row.product_name}</span>
            <span
              title="Product name, category and price were captured when this item was added and won't change even if the catalog product is later edited or removed."
              data-testid={`order-item-snapshot-indicator-${row.id}`}
            >
              <History className="h-3.5 w-3.5 text-muted-foreground" />
            </span>
          </div>
          <span className="text-xs text-muted-foreground">{row.product_category}</span>
        </div>
      ),
    },
    {
      header: 'Quantity',
      accessorKey: 'quantity',
      cell: (val, row) => {
        const locked = isProductionStageLocked(row.production_stage);
        return isEditable ? (
          <QuantityEditor
            value={Number(val)}
            onChange={(next) => onUpdateQuantity(row, next)}
            disabled={isMutating || locked}
            className="w-24 h-9"
            data-testid={`order-item-quantity-${row.id}`}
          />
        ) : (
          <span>{String(val)}</span>
        );
      },
    },
    {
      header: 'Unit Price',
      accessorKey: 'unit_price',
      cell: (val, row) => {
        const locked = isProductionStageLocked(row.production_stage);
        return isEditable ? (
          <CurrencyInput
            value={Number(val)}
            onChangeValue={(next) => next !== null && onUpdateUnitPrice(row, next)}
            disabled={isMutating || locked}
            className="w-32 h-9"
            data-testid={`order-item-unit-price-${row.id}`}
          />
        ) : (
          <span>{formatCurrency(Number(val))}</span>
        );
      },
    },
    {
      header: 'Discount',
      accessorKey: 'discount',
      cell: (val) => <span>{formatCurrency(Number(val))}</span>,
    },
    {
      header: 'Subtotal',
      accessorKey: 'subtotal',
      cell: (val) => <span className="font-semibold text-foreground">{formatCurrency(Number(val))}</span>,
    },
    ...(isEditable
      ? [
          {
            header: 'Status',
            className: 'text-center',
            cell: (_: any, row: OrderItem) =>
              isProductionStageLocked(row.production_stage) ? (
                <Badge
                  variant="warning"
                  size="sm"
                  className="inline-flex items-center gap-1"
                  data-testid={`order-item-locked-badge-${row.id}`}
                >
                  <Lock className="h-3 w-3" /> Locked
                </Badge>
              ) : null,
          } as ColumnDef<OrderItem>,
          {
            header: 'Actions',
            className: 'text-right',
            cell: (_: any, row: OrderItem) => {
              const locked = isProductionStageLocked(row.production_stage);
              return (
                <div className="flex items-center justify-end gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    leftIcon={<Pencil className="h-4 w-4" />}
                    onClick={() => onEditItem?.(row)}
                    disabled={isMutating || locked}
                    title={locked ? 'This item is locked once it reaches the Packing stage.' : undefined}
                    data-testid={`order-item-edit-${row.id}`}
                  >
                    Edit
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    leftIcon={<Copy className="h-4 w-4" />}
                    onClick={() => onDuplicateItem?.(row)}
                    disabled={isMutating}
                    data-testid={`order-item-duplicate-${row.id}`}
                  >
                    Duplicate
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    leftIcon={<Trash2 className="h-4 w-4" />}
                    onClick={() => onRemoveItem(row)}
                    disabled={isMutating || locked}
                    title={locked ? 'This item is locked once it reaches the Packing stage.' : undefined}
                    data-testid={`order-item-remove-${row.id}`}
                  >
                    Remove
                  </Button>
                </div>
              );
            },
          } as ColumnDef<OrderItem>,
        ]
      : []),
  ];

  return (
    <div className="space-y-3" data-testid="order-items-table">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">Order Items</h3>
        {isEditable && (
          <Button
            variant="outline"
            size="sm"
            leftIcon={<Plus className="h-4 w-4" />}
            onClick={onAddItem}
            data-testid="order-item-add-btn"
          >
            Add Item
          </Button>
        )}
      </div>

      <DataTable
        columns={columns}
        data={items}
        getRowId={(row) => row.id}
        emptyComponent={
          <EmptyState
            icon={<PackagePlus className="h-6 w-6" />}
            title="No items yet"
            description={
              isEditable
                ? 'Add a product to start building this order.'
                : 'This order has no items.'
            }
          />
        }
      />

      <div className="flex justify-end border-t border-border pt-3">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-muted-foreground">Grand Total</span>
          <span className="text-lg font-bold text-foreground" data-testid="order-items-grand-total">
            {formatCurrency(grandTotal)}
          </span>
        </div>
      </div>
    </div>
  );
};
