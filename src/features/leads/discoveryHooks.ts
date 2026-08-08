/**
 * src/features/leads/discoveryHooks.ts
 *
 * Business logic for the City Discovery mode. Components below this layer render what these
 * hooks return and raise events; every request, cache invalidation, toast, timer and piece
 * of derived state lives here.
 *
 * Three decisions shape this file:
 *
 *  - **Discovery is a mutation that returns its own result.** `POST /leads/discover` runs
 *    the whole pipeline synchronously and responds with the finished counters and records.
 *    There is no job row, so there is no id and nothing to fetch. The result is held in
 *    local state and rendered; it is not a cache entry because nothing else reads it.
 *
 *  - **The polling seam exists but is not yet wired to a real endpoint.** `useDiscoveryProgress`
 *    is written as a React Query `useQuery` with a `refetchInterval` and is *enabled: false*
 *    today, because there is no status endpoint for it to hit. It runs a local elapsed-time
 *    estimate instead. See the long note on that hook for exactly what changes when the
 *    backend grows a job row — it is a one-file change, by construction.
 *
 *  - **A successful run invalidates the lead root key.** New leads exist, so every list,
 *    count and chart under `leadKeys.all` is stale, as are the import history and statistics
 *    nested beneath it. One broad invalidation cannot miss a widget, and TanStack Query only
 *    refetches what is mounted.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { leadDiscoveryService } from '../../services/leads';
import { useNotificationStore } from '../../app/store';
import { leadKeys } from './hooks';
import { DiscoveryRunPayload, DiscoveryRunResult } from './types';
import { toFriendlyErrorMessage } from './importUtils';
import {
  DEFAULT_CATEGORY,
  DEFAULT_DISCOVERY_LIMIT,
  DISCOVERY_STAGES,
  discoveryOutcome,
  estimateStageIndex,
  stateForCity,
  summarizeDiscovery,
} from './discoveryUtils';

/**
 * Query keys for discovery.
 *
 * Nested under `leadKeys.all` so the single post-run invalidation reaches these too, the
 * same arrangement `importKeys` uses. `progress` is keyed by job id in anticipation of the
 * async backend; it is unused while discovery stays synchronous.
 */
export const discoveryKeys = {
  all: [...leadKeys.all, 'discovery'] as const,
  progress: (jobId: string | null) => [...discoveryKeys.all, 'progress', jobId] as const,
};

/** How often the progress query would poll the backend, once there is one to poll. */
export const DISCOVERY_POLL_INTERVAL_MS = 2000;

/** What the discovery form collects. Mirrors `DiscoveryRunRequest`. */
export interface DiscoveryFormValues {
  city: string;
  category: string;
  radius_km: number | null;
  limit: number;
  discover_websites: boolean;
  extract_contacts: boolean;
}

export const EMPTY_DISCOVERY_FORM: DiscoveryFormValues = {
  city: '',
  category: DEFAULT_CATEGORY,
  radius_km: null,
  limit: DEFAULT_DISCOVERY_LIMIT,
  discover_websites: true,
  extract_contacts: true,
};

/**
 * Translates form values into the request body.
 *
 * Exported and pure so the mapping is unit-testable without rendering anything. Two rules
 * live here rather than in the component: a curated city contributes its `state` so the
 * geocoder does not have to guess between same-named cities, and a blank category falls
 * back to the pipeline's own default rather than narrowing the search to an empty string.
 */
export function buildDiscoveryPayload(values: DiscoveryFormValues): DiscoveryRunPayload {
  const city = values.city.trim();
  const category = values.category.trim();

  const payload: DiscoveryRunPayload = {
    city,
    category: category || DEFAULT_CATEGORY,
    limit: values.limit,
    discover_websites: values.discover_websites,
    extract_contacts: values.extract_contacts,
  };

  const state = stateForCity(city);
  if (state) payload.state = state;

  // Omitted entirely rather than sent as null — the adapter then applies its own default
  // instead of receiving a value it would have to interpret.
  if (typeof values.radius_km === 'number') payload.radius_km = values.radius_km;

  return payload;
}

/**
 * Live progress for a running discovery.
 *
 * ## Why this is not really polling yet
 *
 * `POST /leads/discover` is synchronous and writes no job row: it returns only when the
 * pipeline has finished. There is no id to poll and no status endpoint to poll it against,
 * so a `useQuery` here would have nothing to ask. What this hook does instead is run a
 * local timer and derive the likely stage from elapsed time via `estimateStageIndex`. The
 * UI labels that as an estimate; it is not presented as observed truth.
 *
 * ## The seam
 *
 * The query below is real, keyed, and configured with `refetchInterval` — it is simply
 * `enabled: false` because `jobId` is always null today. When the backend grows an async
 * job (create an `ImportJob` row, run the pipeline in a background task, return the id),
 * the change is confined to this file:
 *
 *   1. `useRunDiscovery` sets the returned job id into `jobId` instead of holding a result.
 *   2. `queryFn` calls the new status endpoint.
 *   3. `isEstimated` becomes false and `stageIndex` reads the server's stage.
 *
 * The components consuming `stageIndex`/`percent`/`isEstimated` do not change at all, which
 * is the point of routing the estimate through the same shape the real thing will have.
 */
export function useDiscoveryProgress(options: {
  isRunning: boolean;
  jobId?: string | null;
  discoverWebsites: boolean;
  extractContacts: boolean;
}) {
  const { isRunning, jobId = null, discoverWebsites, extractContacts } = options;

  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const startedAtRef = useRef<number | null>(null);

  // Ticks once a second for as long as a run is open. Reset on each new run so a second
  // import does not continue the first one's clock.
  useEffect(() => {
    if (!isRunning) {
      startedAtRef.current = null;
      return;
    }

    startedAtRef.current = Date.now();
    setElapsedSeconds(0);

    const timer = window.setInterval(() => {
      if (startedAtRef.current === null) return;
      setElapsedSeconds((Date.now() - startedAtRef.current) / 1000);
    }, 1000);

    return () => window.clearInterval(timer);
  }, [isRunning]);

  // The seam described above. Disabled until there is a job id, which means it never runs
  // today — but it is wired, keyed and intervalled, so enabling it is the whole change.
  const progressQuery = useQuery({
    queryKey: discoveryKeys.progress(jobId),
    queryFn: async () => null as DiscoveryRunResult | null,
    enabled: Boolean(jobId) && isRunning,
    refetchInterval: isRunning ? DISCOVERY_POLL_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
  });

  const stageIndex = useMemo(
    () =>
      isRunning
        ? estimateStageIndex(elapsedSeconds, { discoverWebsites, extractContacts })
        : -1,
    [isRunning, elapsedSeconds, discoverWebsites, extractContacts]
  );

  // Deliberately capped below 100: the run is not finished until the response lands, and a
  // full bar that then keeps spinning reads as a stall.
  const percent = useMemo(() => {
    if (!isRunning) return 0;
    const raw = ((stageIndex + 1) / DISCOVERY_STAGES.length) * 100;
    return Math.min(95, Math.round(raw));
  }, [isRunning, stageIndex]);

  return {
    stageIndex,
    percent,
    elapsedSeconds,
    /** True while progress is a time-based guess rather than a reading from the server. */
    isEstimated: !jobId,
    isPolling: progressQuery.isFetching,
  };
}

/**
 * Runs a discovery and owns everything that follows from it.
 *
 * The finished result is kept here as `result`; `reset` clears it so the form can be shown
 * again. Toast wording is decided by `discoveryOutcome`, which draws the distinction the
 * counters alone do not: a run that found nothing is not a failure.
 */
export function useRunDiscovery() {
  const queryClient = useQueryClient();
  const addToast = useNotificationStore((state) => state.addToast);

  const [result, setResult] = useState<DiscoveryRunResult | null>(null);

  const mutation = useMutation<DiscoveryRunResult, unknown, DiscoveryFormValues>({
    mutationFn: (values) => leadDiscoveryService.discover(buildDiscoveryPayload(values)),

    onSuccess: (run) => {
      setResult(run);

      // Leads changed, so every lead list, count and chart is stale — as are this page's
      // import history and statistics, which nest under the same root key.
      queryClient.invalidateQueries({ queryKey: leadKeys.all });

      const outcome = discoveryOutcome(run);
      const message = summarizeDiscovery(run);

      if (outcome === 'empty') {
        addToast({ type: 'info', title: 'Nothing found', message });
        return;
      }
      if (outcome === 'failed') {
        addToast({ type: 'error', title: 'Discovery could not save leads', message });
        return;
      }
      if (outcome === 'partial') {
        addToast({ type: 'warning', title: 'Discovery finished with problems', message });
        return;
      }
      addToast({ type: 'success', title: 'Discovery complete', message });
    },

    onError: (error) => {
      addToast({
        type: 'error',
        title: 'Discovery failed',
        message: toFriendlyErrorMessage(error),
      });
    },
  });

  const reset = useCallback(() => {
    setResult(null);
    mutation.reset();
  }, [mutation]);

  return {
    run: mutation.mutate,
    isRunning: mutation.isPending,
    error: mutation.error ? toFriendlyErrorMessage(mutation.error) : null,
    result,
    reset,
  };
}

/**
 * Splits a finished result into the tabs the results table shows.
 *
 * Note there is no duplicates *list*: a duplicate matched an existing lead and contributed
 * nothing, so the backend records only its count. The tab still exists and shows that count
 * with an explanation, because an operator asking "why did 40 records yield 12 leads" needs
 * to see the number even without rows behind it.
 */
export interface DiscoveryTabCounts {
  imported: number;
  merged: number;
  duplicates: number;
  failed: number;
}

export function useDiscoveryTabs(result: DiscoveryRunResult | null) {
  return useMemo<DiscoveryTabCounts>(
    () => ({
      imported: result?.imported ?? 0,
      merged: result?.merged ?? 0,
      duplicates: result?.duplicates ?? 0,
      failed: result?.failed ?? 0,
    }),
    [result]
  );
}
