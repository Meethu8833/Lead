import * as React from 'react';
import { Card, CardContent } from './Card';
import { Skeleton } from './Skeleton';
import { cn } from '../../utils/cn';
import { ArrowUpRight, ArrowDownRight, Minus } from 'lucide-react';

export interface TrendType {
  value: number | string;
  direction: 'up' | 'down' | 'neutral';
  label?: string;
}

export interface StatCardProps {
  title: string;
  value: React.ReactNode;
  icon?: React.ReactNode;
  footer?: React.ReactNode;
  loading?: boolean;
  trend?: TrendType;
  className?: string;
}

export const StatCard = ({
  title,
  value,
  icon,
  footer,
  loading = false,
  trend,
  className,
}: StatCardProps) => {
  const renderTrend = () => {
    if (!trend) return null;

    const directions = {
      up: {
        icon: <ArrowUpRight className="h-4 w-4" />,
        textClass: 'text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/30',
      },
      down: {
        icon: <ArrowDownRight className="h-4 w-4" />,
        textClass: 'text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/30',
      },
      neutral: {
        icon: <Minus className="h-4 w-4" />,
        textClass: 'text-muted-foreground bg-muted dark:bg-zinc-900',
      },
    };

    const currentTrend = directions[trend.direction];

    return (
      <div className="flex items-center gap-1.5 flex-wrap" data-testid="stat-trend-container">
        <span
          className={cn(
            'inline-flex items-center gap-0.5 px-2 py-0.5 rounded text-xs font-semibold select-none',
            currentTrend.textClass
          )}
          data-testid={`stat-trend-${trend.direction}`}
        >
          {currentTrend.icon}
          <span>{trend.value}</span>
        </span>
        {trend.label && (
          <span className="text-xs text-muted-foreground" data-testid="stat-trend-label">
            {trend.label}
          </span>
        )}
      </div>
    );
  };

  return (
    <Card className={cn('relative overflow-hidden transition-all hover:shadow-md border border-border bg-card', className)} data-testid="stat-card">
      <CardContent className="p-6">
        {loading ? (
          <div className="space-y-4" data-testid="stat-card-skeleton">
            <div className="flex items-center justify-between gap-4">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-9 w-9 rounded-md" />
            </div>
            <Skeleton className="h-8 w-32" />
            <div className="flex items-center gap-2">
              <Skeleton className="h-4 w-12" />
              <Skeleton className="h-4 w-20" />
            </div>
          </div>
        ) : (
          <div className="flex flex-col h-full justify-between gap-4">
            {/* Top Row: Title & Icon */}
            <div className="flex items-start justify-between gap-4">
              <span className="text-sm font-medium text-muted-foreground select-none" data-testid="stat-card-title">
                {title}
              </span>
              {icon && (
                <span className="p-2.5 rounded-lg bg-muted/60 dark:bg-zinc-900/60 text-muted-foreground shrink-0 select-none" data-testid="stat-card-icon">
                  {icon}
                </span>
              )}
            </div>

            {/* Middle Row: Value & Trend */}
            <div className="space-y-1.5">
              <div className="text-2xl sm:text-3xl font-bold tracking-tight text-foreground" data-testid="stat-card-value">
                {value}
              </div>
              {trend && renderTrend()}
            </div>

            {/* Bottom Row: Footer */}
            {footer && (
              <div className="text-xs text-muted-foreground border-t border-border pt-3 select-none" data-testid="stat-card-footer">
                {footer}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
};
