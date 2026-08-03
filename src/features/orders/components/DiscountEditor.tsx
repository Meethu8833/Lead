import { CurrencyInput } from '../../../components/ui/CurrencyInput';
import { formatCurrency } from '../../../utils/helpers';

interface DiscountEditorProps {
  value: number;
  max: number;
  onChange: (value: number) => void;
  disabled?: boolean;
  error?: string;
  fullWidth?: boolean;
  'data-testid'?: string;
}

// Flat currency discount only — the backend has no percentage-discount concept
// (app/models/order_item.py: `discount` is a flat Numeric column), and the only server-side
// limit is "discount cannot exceed the gross item amount" (unit_price * quantity). `max` is
// surfaced here purely as a client-side hint/validation so the user isn't surprised by a 400
// on save.
export const DiscountEditor = ({
  value,
  max,
  onChange,
  disabled,
  error,
  fullWidth = true,
  ...rest
}: DiscountEditorProps) => {
  const exceedsMax = value > max;

  return (
    <CurrencyInput
      label="Discount"
      value={value}
      onChangeValue={(next) => onChange(next ?? 0)}
      disabled={disabled}
      fullWidth={fullWidth}
      error={error || (exceedsMax ? `Discount cannot exceed ${formatCurrency(max)} (the item's gross amount).` : undefined)}
      helperText={!error && !exceedsMax ? `Maximum discount: ${formatCurrency(max)}` : undefined}
      {...rest}
    />
  );
};
