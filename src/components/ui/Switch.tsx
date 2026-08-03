import * as React from 'react';
import { cn } from '../../utils/cn';

export interface SwitchProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label?: string;
  description?: string;
  error?: boolean | string;
}

export const Switch = React.forwardRef<HTMLInputElement, SwitchProps>(
  ({ className, label, description, error, disabled, id, ...props }, ref) => {
    const generatedId = React.useId();
    const switchId = id || generatedId;

    return (
      <div className="flex flex-col gap-1">
        <label
          htmlFor={switchId}
          className={cn(
            'inline-flex items-start gap-3 cursor-pointer select-none',
            disabled && 'cursor-not-allowed opacity-50'
          )}
        >
          <div className="relative flex items-center h-5">
            <input
              id={switchId}
              type="checkbox"
              ref={ref}
              disabled={disabled}
              className="sr-only peer"
              {...props}
            />
            <div
              className={cn(
                'w-9 h-5 rounded-full bg-zinc-200 dark:bg-zinc-800 transition-colors flex items-center p-0.5 peer-focus-visible:outline-none peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 peer-checked:bg-primary peer-disabled:cursor-not-allowed',
                error && 'ring-2 ring-destructive ring-offset-2',
                className
              )}
              data-testid="switch-track"
            >
              <div
                className="w-4 h-4 rounded-full bg-background shadow-sm transition-transform duration-200 ease-in-out transform translate-x-0 peer-checked:translate-x-4"
                data-testid="switch-thumb"
              />
            </div>
          </div>

          {(label || description) && (
            <div className="flex flex-col select-none">
              {label && (
                <span
                  className="text-sm font-medium text-foreground leading-none"
                  data-testid="switch-label"
                >
                  {label}
                </span>
              )}
              {description && (
                <span
                  className="text-xs text-muted-foreground mt-1"
                  data-testid="switch-description"
                >
                  {description}
                </span>
              )}
            </div>
          )}
        </label>

        {error && typeof error === 'string' && (
          <p className="text-xs font-medium text-destructive mt-0.5" data-testid="switch-error">
            {error}
          </p>
        )}
      </div>
    );
  }
);

Switch.displayName = 'Switch';
