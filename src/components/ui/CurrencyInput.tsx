import * as React from 'react';
import { Input } from './Input';
import { cn } from '../../utils/cn';

export interface CurrencyInputProps
  extends Omit<
    React.InputHTMLAttributes<HTMLInputElement>,
    'value' | 'defaultValue' | 'onChange' | 'prefix'
  > {
  value?: number | null;
  defaultValue?: number;
  currency?: string;
  locale?: string;
  onChangeValue?: (value: number | null) => void;
  label?: string;
  error?: string;
  helperText?: string;
  fullWidth?: boolean;
}

const getCurrencySymbol = (locale: string, currency: string) => {
  try {
    const formatter = new Intl.NumberFormat(locale, {
      style: 'currency',
      currency,
    });
    const parts = formatter.formatToParts(0);
    const symbolPart = parts.find((part) => part.type === 'currency');
    return symbolPart ? symbolPart.value : '';
  } catch {
    return currency === 'INR' ? '₹' : currency === 'USD' ? '$' : currency;
  }
};

export const CurrencyInput = React.forwardRef<HTMLInputElement, CurrencyInputProps>(
  (
    {
      className,
      value,
      defaultValue,
      onChangeValue,
      currency = 'INR',
      locale = 'en-IN',
      ...props
    },
    ref
  ) => {
    const [isFocused, setIsFocused] = React.useState(false);
    const [rawVal, setRawVal] = React.useState<number | null>(
      value !== undefined
        ? value
        : defaultValue !== undefined
        ? defaultValue
        : null
    );
    const [inputValue, setInputValue] = React.useState('');

    const symbol = getCurrencySymbol(locale, currency);

    // Format utility
    const formatNumber = React.useCallback(
      (val: number | null): string => {
        if (val === null || isNaN(val)) return '';
        try {
          return new Intl.NumberFormat(locale, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          }).format(val);
        } catch {
          return val.toFixed(2);
        }
      },
      [locale]
    );

    // Sync state with value from prop
    React.useEffect(() => {
      if (value !== undefined) {
        setRawVal(value);
        if (!isFocused) {
          setInputValue(formatNumber(value));
        }
      }
    }, [value, isFocused, formatNumber]);

    // Initial input value binding if uncontrolled
    React.useEffect(() => {
      if (value === undefined && defaultValue !== undefined) {
        setInputValue(formatNumber(defaultValue));
      }
    }, [defaultValue, value, formatNumber]);

    const handleFocus = (e: React.FocusEvent<HTMLInputElement>) => {
      setIsFocused(true);
      // When focused, display raw float numeric value for editing
      setInputValue(rawVal !== null ? String(rawVal) : '');
      if (props.onFocus) {
        props.onFocus(e);
      }
    };

    const handleBlur = (e: React.FocusEvent<HTMLInputElement>) => {
      setIsFocused(false);
      // When blurred, display formatted string
      setInputValue(formatNumber(rawVal));
      if (props.onBlur) {
        props.onBlur(e);
      }
    };

    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      const inputStr = e.target.value;
      setInputValue(inputStr);

      // Strip all characters except digits, minus, and decimal points
      const stripped = inputStr.replace(/[^0-9.-]/g, '');
      const parsed = parseFloat(stripped);

      if (inputStr === '' || isNaN(parsed)) {
        setRawVal(null);
        onChangeValue?.(null);
      } else {
        setRawVal(parsed);
        onChangeValue?.(parsed);
      }
    };

    return (
      <Input
        ref={ref}
        type={isFocused ? 'number' : 'text'}
        step="any"
        value={inputValue}
        prefix={
          <span className="text-sm font-medium text-muted-foreground select-none" data-testid="currency-symbol">
            {symbol}
          </span>
        }
        onChange={handleChange}
        onFocus={handleFocus}
        onBlur={handleBlur}
        className={cn('[appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none', className)}
        {...props}
      />
    );
  }
);

CurrencyInput.displayName = 'CurrencyInput';
