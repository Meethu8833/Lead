import * as React from 'react';
import { cn } from '../../utils/cn';

export interface EmptyStateProps extends React.HTMLAttributes<HTMLDivElement> {
  icon?: React.ReactNode;
  title: string;
  description: string;
  action?: React.ReactNode;
}

export const EmptyState = React.forwardRef<HTMLDivElement, EmptyStateProps>(
  ({ className, icon, title, description, action, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          'flex flex-col items-center justify-center text-center p-8 border border-dashed rounded-lg border-muted-foreground/20 dark:border-zinc-800 bg-card dark:bg-zinc-950/20 max-w-md mx-auto',
          className
        )}
        data-testid="empty-state"
        {...props}
      >
        {icon && (
          <div className="flex items-center justify-center text-muted-foreground mb-4 w-12 h-12 rounded-full bg-muted dark:bg-zinc-900" data-testid="empty-state-icon">
            {icon}
          </div>
        )}
        <h3 className="text-lg font-semibold text-foreground mb-1" data-testid="empty-state-title">{title}</h3>
        <p className="text-sm text-muted-foreground mb-6 max-w-xs" data-testid="empty-state-description">{description}</p>
        {action && <div className="flex justify-center w-full" data-testid="empty-state-action">{action}</div>}
      </div>
    );
  }
);

EmptyState.displayName = 'EmptyState';
