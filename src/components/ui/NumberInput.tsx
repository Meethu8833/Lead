import * as React from 'react';
import { cn } from '../../utils/cn';
import { ChevronUp, ChevronDown } from 'lucide-react';

export interface NumberInputProps
  extends Omit<
    React.InputHTMLAttributes<HTMLInputElement>,
    'onChange' | 'value' | 'defaultValue' | 'type'
  > {
  value?: number | null;
  defaultValue?: number;
  onChange?: (value: number | null) => void;
  label?: string;
  error?: string;
  helperText?: string;
  step?: number;
  min?: number;
  max?: number;
  fullWidth?: boolean;
}

export const NumberInput = React.forwardRef<HTMLInputElement, NumberInputProps>(
  (
    {
      className,
      label,
      error,
      helperText,
      value,
      defaultValue,
      onChange,
      step = 1,
      min,
      max,
      fullWidth = false,
      required,
      disabled,
      id,
      ...props
    },
    ref
  ) => {
    const generatedId = React.useId();
    const inputId = id || generatedId;
    const errorId = `${inputId}-error`;
    const helperId = `${inputId}-helper`;

    const inputRef = React.useRef<HTMLInputElement>(null);
    React.useImperativeHandle(ref, () => inputRef.current!);

    // Handle controlled/uncontrolled state
    const [numValue, setNumValue] = React.useState<number | null>(
      value !== undefined
        ? value
        : defaultValue !== undefined
        ? defaultValue
        : null
    );

    React.useEffect(() => {
      if (value !== undefined) {
        setNumValue(value);
      }
    }, [value]);

    const handleIncrement = () => {
      if (disabled) return;
      const current = numValue !== null ? numValue : (min !== undefined ? min : 0);
      let next = current + step;

      // Handle float precision issues
      next = parseFloat(next.toFixed(10));

      if (max !== undefined && next > max) {
        next = max;
      }
      if (min !== undefined && next < min) {
        next = min;
      }

      setNumValue(next);
      onChange?.(next);
    };

    const handleDecrement = () => {
      if (disabled) return;
      const current = numValue !== null ? numValue : (min !== undefined ? min : 0);
      let next = current - step;

      // Handle float precision issues
      next = parseFloat(next.toFixed(10));

      if (min !== undefined && next < min) {
        next = min;
      }
      if (max !== undefined && next > max) {
        next = max;
      }

      setNumValue(next);
      onChange?.(next);
    };

    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = e.target.value;
      if (val === '') {
        setNumValue(null);
        onChange?.(null);
        return;
      }

      const parsed = parseFloat(val);
      if (!isNaN(parsed)) {
        let bounded = parsed;
        if (min !== undefined && bounded < min) bounded = min;
        if (max !== undefined && bounded > max) bounded = max;

        setNumValue(bounded);
        onChange?.(bounded);
      }
    };

    // Prevent mouse wheel from changing input value accidentally
    const handleWheel = (e: React.WheelEvent<HTMLInputElement>) => {
      e.currentTarget.blur();
    };

    return (
      <div className={cn('flex flex-col gap-1.5', fullWidth ? 'w-full' : 'w-auto')}>
        {label && (
          <label
            htmlFor={inputId}
            className={cn(
              'text-sm font-medium text-foreground select-none',
              disabled && 'opacity-50'
            )}
            data-testid="numberinput-label"
          >
            {label}
            {required && <span className="text-destructive ml-1" data-testid="numberinput-required-star">*</span>}
          </label>
        )}

        <div className="relative flex items-center w-full rounded-md shadow-sm">
          <input
            id={inputId}
            type="number"
            ref={inputRef}
            disabled={disabled}
            step={step}
            min={min}
            max={max}
            value={numValue !== null ? numValue : ''}
            onChange={handleChange}
            onWheel={handleWheel}
            aria-invalid={error ? 'true' : 'false'}
            aria-describedby={
              error ? errorId : helperText ? helperId : undefined
            }
            className={cn(
              'flex h-10 w-full rounded-md border border-input bg-background pl-3 pr-10 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 transition-colors [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none',
              error && 'border-destructive focus-visible:ring-destructive',
              className
            )}
            {...props}
          />

          {/* Increment/Decrement Buttons */}
          <div className="absolute right-0 inset-y-0 flex flex-col border-l border-input select-none" data-testid="numberinput-buttons">
            <button
              type="button"
              tabIndex={-1}
              disabled={disabled || (max !== undefined && numValue !== null && numValue >= max)}
              onClick={handleIncrement}
              className="flex-1 flex items-center justify-center px-2 hover:bg-muted text-muted-foreground hover:text-foreground active:bg-zinc-200 dark:active:bg-zinc-800 disabled:opacity-30 disabled:pointer-events-none transition-colors border-b border-input rounded-tr-md"
              aria-label="Increment value"
              data-testid="numberinput-inc"
            >
              <ChevronUp className="h-3 w-3" />
            </button>
            <button
              type="button"
              tabIndex={-1}
              disabled={disabled || (min !== undefined && numValue !== null && numValue <= min)}
              onClick={handleDecrement}
              className="flex-1 flex items-center justify-center px-2 hover:bg-muted text-muted-foreground hover:text-foreground active:bg-zinc-200 dark:active:bg-zinc-800 disabled:opacity-30 disabled:pointer-events-none transition-colors rounded-br-md"
              aria-label="Decrement value"
              data-testid="numberinput-dec"
            >
              <ChevronDown className="h-3 w-3" />
            </button>
          </div>
        </div>

        {error ? (
          <p
            id={errorId}
            className="text-xs font-medium text-destructive mt-0.5"
            data-testid="numberinput-error"
          >
            {error}
          </p>
        ) : (
          helperText && (
            <p
              id={helperId}
              className="text-xs text-muted-foreground mt-0.5"
              data-testid="numberinput-helper"
            >
              {helperText}
            </p>
          )
        )}
      </div>
    );
  }
);

NumberInput.displayName = 'NumberInput';
