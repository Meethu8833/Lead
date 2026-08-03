import * as React from 'react';
import { cn } from '../../utils/cn';

export interface ProgressBarProps {
  value?: number;
  max?: number;
  variant?: 'determinate' | 'indeterminate';
  size?: 'sm' | 'md' | 'lg';
  label?: string | React.ReactNode;
  showPercentage?: boolean;
  className?: string;
  color?: 'primary' | 'success' | 'warning' | 'danger';
}

export const ProgressBar = ({
  value = 0,
  max = 100,
  variant = 'determinate',
  size = 'md',
  label,
  showPercentage = false,
  className,
  color = 'primary',
}: ProgressBarProps) => {
  const boundedValue = Math.min(Math.max(0, value), max);
  const percentage = Math.round((boundedValue / max) * 100);

  const heightClasses = {
    sm: 'h-1.5',
    md: 'h-2.5',
    lg: 'h-4',
  };

  const colorClasses = {
    primary: 'bg-primary',
    success: 'bg-emerald-600 dark:bg-emerald-500',
    warning: 'bg-amber-500 dark:bg-amber-400',
    danger: 'bg-destructive',
  };

  const isIndeterminate = variant === 'indeterminate';

  return (
    <div className={cn('w-full flex flex-col gap-1.5', className)} data-testid="progress-bar-container">
      {/* Label and Percentage */}
      {(label || showPercentage) && (
        <div className="flex items-center justify-between text-sm font-medium text-foreground/80 select-none">
          {label && <span data-testid="progress-bar-label">{label}</span>}
          {showPercentage && !isIndeterminate && (
            <span className="text-muted-foreground tabular-nums" data-testid="progress-bar-percentage">
              {percentage}%
            </span>
          )}
        </div>
      )}

      {/* Progress Track */}
      <div
        className={cn(
          'w-full bg-muted dark:bg-zinc-800 rounded-full overflow-hidden relative',
          heightClasses[size]
        )}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={isIndeterminate ? undefined : boundedValue}
        data-testid="progress-bar-track"
      >
        {isIndeterminate ? (
          /* Indeterminate sliding indicator */
          <div
            className={cn(
              'absolute top-0 bottom-0 rounded-full animate-progress-indeterminate',
              colorClasses[color]
            )}
            data-testid="progress-bar-indicator-indeterminate"
            style={{ width: '40%' }}
          />
        ) : (
          /* Determinate scaled indicator */
          <div
            className={cn(
              'h-full rounded-full transition-all duration-300 ease-out',
              colorClasses[color]
            )}
            data-testid="progress-bar-indicator-determinate"
            style={{ width: `${percentage}%` }}
          />
        )}
      </div>
    </div>
  );
};
