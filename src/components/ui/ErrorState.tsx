import * as React from 'react';
import { cn } from '../../utils/cn';
import { Button } from './Button';
import { AlertTriangle } from 'lucide-react';

export interface ErrorStateProps extends React.HTMLAttributes<HTMLDivElement> {
  title?: string;
  description: string;
  retryButton?: React.ReactNode;
  onRetry?: () => void;
  icon?: React.ReactNode;
}

export const ErrorState = React.forwardRef<HTMLDivElement, ErrorStateProps>(
  ({ className, title = 'An error occurred', description, retryButton, onRetry, icon, ...props }, ref) => {
    const defaultIcon = <AlertTriangle className="h-6 w-6 text-destructive" />;

    return (
      <div
        ref={ref}
        className={cn(
          'flex flex-col items-center justify-center text-center p-8 border rounded-lg border-destructive/20 bg-destructive/5 dark:bg-destructive/10 max-w-md mx-auto',
          className
        )}
        data-testid="error-state"
        {...props}
      >
        <div className="flex items-center justify-center mb-4 w-12 h-12 rounded-full bg-destructive/10 dark:bg-destructive/20" data-testid="error-state-icon">
          {icon || defaultIcon}
        </div>
        <h3 className="text-lg font-semibold text-destructive mb-1" data-testid="error-state-title">{title}</h3>
        <p className="text-sm text-muted-foreground mb-6 max-w-xs" data-testid="error-state-description">{description}</p>
        {retryButton ? (
          <div className="flex justify-center w-full" data-testid="error-state-retry-button-slot">{retryButton}</div>
        ) : (
          onRetry && (
            <Button variant="outline" size="sm" onClick={onRetry} data-testid="error-state-retry-button">
              Try Again
            </Button>
          )
        )}
      </div>
    );
  }
);

ErrorState.displayName = 'ErrorState';
