import * as React from 'react';
import { cn } from '../../utils/cn';

export interface CheckboxProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label?: string;
  description?: string;
  error?: boolean | string;
}

export const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, label, description, error, disabled, id, ...props }, ref) => {
    const generatedId = React.useId();
    const checkboxId = id || generatedId;

    return (
      <div className="flex flex-col gap-1">
        <label
          htmlFor={checkboxId}
          className={cn(
            'inline-flex items-start gap-2.5 cursor-pointer select-none',
            disabled && 'cursor-not-allowed opacity-50'
          )}
        >
          <div className="relative flex items-center h-5">
            <input
              id={checkboxId}
              type="checkbox"
              ref={ref}
              disabled={disabled}
              className="sr-only peer"
              {...props}
            />
            <div
              className={cn(
                'h-4 w-4 shrink-0 rounded border border-input bg-background transition-all flex items-center justify-center peer-focus-visible:outline-none peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 peer-checked:bg-primary peer-checked:border-primary peer-checked:text-primary-foreground',
                error && 'border-destructive peer-focus-visible:ring-destructive',
                className
              )}
              data-testid="checkbox-indicator"
            >
              <svg
                className="h-3 w-3 fill-none stroke-current stroke-[3] opacity-0 peer-checked:opacity-100 transition-opacity"
                viewBox="0 0 24 24"
                data-testid="checkbox-svg"
              >
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </div>
          </div>

          {(label || description) && (
            <div className="flex flex-col select-none">
              {label && (
                <span
                  className="text-sm font-medium text-foreground leading-none"
                  data-testid="checkbox-label"
                >
                  {label}
                </span>
              )}
              {description && (
                <span
                  className="text-xs text-muted-foreground mt-1"
                  data-testid="checkbox-description"
                >
                  {description}
                </span>
              )}
            </div>
          )}
        </label>

        {error && typeof error === 'string' && (
          <p className="text-xs font-medium text-destructive pl-6.5 mt-0.5" data-testid="checkbox-error">
            {error}
          </p>
        )}
      </div>
    );
  }
);

Checkbox.displayName = 'Checkbox';
