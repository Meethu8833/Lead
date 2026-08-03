import { formatCurrency } from '../../../utils/helpers';

interface PriceBreakdownProps {
  unitPrice: number;
  quantity: number;
  discount: number;
}

// Itemized math for a single line item, mirroring the backend formula exactly
// (app/services/order_item.py: subtotal = unit_price * quantity - discount).
export const PriceBreakdown = ({ unitPrice, quantity, discount }: PriceBreakdownProps) => {
  const gross = unitPrice * quantity;
  const subtotal = Math.max(0, gross - discount);

  return (
    <div
      className="rounded-md border border-border bg-muted/30 p-3 space-y-1.5 text-sm"
      data-testid="price-breakdown"
    >
      <div className="flex justify-between">
        <span className="text-muted-foreground">Unit Price × Quantity</span>
        <span data-testid="price-breakdown-gross">
          {formatCurrency(unitPrice)} × {quantity} = {formatCurrency(gross)}
        </span>
      </div>
      <div className="flex justify-between">
        <span className="text-muted-foreground">Discount</span>
        <span data-testid="price-breakdown-discount">- {formatCurrency(discount)}</span>
      </div>
      <div className="flex justify-between border-t border-border pt-1.5 font-semibold text-foreground">
        <span>Subtotal</span>
        <span data-testid="price-breakdown-subtotal">{formatCurrency(subtotal)}</span>
      </div>
    </div>
  );
};
