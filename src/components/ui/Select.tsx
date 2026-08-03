import * as React from 'react';
import { cn } from '../../utils/cn';

export interface SelectOption {
  label: string;
  value: string;
  disabled?: boolean;
}

export interface SelectOptionGroup {
  label: string;
  options: SelectOption[];
}

export interface SelectProps
  extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  placeholder?: string;
  error?: string;
  helperText?: string;
  options?: SelectOption[];
  groups?: SelectOptionGroup[];
  fullWidth?: boolean;
}

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  (
    {
      className,
      label,
      placeholder,
      error,
      helperText,
      options = [],
      groups = [],
      fullWidth = false,
      required,
      disabled,
      children,
      id,
      ...props
    },
    ref
  ) => {
    const generatedId = React.useId();
    const selectId = id || generatedId;
    const errorId = `${selectId}-error`;
    const helperId = `${selectId}-helper`;

    return (
      <div className={cn('flex flex-col gap-1.5', fullWidth ? 'w-full' : 'w-auto')}>
        {label && (
          <label
            htmlFor={selectId}
            className={cn(
              'text-sm font-medium text-foreground select-none',
              disabled && 'opacity-50'
            )}
            data-testid="select-label"
          >
            {label}
            {required && <span className="text-destructive ml-1" data-testid="select-required-star">*</span>}
          </label>
        )}

        <div className="relative w-full">
          <select
            id={selectId}
            ref={ref}
            disabled={disabled}
            aria-invalid={error ? 'true' : 'false'}
            aria-describedby={
              error ? errorId : helperText ? helperId : undefined
            }
            className={cn(
              'flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 transition-colors appearance-none pr-10',
              error && 'border-destructive focus-visible:ring-destructive',
              className
            )}
            {...props}
          >
            {placeholder && (
              <option value="" disabled hidden>
                {placeholder}
              </option>
            )}

            {children}

            {options.map((opt) => (
              <option
                key={opt.value}
                value={opt.value}
                disabled={opt.disabled}
              >
                {opt.label}
              </option>
            ))}

            {groups.map((group) => (
              <optgroup key={group.label} label={group.label}>
                {group.options.map((opt) => (
                  <option
                    key={opt.value}
                    value={opt.value}
                    disabled={opt.disabled}
                  >
                    {opt.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>

          {/* Custom dropdown arrow decorator */}
          <div
            className="absolute inset-y-0 right-0 flex items-center pr-3 pointer-events-none text-muted-foreground"
            data-testid="select-arrow"
          >
            <svg
              className="h-4 w-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                d="M19 9l-7 7-7-7"
              />
            </svg>
          </div>
        </div>

        {error ? (
          <p
            id={errorId}
            className="text-xs font-medium text-destructive mt-0.5"
            data-testid="select-error"
          >
            {error}
          </p>
        ) : (
          helperText && (
            <p
              id={helperId}
              className="text-xs text-muted-foreground mt-0.5"
              data-testid="select-helper"
            >
              {helperText}
            </p>
          )
        )}
      </div>
    );
  }
);

Select.displayName = 'Select';
