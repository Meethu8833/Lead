import { formatCurrency } from '../../../utils/helpers';

interface PriceSummaryProps {
  unitPrice: number;
  quantity: number;
  discount: number;
}

// Compact single-line live preview used while a new item is being built (AddItemDialog) —
// recalculates on every keystroke as product/quantity/price/discount change.
export const PriceSummary = ({ unitPrice, quantity, discount }: PriceSummaryProps) => {
  const subtotal = Math.max(0, unitPrice * quantity - discount);

  return (
    <div
      className="flex items-center justify-between rounded-md bg-primary/5 px-3 py-2"
      data-testid="price-summary"
    >
      <span className="text-sm font-medium text-muted-foreground">Item Subtotal</span>
      <span className="text-base font-bold text-foreground" data-testid="price-summary-subtotal">
        {formatCurrency(subtotal)}
      </span>
    </div>
  );
};
