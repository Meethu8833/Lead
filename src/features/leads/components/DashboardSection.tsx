/**
 * src/features/leads/components/DashboardSection.tsx
 *
 * The card shell every dashboard section sits in, and the single place the
 * loading / empty / error triad is resolved.
 *
 * Each section on this page needs all three states. Implementing that per section would
 * mean six near-identical copies drifting apart, so the decision lives here once and the
 * sections pass flags. Precedence is error > loading > empty > content: an error must not
 * be hidden behind a skeleton, and an empty list must not be claimed while data is still
 * in flight.
 */

import * as React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../../../components/ui/Card';
import { Skeleton } from '../../../components/ui/Skeleton';
import { EmptyState } from '../../../components/ui/EmptyState';
import { ErrorState } from '../../../components/ui/ErrorState';
import { cn } from '../../../utils/cn';

export interface DashboardSectionProps {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  actions?: React.ReactNode;
  isLoading?: boolean;
  isError?: boolean;
  isEmpty?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  emptyIcon?: React.ReactNode;
  emptyAction?: React.ReactNode;
  errorDescription?: string;
  onRetry?: () => void;
  /** Rows of skeleton placeholder to show while loading. */
  skeletonRows?: number;
  className?: string;
  contentClassName?: string;
  children: React.ReactNode;
  'data-testid'?: string;
}

export const DashboardSection = ({
  title,
  description,
  icon,
  actions,
  isLoading = false,
  isError = false,
  isEmpty = false,
  emptyTitle = 'Nothing here yet',
  emptyDescription = 'There is no data to display for this section.',
  emptyIcon,
  emptyAction,
  errorDescription = 'We could not load this section. Please try again.',
  onRetry,
  skeletonRows = 3,
  className,
  contentClassName,
  children,
  'data-testid': testId,
}: DashboardSectionProps) => {
  const renderBody = () => {
    if (isError) {
      return (
        <ErrorState
          description={errorDescription}
          onRetry={onRetry}
          className="max-w-full border-0 bg-transparent dark:bg-transparent p-4"
          data-testid={testId ? `${testId}-error` : undefined}
        />
      );
    }

    if (isLoading) {
      return (
        <div className="space-y-3" data-testid={testId ? `${testId}-loading` : 'section-loading'}>
          {Array.from({ length: skeletonRows }).map((_, index) => (
            <div key={index} className="flex items-center gap-3">
              <Skeleton className="h-10 w-10 rounded-full shrink-0" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-3.5 w-1/3" />
                <Skeleton className="h-3 w-2/3" />
              </div>
            </div>
          ))}
        </div>
      );
    }

    if (isEmpty) {
      return (
        <EmptyState
          icon={emptyIcon}
          title={emptyTitle}
          description={emptyDescription}
          action={emptyAction}
          className="max-w-full border-0 bg-transparent dark:bg-transparent"
          data-testid={testId ? `${testId}-empty` : undefined}
        />
      );
    }

    return children;
  };

  return (
    <Card className={cn('flex flex-col', className)} data-testid={testId}>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0 pb-4">
        <div className="space-y-1 min-w-0">
          <CardTitle className="text-base font-semibold flex items-center gap-2">
            {icon && <span className="text-muted-foreground shrink-0">{icon}</span>}
            <span className="truncate">{title}</span>
          </CardTitle>
          {description && (
            <p className="text-xs text-muted-foreground">{description}</p>
          )}
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </CardHeader>
      <CardContent className={cn('flex-1', contentClassName)}>{renderBody()}</CardContent>
    </Card>
  );
};
