import { NumberInput } from '../../../components/ui/NumberInput';

interface QuantityEditorProps {
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
  error?: string;
  label?: string;
  fullWidth?: boolean;
  className?: string;
  'data-testid'?: string;
}

// Backend enforces quantity as an integer >= 1 (app/schemas/order_item.py validate_quantity).
// Coerce any decrement below 1 or fractional input back to a valid whole number here so the
// UI can never even attempt to submit an invalid quantity.
export const QuantityEditor = ({
  value,
  onChange,
  disabled,
  error,
  label,
  fullWidth,
  className,
  ...rest
}: QuantityEditorProps) => (
  <NumberInput
    label={label}
    value={value}
    min={1}
    step={1}
    disabled={disabled}
    error={error}
    fullWidth={fullWidth}
    className={className}
    onChange={(next) => onChange(next !== null ? Math.max(1, Math.round(next)) : 1)}
    {...rest}
  />
);
