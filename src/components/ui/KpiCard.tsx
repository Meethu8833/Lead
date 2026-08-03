import * as React from 'react';
import { StatCard, StatCardProps } from './StatCard';
import { cn } from '../../utils/cn';

export interface KpiCardProps extends Omit<StatCardProps, 'trend'> {
  percentageChange: number;
  comparisonLabel?: string;
  miniChartPlaceholder?: React.ReactNode;
}

export const KpiCard = ({
  percentageChange,
  comparisonLabel,
  miniChartPlaceholder,
  footer,
  ...props
}: KpiCardProps) => {
  const trendDirection =
    percentageChange > 0 ? 'up' : percentageChange < 0 ? 'down' : 'neutral';

  const formattedValue =
    percentageChange > 0
      ? `+${percentageChange}%`
      : `${percentageChange}%`;

  // Merge the mini trend chart/sparkline placeholder into the layout footer
  const renderedFooter = React.useMemo(() => {
    if (!miniChartPlaceholder && !footer) return undefined;

    return (
      <div className="flex flex-col gap-2" data-testid="kpi-card-footer">
        {miniChartPlaceholder && (
          <div className="w-full h-8 flex items-center justify-center bg-muted/30 dark:bg-zinc-900/30 rounded border border-border/40 overflow-hidden" data-testid="kpi-mini-chart">
            {miniChartPlaceholder}
          </div>
        )}
        {footer && <div data-testid="kpi-footer-content">{footer}</div>}
      </div>
    );
  }, [miniChartPlaceholder, footer]);

  return (
    <StatCard
      {...props}
      trend={{
        value: formattedValue,
        direction: trendDirection,
        label: comparisonLabel,
      }}
      footer={renderedFooter}
      className={cn('relative border-primary/10 dark:border-primary/20 bg-gradient-to-br from-card to-muted/10 dark:from-zinc-950 dark:to-zinc-900/10', props.className)}
      data-testid="kpi-card"
    />
  );
};
