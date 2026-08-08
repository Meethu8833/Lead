/**
 * src/features/leads/importHooks.ts
 *
 * Business logic for the Lead Import screen. Components below this layer render what these
 * hooks return and raise events; every request, cache invalidation, toast and piece of
 * derived state lives here.
 *
 * Two decisions are worth stating up front:
 *
 *  - **Imports are mutations that return their own result.** The backend runs collection
 *    synchronously and responds with the finished job, so there is no polling loop and no
 *    job-status query. The completed job is held in local component state (via
 *    `useLeadImport`) and rendered as the result summary; it is not a cache entry because
 *    nothing else reads it.
 *
 *  - **A successful import invalidates the lead pipeline, not just the import history.**
 *    New leads have appeared, so every list, count and chart keyed under `leadKeys.all` is
 *    now stale. Invalidating the root key is deliberately broad: it is one call, it cannot
 *    miss a widget, and TanStack Query only refetches what is actually mounted.
 */

import { useCallback, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { leadImportsService } from '../../services/leads';
import { useNotificationStore } from '../../app/store';
import { leadKeys } from './hooks';
import {
  ImportJobDetail,
  ImportJobListParams,
  ImportRunPayload,
  ImportStatistics,
} from './types';
import {
  DEFAULT_IMPORT_LIMIT,
  DescribedProvider,
  describeProviders,
  toFriendlyErrorMessage,
} from './importUtils';

/** How many recent runs the history table shows by default. */
export const IMPORT_HISTORY_PAGE_SIZE = 10;

/**
 * Query keys for the import screen.
 *
 * Nested under `leadKeys.all` so that invalidating the lead root after an import also
 * refreshes the history and statistics on this page, rather than needing separate calls
 * that could drift apart.
 */
export const importKeys = {
  all: [...leadKeys.all, 'import'] as const,
  providers: () => [...importKeys.all, 'providers'] as const,
  statistics: () => [...importKeys.all, 'statistics'] as const,
  history: (params: ImportJobListParams) =>
    [...importKeys.all, 'history', params] as const,
};

/**
 * Loads the provider registry and merges it with local capability copy.
 *
 * Availability comes from the server (an API key present or absent is a deployment fact),
 * so this is a query rather than a constant — see the note in `importUtils`.
 */
export function useImportProviders() {
  const query = useQuery({
    queryKey: importKeys.providers(),
    queryFn: () => leadImportsService.listProviders(),
    staleTime: 5 * 60 * 1000,
  });

  const providers = useMemo<DescribedProvider[]>(
    () => describeProviders(query.data?.items ?? []),
    [query.data]
  );

  return { ...query, providers };
}

/** Paginated import-run history for the table below the form. */
export function useImportHistory(params: ImportJobListParams = {}) {
  const merged: ImportJobListParams = {
    skip: 0,
    limit: IMPORT_HISTORY_PAGE_SIZE,
    ...params,
  };

  return useQuery({
    queryKey: importKeys.history(merged),
    queryFn: () => leadImportsService.listJobsFiltered(merged),
  });
}

/** Lifetime aggregate statistics for the summary cards. */
export function useImportStatistics() {
  return useQuery({
    queryKey: importKeys.statistics(),
    queryFn: () => leadImportsService.getStatistics(),
  });
}

/**
 * Derives the per-provider breakdown card from the history rows.
 *
 * The statistics endpoint aggregates by status, not by provider, and there is no
 * group-by-provider endpoint — so this counts what the loaded history page shows and
 * reports `isSampled` when more runs exist than were read, the same honesty the dashboard
 * charts apply to their 500-lead sample.
 */
export interface ProviderBreakdownRow {
  provider: string;
  jobs: number;
  imported: number;
}

export function useProviderBreakdown(
  jobs: { provider: string; new_leads: number }[] | undefined,
  total: number | undefined
) {
  return useMemo(() => {
    const rows = new Map<string, ProviderBreakdownRow>();

    for (const job of jobs ?? []) {
      const existing = rows.get(job.provider) ?? {
        provider: job.provider,
        jobs: 0,
        imported: 0,
      };
      existing.jobs += 1;
      existing.imported += job.new_leads;
      rows.set(job.provider, existing);
    }

    return {
      rows: [...rows.values()].sort((a, b) => b.imported - a.imported),
      isSampled: (total ?? 0) > (jobs?.length ?? 0),
    };
  }, [jobs, total]);
}

/** What the import form collects. Mirrors the fields the two endpoints accept. */
export interface ImportFormValues {
  provider: string;
  query: string;
  limit: number;
  file: File | null;
}

export const EMPTY_IMPORT_FORM: ImportFormValues = {
  provider: '',
  query: '',
  limit: DEFAULT_IMPORT_LIMIT,
  file: null,
};

/**
 * Runs an import and owns everything that follows from it.
 *
 * Exposes one `run` entry point that dispatches to the CSV or query endpoint by provider,
 * so the page never branches on transport. The finished job is kept here as `result`;
 * `reset` clears it for the "Import Again" button.
 */
export function useLeadImport() {
  const queryClient = useQueryClient();
  const addToast = useNotificationStore((state) => state.addToast);

  const [result, setResult] = useState<ImportJobDetail | null>(null);
  const [uploadPercent, setUploadPercent] = useState(0);

  const mutation = useMutation<ImportJobDetail, unknown, ImportFormValues>({
    mutationFn: async (values) => {
      setUploadPercent(0);

      if (values.file) {
        return leadImportsService.importCsv(values.file, values.limit, setUploadPercent);
      }

      const payload: ImportRunPayload = {
        provider: values.provider,
        query: values.query.trim() || null,
        limit: values.limit,
      };
      return leadImportsService.runImport(payload);
    },

    onSuccess: (job) => {
      setResult(job);

      // New leads exist: every lead list, count and chart is stale, as is this page's own
      // history and statistics (both nested under the same root key).
      queryClient.invalidateQueries({ queryKey: leadKeys.all });

      if (job.status === 'FAILED') {
        addToast({
          type: 'error',
          title: 'Import failed',
          message:
            job.error_message ??
            'The import finished without collecting any leads. Check the provider and query, then try again.',
        });
        return;
      }

      if (job.status === 'PARTIAL') {
        addToast({
          type: 'warning',
          title: 'Import finished with problems',
          message: `Imported ${job.new_leads} lead${job.new_leads === 1 ? '' : 's'}, but ${
            job.failed_records
          } record${job.failed_records === 1 ? '' : 's'} could not be read.`,
        });
        return;
      }

      addToast({
        type: 'success',
        title: 'Import complete',
        message: `Imported ${job.new_leads} new lead${job.new_leads === 1 ? '' : 's'} from ${
          job.total_found
        } record${job.total_found === 1 ? '' : 's'}.`,
      });
    },

    onError: (error) => {
      addToast({
        type: 'error',
        title: 'Import failed',
        message: toFriendlyErrorMessage(error),
      });
    },
  });

  const reset = useCallback(() => {
    setResult(null);
    setUploadPercent(0);
    mutation.reset();
  }, [mutation]);

  return {
    run: mutation.mutate,
    isImporting: mutation.isPending,
    error: mutation.error ? toFriendlyErrorMessage(mutation.error) : null,
    result,
    uploadPercent,
    reset,
  };
}

/** Re-runs a previous job from the history table. */
export function useRetryImport() {
  const queryClient = useQueryClient();
  const addToast = useNotificationStore((state) => state.addToast);

  return useMutation<ImportJobDetail, unknown, string>({
    mutationFn: (id) => leadImportsService.retryJob(id),
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: leadKeys.all });
      addToast({
        type: 'success',
        title: 'Retry finished',
        message: `The retry imported ${job.new_leads} new lead${
          job.new_leads === 1 ? '' : 's'
        }.`,
      });
    },
    onError: (error) => {
      addToast({
        type: 'error',
        title: 'Retry failed',
        message: toFriendlyErrorMessage(error),
      });
    },
  });
}

/** Convenience projection of the statistics response for the summary cards. */
export function summarizeStatistics(stats: ImportStatistics | undefined) {
  return {
    totalJobs: stats?.total_jobs ?? 0,
    totalImported: stats?.new_leads ?? 0,
    duplicatesPrevented: stats?.duplicate_leads ?? 0,
    updated: stats?.updated_leads ?? 0,
    failed: stats?.failed_records ?? 0,
  };
}
