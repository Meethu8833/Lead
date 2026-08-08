/**
 * src/features/leads/components/ImportStatsCards.tsx
 *
 * The lifetime-statistics row above the import form, plus the per-provider breakdown.
 *
 * Every figure is a `StatCard` from the design system — the requirement is explicit that
 * no new dashboard component be introduced for this screen, and the four headline numbers
 * map onto that primitive exactly.
 *
 * The breakdown is derived from the loaded history page rather than a dedicated endpoint,
 * because the statistics endpoint aggregates by status and nothing aggregates by provider.
 * When more runs exist than were read, the card says so rather than presenting a partial
 * count as a lifetime total.
 */

import { Clock, Copy, Download, Layers } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, StatCard } from '../../../components/ui';
import { ImportStatistics } from '../types';
import { ProviderBreakdownRow } from '../importHooks';
import { formatProviderName } from '../importUtils';
import { formatDateTime } from '../../../utils/helpers';

export interface ImportStatsCardsProps {
  statistics?: ImportStatistics;
  isLoading?: boolean;
  /** `created_at` of the newest run, read from the history rather than the aggregates. */
  lastImportAt?: string | null;
  breakdown: ProviderBreakdownRow[];
  breakdownIsSampled?: boolean;
}

export const ImportStatsCards = ({
  statistics,
  isLoading = false,
  lastImportAt,
  breakdown,
  breakdownIsSampled = false,
}: ImportStatsCardsProps) => {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="Total Imports"
          value={statistics?.total_jobs ?? 0}
          loading={isLoading}
          icon={<Layers className="h-4 w-4" aria-hidden="true" />}
        />
        <StatCard
          title="Total Leads Imported"
          value={statistics?.new_leads ?? 0}
          loading={isLoading}
          icon={<Download className="h-4 w-4" aria-hidden="true" />}
        />
        <StatCard
          title="Duplicates Prevented"
          value={statistics?.duplicate_leads ?? 0}
          loading={isLoading}
          icon={<Copy className="h-4 w-4" aria-hidden="true" />}
          footer={
            statistics ? `${statistics.updated_leads} existing leads enriched` : undefined
          }
        />
        <StatCard
          title="Last Import"
          value={lastImportAt ? formatDateTime(lastImportAt) : 'Never'}
          loading={isLoading}
          icon={<Clock className="h-4 w-4" aria-hidden="true" />}
        />
      </div>

      {breakdown.length > 0 && (
        <Card data-testid="provider-breakdown">
          <CardHeader>
            <CardTitle>Provider Breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {breakdown.map((row) => (
                <li
                  key={row.provider}
                  className="flex items-center justify-between gap-3 text-sm"
                >
                  <span className="font-medium">{formatProviderName(row.provider)}</span>
                  <span className="text-muted-foreground tabular-nums">
                    {row.imported} lead{row.imported === 1 ? '' : 's'} · {row.jobs} run
                    {row.jobs === 1 ? '' : 's'}
                  </span>
                </li>
              ))}
            </ul>
            {breakdownIsSampled && (
              <p className="mt-3 text-xs text-muted-foreground">
                Based on the most recent runs shown below, not the full history.
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
};
