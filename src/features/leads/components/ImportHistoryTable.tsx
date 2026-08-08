/**
 * src/features/leads/components/ImportHistoryTable.tsx
 *
 * Recent import runs and how each one landed.
 *
 * Presented as a scrollable table on desktop and stacked cards on mobile — eight columns,
 * six of them numeric, cannot be squeezed into a phone width without becoming unreadable,
 * so the small-screen layout drops the grid rather than the data. This mirrors what
 * `RecentImports` already does on the lead dashboard.
 *
 * Retry is offered only for the statuses the backend actually accepts (FAILED, PARTIAL,
 * CANCELLED) and never for a file upload, because the uploaded bytes are not retained
 * server-side — offering it there would produce a guaranteed 400.
 */

import { RefreshCw, RotateCcw } from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  Skeleton,
  Spinner,
} from '../../../components/ui';
import { ImportJob } from '../types';
import { formatDateTime } from '../../../utils/helpers';
import { formatDuration, formatProviderName, importStatusVariant } from '../importUtils';

export interface ImportHistoryTableProps {
  jobs: ImportJob[];
  isLoading?: boolean;
  isError?: boolean;
  onRefresh: () => void;
  isRefreshing?: boolean;
  onRetry?: (jobId: string) => void;
  retryingJobId?: string | null;
  canRetry?: boolean;
}

/** Statuses the retry endpoint accepts. */
const RETRYABLE = new Set(['FAILED', 'PARTIAL', 'CANCELLED']);

const isRetryable = (job: ImportJob) =>
  RETRYABLE.has(job.status) && !job.source_filename;

export const ImportHistoryTable = ({
  jobs,
  isLoading = false,
  isError = false,
  onRefresh,
  isRefreshing = false,
  onRetry,
  retryingJobId = null,
  canRetry = false,
}: ImportHistoryTableProps) => {
  const showRetryColumn = canRetry && Boolean(onRetry);

  return (
    <Card data-testid="import-history">
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle>Import History</CardTitle>
        <Button
          variant="ghost"
          size="sm"
          onClick={onRefresh}
          disabled={isRefreshing}
          aria-label="Refresh import history"
          data-testid="refresh-history"
        >
          <RefreshCw
            className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`}
            aria-hidden="true"
          />
          <span className="ml-2 hidden sm:inline">Refresh</span>
        </Button>
      </CardHeader>

      <CardContent>
        {isLoading ? (
          <div className="space-y-2" data-testid="history-loading">
            {[0, 1, 2].map((row) => (
              <Skeleton key={row} className="h-12 w-full" />
            ))}
          </div>
        ) : isError ? (
          <ErrorState
            description="Could not load the import history."
            onRetry={onRefresh}
          />
        ) : jobs.length === 0 ? (
          <EmptyState
            title="No imports yet"
            description="Run your first import above and it will appear here."
          />
        ) : (
          <>
            {/* Desktop / tablet */}
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full text-sm">
                <caption className="sr-only">
                  Recent lead import runs, newest first
                </caption>
                <thead>
                  <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground dark:border-zinc-800">
                    <th scope="col" className="py-2 pr-4 font-medium">Date</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Provider</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Keyword</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Imported</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Duplicates</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Failed</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Status</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Duration</th>
                    {showRetryColumn && (
                      <th scope="col" className="py-2 font-medium">
                        <span className="sr-only">Actions</span>
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job) => (
                    <tr
                      key={job.id}
                      className="border-b last:border-0 dark:border-zinc-800"
                      data-testid={`history-row-${job.id}`}
                    >
                      <td className="whitespace-nowrap py-2.5 pr-4">
                        {formatDateTime(job.created_at)}
                      </td>
                      <td className="whitespace-nowrap py-2.5 pr-4">
                        {formatProviderName(job.provider)}
                      </td>
                      <td className="max-w-[16rem] truncate py-2.5 pr-4 text-muted-foreground">
                        {job.query ?? job.source_filename ?? '—'}
                      </td>
                      <td className="py-2.5 pr-4 text-right tabular-nums">{job.new_leads}</td>
                      <td className="py-2.5 pr-4 text-right tabular-nums">
                        {job.duplicate_leads}
                      </td>
                      <td className="py-2.5 pr-4 text-right tabular-nums">
                        {job.failed_records}
                      </td>
                      <td className="py-2.5 pr-4">
                        <Badge variant={importStatusVariant(job.status)} size="sm">
                          {job.status}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap py-2.5 pr-4 text-muted-foreground">
                        {formatDuration(job.started_at, job.completed_at) ?? '—'}
                      </td>
                      {showRetryColumn && (
                        <td className="py-2.5">
                          {isRetryable(job) && (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => onRetry?.(job.id)}
                              disabled={retryingJobId === job.id}
                              aria-label={`Retry the ${formatProviderName(job.provider)} import`}
                            >
                              {retryingJobId === job.id ? (
                                <Spinner size="sm" />
                              ) : (
                                <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                              )}
                            </Button>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Mobile */}
            <ul className="space-y-3 md:hidden">
              {jobs.map((job) => (
                <li
                  key={job.id}
                  className="rounded-lg border p-3 dark:border-zinc-800"
                  data-testid={`history-card-${job.id}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">
                        {formatProviderName(job.provider)}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        {job.query ?? job.source_filename ?? '—'}
                      </p>
                    </div>
                    <Badge variant={importStatusVariant(job.status)} size="sm">
                      {job.status}
                    </Badge>
                  </div>

                  <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
                    <div>
                      <dt className="text-muted-foreground">Imported</dt>
                      <dd className="font-medium tabular-nums">{job.new_leads}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">Duplicates</dt>
                      <dd className="font-medium tabular-nums">{job.duplicate_leads}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">Failed</dt>
                      <dd className="font-medium tabular-nums">{job.failed_records}</dd>
                    </div>
                  </dl>

                  <p className="mt-2 text-xs text-muted-foreground">
                    {formatDateTime(job.created_at)}
                    {formatDuration(job.started_at, job.completed_at)
                      ? ` · ${formatDuration(job.started_at, job.completed_at)}`
                      : ''}
                  </p>

                  {showRetryColumn && isRetryable(job) && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="mt-3 w-full"
                      onClick={() => onRetry?.(job.id)}
                      disabled={retryingJobId === job.id}
                    >
                      {retryingJobId === job.id ? <Spinner size="sm" /> : 'Retry import'}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
};
