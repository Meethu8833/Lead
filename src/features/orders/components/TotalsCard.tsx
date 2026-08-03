import * as React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../../../components/ui/Card';
import { formatCurrency } from '../../../utils/helpers';
import { OrderItem } from '../types';

export interface OrderItemTotals {
  itemsCount: number;
  totalQuantity: number;
  grossSubtotal: number;
  discountTotal: number;
  netTotal: number;
}

// Recomputed client-side from the live items array (unit_price * quantity - discount per item,
// same formula as app/services/order_item.py) rather than trusting each item's server-returned
// `subtotal` field, so the totals recalculate the instant a quantity/price/discount/product
// change is optimistically applied to the cache — no need to wait for the server round-trip.
export const computeOrderItemTotals = (items: OrderItem[]): OrderItemTotals => {
  let grossSubtotal = 0;
  let discountTotal = 0;
  let totalQuantity = 0;

  items.forEach((item) => {
    grossSubtotal += item.unit_price * item.quantity;
    discountTotal += item.discount;
    totalQuantity += item.quantity;
  });

  return {
    itemsCount: items.length,
    totalQuantity,
    grossSubtotal,
    discountTotal,
    netTotal: Math.max(0, grossSubtotal - discountTotal),
  };
};

const Stat = ({ label, value, emphasis }: { label: string; value: React.ReactNode; emphasis?: boolean }) => (
  <div className="flex flex-col gap-0.5">
    <span className="text-xs font-medium text-muted-foreground">{label}</span>
    <span className={emphasis ? 'text-lg font-bold text-foreground' : 'text-sm font-semibold text-foreground'}>
      {value}
    </span>
  </div>
);

interface TotalsCardProps {
  items: OrderItem[];
  advancePaid: number;
}

export const TotalsCard = ({ items, advancePaid }: TotalsCardProps) => {
  const totals = computeOrderItemTotals(items);
  const balancePreview = totals.netTotal - advancePaid;

  return (
    <Card data-testid="totals-card">
      <CardHeader>
        <CardTitle className="text-lg">Totals (Live Preview)</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Stat label="Items" value={totals.itemsCount} />
        <Stat label="Quantity" value={totals.totalQuantity} />
        <Stat label="Subtotal" value={formatCurrency(totals.grossSubtotal)} />
        <Stat label="Discount" value={`- ${formatCurrency(totals.discountTotal)}`} />
        <Stat label="Grand Total" value={formatCurrency(totals.netTotal)} emphasis />
        <Stat label="Advance Paid" value={formatCurrency(advancePaid)} />
        <Stat
          label="Balance Preview"
          value={
            <span
              className={
                balancePreview > 0
                  ? 'text-destructive font-bold'
                  : 'text-emerald-600 dark:text-emerald-500 font-bold'
              }
              data-testid="totals-card-balance-preview"
            >
              {formatCurrency(balancePreview)}
            </span>
          }
        />
      </CardContent>
    </Card>
  );
};
