/**
 * src/features/leads/components/RecentImports.tsx
 *
 * Section 4 — the most recent lead-import runs and how each one landed.
 *
 * Rendered as a horizontally scrollable table on desktop and stacked cards on mobile:
 * seven numeric columns cannot be squeezed into a phone width without becoming
 * unreadable, so the small-screen layout drops the grid rather than the data.
 */

import { DashboardSection } from './DashboardSection';
import { LeadStatusBadge } from './LeadStatusBadge';
import { ImportJob } from '../types';
import { formatDateTime } from '../../../utils/helpers';
import { Download, PackageOpen } from 'lucide-react';

export interface RecentImportsProps {
  imports: ImportJob[];
  isLoading?: boolean;
  isError?: boolean;
  isEmpty?: boolean;
  onRetry?: () => void;
}

/** Turns "google_maps" into "Google Maps" for display. */
const formatProvider = (provider: string): string =>
  provider
    .split(/[_\-\s]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');

export const RecentImports = ({
  imports,
  isLoading = false,
  isError = false,
  isEmpty = false,
  onRetry,
}: RecentImportsProps) => {
  return (
    <DashboardSection
      title="Recent Lead Imports"
      description="Latest import runs and their outcomes"
      icon={<Download className="h-4 w-4" />}
      isLoading={isLoading}
      isError={isError}
      isEmpty={isEmpty}
      emptyIcon={<PackageOpen className="h-6 w-6" />}
      emptyTitle="No imports yet"
      emptyDescription="Run your first lead import to populate the CRM with photographer prospects."
      errorDescription="We could not load recent imports. Please try again."
      onRetry={onRetry}
      skeletonRows={3}
      data-testid="recent-imports"
    >
      {/* Desktop / tablet: full table, scrolls sideways rather than wrapping columns. */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-sm" data-testid="recent-imports-table">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="pb-2 pr-4 font-medium">Provider</th>
              <th className="pb-2 pr-4 font-medium">Import Time</th>
              <th className="pb-2 pr-4 font-medium text-right">Imported</th>
              <th className="pb-2 pr-4 font-medium text-right">New</th>
              <th className="pb-2 pr-4 font-medium text-right">Duplicate</th>
              <th className="pb-2 pr-4 font-medium text-right">Failed</th>
              <th className="pb-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {imports.map((job) => (
              <tr key={job.id} data-testid="recent-import-row">
                <td className="py-2.5 pr-4 font-medium text-foreground">
                  {formatProvider(job.provider)}
                </td>
                <td className="py-2.5 pr-4 text-muted-foreground whitespace-nowrap">
                  {/* started_at is null until a run begins, so fall back to created_at. */}
                  {formatDateTime(job.started_at ?? job.created_at)}
                </td>
                <td className="py-2.5 pr-4 text-right tabular-nums">{job.total_found}</td>
                <td className="py-2.5 pr-4 text-right tabular-nums text-emerald-600 dark:text-emerald-400">
                  {job.new_leads}
                </td>
                <td className="py-2.5 pr-4 text-right tabular-nums text-muted-foreground">
                  {job.duplicate_leads}
                </td>
                <td className="py-2.5 pr-4 text-right tabular-nums text-rose-600 dark:text-rose-400">
                  {job.failed_records}
                </td>
                <td className="py-2.5">
                  <LeadStatusBadge status={job.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile: one card per run, same figures as labelled pairs. */}
      <ul className="md:hidden space-y-3" data-testid="recent-imports-mobile">
        {imports.map((job) => (
          <li
            key={job.id}
            className="rounded-lg border border-border p-3 space-y-2"
            data-testid="recent-import-card"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-sm">{formatProvider(job.provider)}</span>
              <LeadStatusBadge status={job.status} />
            </div>
            <div className="text-xs text-muted-foreground">
              {formatDateTime(job.started_at ?? job.created_at)}
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
              <span className="text-muted-foreground">
                Imported: <span className="text-foreground tabular-nums">{job.total_found}</span>
              </span>
              <span className="text-muted-foreground">
                New: <span className="text-emerald-600 dark:text-emerald-400 tabular-nums">{job.new_leads}</span>
              </span>
              <span className="text-muted-foreground">
                Duplicate: <span className="text-foreground tabular-nums">{job.duplicate_leads}</span>
              </span>
              <span className="text-muted-foreground">
                Failed: <span className="text-rose-600 dark:text-rose-400 tabular-nums">{job.failed_records}</span>
              </span>
            </div>
          </li>
        ))}
      </ul>
    </DashboardSection>
  );
};
