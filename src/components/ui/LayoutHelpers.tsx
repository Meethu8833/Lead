import * as React from 'react';
import { cn } from '../../utils/cn';

// ----------------------------------------------------
// PageContainer
// ----------------------------------------------------
export interface PageContainerProps extends React.HTMLAttributes<HTMLDivElement> {}

export const PageContainer = React.forwardRef<HTMLDivElement, PageContainerProps>(
  ({ className, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          'mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8 py-6 space-y-6 flex flex-col min-h-0',
          className
        )}
        data-testid="page-container"
        {...props}
      />
    );
  }
);
PageContainer.displayName = 'PageContainer';

// ----------------------------------------------------
// PageHeader
// ----------------------------------------------------
export interface PageHeaderProps extends Omit<React.HTMLAttributes<HTMLDivElement>, 'title'> {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}

export const PageHeader = React.forwardRef<HTMLDivElement, PageHeaderProps>(
  ({ className, title, description, actions, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          'flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-5 border-b border-border select-none',
          className
        )}
        data-testid="page-header"
        {...props}
      >
        <div className="space-y-1">
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-foreground" data-testid="page-header-title">
            {title}
          </h1>
          {description && (
            <p className="text-sm text-muted-foreground" data-testid="page-header-description">
              {description}
            </p>
          )}
        </div>
        {actions && (
          <div className="flex items-center gap-3 sm:shrink-0" data-testid="page-header-actions">
            {actions}
          </div>
        )}
      </div>
    );
  }
);
PageHeader.displayName = 'PageHeader';

// ----------------------------------------------------
// Section
// ----------------------------------------------------
export interface SectionProps extends Omit<React.HTMLAttributes<HTMLDivElement>, 'title'> {
  title?: React.ReactNode;
  actions?: React.ReactNode;
}

export const Section = React.forwardRef<HTMLDivElement, SectionProps>(
  ({ className, title, actions, children, ...props }, ref) => {
    return (
      <section
        ref={ref}
        className={cn('space-y-4', className)}
        data-testid="layout-section"
        {...props}
      >
        {(title || actions) && (
          <div className="flex items-center justify-between gap-4 select-none">
            {title && (
              <h2 className="text-lg font-semibold text-foreground/90" data-testid="section-title">
                {title}
              </h2>
            )}
            {actions && (
              <div className="flex items-center gap-2" data-testid="section-actions">
                {actions}
              </div>
            )}
          </div>
        )}
        <div className="w-full" data-testid="section-content">
          {children}
        </div>
      </section>
    );
  }
);
Section.displayName = 'Section';

// ----------------------------------------------------
// Divider
// ----------------------------------------------------
export interface DividerProps extends React.HTMLAttributes<HTMLDivElement> {
  vertical?: boolean;
}

export const Divider = React.forwardRef<HTMLDivElement, DividerProps>(
  ({ className, vertical = false, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          vertical ? 'w-[1px] self-stretch bg-border' : 'h-[1px] w-full bg-border',
          className
        )}
        data-testid="divider"
        role="separator"
        {...props}
      />
    );
  }
);
Divider.displayName = 'Divider';

// ----------------------------------------------------
// Toolbar
// ----------------------------------------------------
export interface ToolbarProps extends React.HTMLAttributes<HTMLDivElement> {}

export const Toolbar = React.forwardRef<HTMLDivElement, ToolbarProps>(
  ({ className, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          'flex flex-wrap items-center justify-between gap-4 p-4 rounded-lg border border-border bg-card shadow-sm select-none',
          className
        )}
        data-testid="toolbar"
        {...props}
      />
    );
  }
);
Toolbar.displayName = 'Toolbar';

// ----------------------------------------------------
// FilterBar
// ----------------------------------------------------
export interface FilterBarProps extends React.HTMLAttributes<HTMLDivElement> {}

export const FilterBar = React.forwardRef<HTMLDivElement, FilterBarProps>(
  ({ className, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          'flex flex-wrap items-center gap-3 p-3 bg-muted/40 dark:bg-zinc-900/40 rounded-md border border-border/80 select-none',
          className
        )}
        data-testid="filter-bar"
        {...props}
      />
    );
  }
);
FilterBar.displayName = 'FilterBar';
