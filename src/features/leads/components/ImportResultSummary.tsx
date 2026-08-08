/**
 * src/features/leads/components/ImportResultSummary.tsx
 *
 * The outcome card shown once a run finishes.
 *
 * Reuses `StatCard` for the five figures rather than styling bespoke tiles, which is what
 * keeps this card visually identical to the statistics row above it. The heading and tone
 * change with the job's terminal status: a PARTIAL run reads as "finished with problems"
 * rather than "complete", because ninety-seven good leads plus three bad records is
 * neither a success nor a failure and the operator needs it flagged.
 */

import { CheckCircle2, AlertTriangle, XCircle } from 'lucide-react';
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  StatCard,
} from '../../../components/ui';
import { ImportJobDetail } from '../types';
import { formatDuration, formatProviderName } from '../importUtils';

export interface ImportResultSummaryProps {
  job: ImportJobDetail;
  onViewLeads: () => void;
  onImportAgain: () => void;
}

export const ImportResultSummary = ({
  job,
  onViewLeads,
  onImportAgain,
}: ImportResultSummaryProps) => {
  const duration = formatDuration(job.started_at, job.completed_at);

  const tone =
    job.status === 'FAILED'
      ? {
          title: 'Import Failed',
          icon: <XCircle className="h-5 w-5 text-destructive" aria-hidden="true" />,
        }
      : job.status === 'PARTIAL'
      ? {
          title: 'Import Finished With Problems',
          icon: (
            <AlertTriangle
              className="h-5 w-5 text-amber-600 dark:text-amber-400"
              aria-hidden="true"
            />
          ),
        }
      : {
          title: 'Import Complete',
          icon: (
            <CheckCircle2
              className="h-5 w-5 text-emerald-600 dark:text-emerald-400"
              aria-hidden="true"
            />
          ),
        };

  return (
    <Card data-testid="import-result-summary">
      {/*
        `aria-live` announces the outcome to a screen reader the moment this card mounts,
        which is the only signal a non-sighted user gets that the run finished.
      */}
      <CardHeader className="flex flex-row items-center gap-2 space-y-0">
        {tone.icon}
        <CardTitle role="status" aria-live="polite">
          {tone.title}
        </CardTitle>
      </CardHeader>

      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          {formatProviderName(job.provider)}
          {job.query ? ` · “${job.query}”` : ''}
          {job.source_filename ? ` · ${job.source_filename}` : ''}
        </p>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <StatCard title="Imported" value={job.new_leads} />
          <StatCard title="Duplicates" value={job.duplicate_leads} />
          <StatCard title="Updated" value={job.updated_leads} />
          <StatCard title="Failed" value={job.failed_records} />
          <StatCard title="Duration" value={duration ?? '—'} />
        </div>

        {job.error_message && (
          <p
            role="alert"
            className="rounded-md border border-destructive/20 bg-destructive/5 p-3 text-xs text-destructive dark:bg-destructive/10"
          >
            {job.error_message}
          </p>
        )}

        <div className="flex flex-col gap-2 sm:flex-row">
          <Button onClick={onViewLeads} data-testid="view-leads-button">
            View Leads
          </Button>
          <Button variant="outline" onClick={onImportAgain} data-testid="import-again-button">
            Import Again
          </Button>
        </div>
      </CardContent>
    </Card>
  );
};
