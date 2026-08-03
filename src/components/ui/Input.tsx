import * as React from 'react';
import { cn } from '../../utils/cn';

export interface InputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'prefix'> {
  label?: string;
  error?: string;
  helperText?: string;
  prefix?: React.ReactNode;
  suffix?: React.ReactNode;
  fullWidth?: boolean;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  (
    {
      className,
      label,
      error,
      helperText,
      prefix,
      suffix,
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
    const helperId = `${inputId}-helper`;
    const errorId = `${inputId}-error`;

    return (
      <div className={cn('flex flex-col gap-1.5', fullWidth ? 'w-full' : 'w-auto')}>
        {label && (
          <label
            htmlFor={inputId}
            className={cn(
              'text-sm font-medium text-foreground select-none',
              disabled && 'opacity-50'
            )}
            data-testid="input-label"
          >
            {label}
            {required && <span className="text-destructive ml-1" data-testid="input-required-star">*</span>}
          </label>
        )}

        <div className="relative flex items-center w-full rounded-md shadow-sm">
          {prefix && (
            <div
              className="absolute left-3 flex items-center justify-center text-muted-foreground pointer-events-none"
              data-testid="input-prefix"
            >
              {prefix}
            </div>
          )}

          <input
            id={inputId}
            ref={ref}
            disabled={disabled}
            aria-invalid={error ? 'true' : 'false'}
            aria-describedby={
              error ? errorId : helperText ? helperId : undefined
            }
            className={cn(
              'flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 transition-colors',
              prefix && 'pl-10',
              suffix && 'pr-10',
              error && 'border-destructive focus-visible:ring-destructive',
              className
            )}
            {...props}
          />

          {suffix && (
            <div
              className="absolute right-3 flex items-center justify-center text-muted-foreground"
              data-testid="input-suffix"
            >
              {suffix}
            </div>
          )}
        </div>

        {error ? (
          <p
            id={errorId}
            className="text-xs font-medium text-destructive mt-0.5"
            data-testid="input-error"
          >
            {error}
          </p>
        ) : (
          helperText && (
            <p
              id={helperId}
              className="text-xs text-muted-foreground mt-0.5"
              data-testid="input-helper"
            >
              {helperText}
            </p>
          )
        )}
      </div>
    );
  }
);

Input.displayName = 'Input';
