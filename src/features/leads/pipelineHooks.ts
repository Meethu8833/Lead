/**
 * src/features/leads/pipelineHooks.ts
 *
 * Business logic for the Lead Pipeline board. The components below this layer render what
 * these hooks return and raise events; every fetch, page accumulation, sort and optimistic
 * cache edit happens here.
 *
 * Two shapes are worth understanding before reading on, and both are forced by the API:
 *
 *  - **One query per column, not one query for the board.** `GET /leads` caps `limit` at
 *    500 and returns no status histogram, so fetching everything and grouping client-side
 *    would truncate silently and report per-column totals that only describe the first
 *    page. Nine filtered requests instead give each column an exact `total` from its own
 *    envelope and let one column paginate without refetching the rest.
 *
 *  - **Pages accumulate rather than replace.** A column at page 3 keeps pages 0..2 as
 *    separate cache entries and concatenates them, the same approach the Lead Details
 *    timeline uses. Loading page 3 never refetches 1 and 2, and invalidating the column
 *    after a drop correctly refreshes every loaded page of it.
 */

import { useCallback, useMemo, useState } from 'react';
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { followUpsService, leadNotesService, leadPipelineService } from '../../services/leads';
import { useNotificationStore } from '../../app/store';
import { leadKeys } from './hooks';
import { leadDetailKeys } from './detailHooks';
import {
  FollowUpCreatePayload,
  FollowUpTask,
  Lead,
  LeadStatus,
  Paginated,
  PipelineColumnState,
  PipelineFilters,
  PipelineSort,
} from './types';
import { PIPELINE_COLUMNS, PIPELINE_PAGE_SIZE, sortLeads } from './pipelineUtils';

/**
 * How many open follow-ups the board reads to resolve its cards' due dates.
 *
 * 200 is the backend's hard cap on `GET /followups?limit=`, so this asks for as much as
 * the API will give in one request.
 */
export const FOLLOW_UP_LOOKUP_LIMIT = 200;

/**
 * Query keys for the board.
 *
 * `board()` is the shared prefix over every column and page, so a mutation that could
 * have moved a card anywhere invalidates the whole board with one call. `column()` sits
 * under it, keyed by status *and* the serialised filters — changing a filter therefore
 * addresses a different cache entry rather than overwriting the unfiltered one, so
 * clearing a filter restores an already-cached board instantly.
 */
export const pipelineKeys = {
  board: () => [...leadKeys.all, 'pipeline'] as const,
  column: (status: LeadStatus, filters: PipelineFilters) =>
    [...leadKeys.all, 'pipeline', status, filters] as const,
  page: (status: LeadStatus, filters: PipelineFilters, skip: number) =>
    [...leadKeys.all, 'pipeline', status, filters, skip] as const,
};

/**
 * Every column's data, fetched in parallel and keyed by status.
 *
 * `pageCounts` tracks how many pages each column has loaded. It is deliberately *not*
 * reset when filters change: the filters are part of the query key, so a new filter set
 * addresses fresh cache entries anyway, and resetting would additionally throw away the
 * user's scroll depth on columns they had already expanded before filtering.
 *
 * The queries are flattened into a single `useQueries` call rather than one `useQueries`
 * per column, because hooks cannot be called in a loop — the flat list is rebuilt on every
 * render and re-indexed back into columns afterwards.
 */
export const usePipelineBoard = (filters: PipelineFilters, sort: PipelineSort) => {
  const [pageCounts, setPageCounts] = useState<Record<string, number>>({});

  // The filter object is rebuilt by the parent on every keystroke, so it is a new
  // reference each render even when nothing changed. Serialising it gives the memos below
  // a stable primitive to depend on and keeps the query keys value-equal.
  const filterKey = JSON.stringify(filters);

  /** One flat request list: every loaded page of every column. */
  const pageDescriptors = useMemo(
    () =>
      PIPELINE_COLUMNS.flatMap((status) => {
        const pages = pageCounts[status] ?? 1;
        return Array.from({ length: pages }, (_, page) => ({
          status,
          skip: page * PIPELINE_PAGE_SIZE,
        }));
      }),
    // filterKey is not read here but participates so the descriptors are rebuilt (and the
    // queries re-keyed) when the filters change.
    [pageCounts, filterKey]
  );

  const pageQueries = useQueries({
    queries: pageDescriptors.map(({ status, skip }) => ({
      queryKey: pipelineKeys.page(status, filters, skip),
      queryFn: () =>
        leadPipelineService.column(status, {
          ...filters,
          source: filters.source || undefined,
          skip,
          limit: PIPELINE_PAGE_SIZE,
        }),
      // Cards are read far more often than they move, and a drop already invalidates the
      // board explicitly, so a short window of staleness costs nothing and avoids a
      // nine-request refetch every time the tab regains focus.
      staleTime: 30_000,
      placeholderData: (previous: Paginated<Lead> | undefined) => previous,
    })),
  });

  const loadMore = useCallback((status: LeadStatus) => {
    setPageCounts((current) => ({ ...current, [status]: (current[status] ?? 1) + 1 }));
  }, []);

  /**
   * Re-index the flat query results back into per-column state.
   *
   * Cards are de-duplicated by id while concatenating: a lead moved by someone else
   * between two of this column's page fetches can legitimately appear on two pages, and
   * React would warn about the duplicate key and render the card twice.
   */
  const columns = useMemo<PipelineColumnState[]>(() => {
    const byStatus = new Map<LeadStatus, typeof pageQueries>();

    pageDescriptors.forEach((descriptor, index) => {
      const bucket = byStatus.get(descriptor.status) ?? [];
      bucket.push(pageQueries[index]);
      byStatus.set(descriptor.status, bucket);
    });

    return PIPELINE_COLUMNS.map((status) => {
      const queries = byStatus.get(status) ?? [];
      const seen = new Set<string>();
      const leads: Lead[] = [];

      queries.forEach((query) => {
        (query.data?.items ?? []).forEach((lead: Lead) => {
          if (seen.has(lead.id)) return;
          seen.add(lead.id);
          leads.push(lead);
        });
      });

      // `total` is the server's count for this status under the current filters. Read
      // from the last page that actually resolved, since a page still in flight carries
      // no envelope — and falling back to 0 would make a loading column claim to be empty.
      const totals = queries.map((query) => query.data?.total).filter((value) => value !== undefined);
      const total = totals.length ? (totals[totals.length - 1] as number) : 0;

      return {
        status,
        leads: sortLeads(leads, sort),
        total,
        loadedCount: leads.length,
        hasMore: leads.length < total,
        // Only the first page counts as "loading" — a column showing cards while it
        // fetches page 2 is not empty, and should not collapse into a skeleton.
        isLoading: queries[0]?.isLoading ?? true,
        isFetchingMore: queries.slice(1).some((query) => query.isLoading),
        isError: queries.some((query) => query.isError),
        loadMore: () => loadMore(status),
      };
    });
  }, [pageQueries, pageDescriptors, sort, loadMore]);

  const totalLeads = useMemo(
    () => columns.reduce((sum, column) => sum + column.total, 0),
    [columns]
  );

  return {
    columns,
    totalLeads,
    isLoading: columns.some((column) => column.isLoading),
    isError: columns.every((column) => column.isError),
  };
};

/**
 * Moving a lead between columns — the write behind a drop.
 *
 * Optimistic by necessity rather than for polish: a drop is a direct-manipulation gesture,
 * and a card that springs back to its origin for the duration of a round trip reads as a
 * failed drag. So the card is moved in the cache immediately, and the mutation's job is to
 * confirm or undo that.
 *
 * The rollback is a **whole-board snapshot**, not a per-card one. A single move mutates
 * several cache entries — the source column's page, the destination column's page, and
 * both columns' totals — and restoring only the card would leave the counts wrong.
 * `getQueriesData` on the board prefix captures all of them, and `setQueriesData` in
 * `onError` puts every one back exactly as it was.
 */
export const useMoveLeadStatus = (filters: PipelineFilters) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ lead, status }: { lead: Lead; status: LeadStatus }) =>
      leadPipelineService.moveToStatus(lead.id, status, lead.version),

    onMutate: async ({ lead, status }) => {
      // Cancel in-flight column fetches first: one that resolves after the optimistic
      // edit would overwrite it with a server page that predates the move, snapping the
      // card back to where it started.
      await queryClient.cancelQueries({ queryKey: pipelineKeys.board() });

      const snapshot = queryClient.getQueriesData<Paginated<Lead>>({
        queryKey: pipelineKeys.board(),
      });

      const sourceKey = JSON.stringify(pipelineKeys.column(lead.status, filters));
      const targetKey = JSON.stringify(pipelineKeys.column(status, filters));

      // Applied per cache entry so each column's own `total` moves with the card. The
      // key is compared by its column prefix, because a column's pages are separate
      // entries that differ only in their trailing `skip`.
      queryClient
        .getQueryCache()
        .findAll({ queryKey: pipelineKeys.board() })
        .forEach((query) => {
          const key = query.queryKey as unknown[];
          const columnPrefix = JSON.stringify(key.slice(0, 4));
          const page = query.state.data as Paginated<Lead> | undefined;
          if (!page) return;

          if (columnPrefix === sourceKey) {
            const remaining = page.items.filter((item) => item.id !== lead.id);
            if (remaining.length !== page.items.length) {
              queryClient.setQueryData<Paginated<Lead>>(query.queryKey, {
                ...page,
                items: remaining,
                total: Math.max(0, page.total - 1),
              });
            } else {
              // The card is on another page of this column, but the count still drops.
              queryClient.setQueryData<Paginated<Lead>>(query.queryKey, {
                ...page,
                total: Math.max(0, page.total - 1),
              });
            }
            return;
          }

          if (columnPrefix === targetKey) {
            // Only the destination's *first* page receives the card — appending it to
            // page 2 would place it below cards it should outrank, and it would vanish
            // on the next refetch anyway. Every page of the column still gains the count.
            const isFirstPage = key[key.length - 1] === 0;
            queryClient.setQueryData<Paginated<Lead>>(query.queryKey, {
              ...page,
              items:
                isFirstPage && !page.items.some((item) => item.id === lead.id)
                  ? [{ ...lead, status }, ...page.items]
                  : page.items,
              total: page.total + 1,
            });
          }
        });

      return { snapshot };
    },

    onError: (_error, _variables, context) => {
      // Put every touched entry back. Without this the board would keep showing a card in
      // a column the server never accepted it into.
      context?.snapshot?.forEach(([key, data]) => {
        queryClient.setQueryData(key, data);
      });
    },

    onSuccess: (updated: Lead) => {
      // The lead's own detail cache is now stale — its status, version and timeline all
      // changed — and so are the dashboard counters derived from lead statuses.
      queryClient.setQueryData(leadDetailKeys.profile(updated.id), updated);
      queryClient.invalidateQueries({ queryKey: leadDetailKeys.detail(updated.id) });
      queryClient.invalidateQueries({ queryKey: leadKeys.summary() });
      queryClient.invalidateQueries({ queryKey: leadKeys.count() });
      queryClient.invalidateQueries({ queryKey: leadKeys.sample() });
    },

    onSettled: () => {
      // Reconcile the optimistic edit against the server either way: on success the
      // real row order and totals are confirmed, and on failure the restored snapshot is
      // re-verified rather than trusted.
      queryClient.invalidateQueries({ queryKey: pipelineKeys.board() });
    },
  });
};

/**
 * The board's drag-and-drop state machine, and the toasts around a move.
 *
 * Kept out of the components so the board itself holds no logic: it renders `draggingId`
 * and `dragOverStatus`, and calls `onDragStart` / `onDragEnter` / `onDrop`.
 */
export const usePipelineDragAndDrop = (filters: PipelineFilters) => {
  const [draggingLead, setDraggingLead] = useState<Lead | null>(null);
  const [dragOverStatus, setDragOverStatus] = useState<LeadStatus | null>(null);
  const { addToast } = useNotificationStore();
  const mutation = useMoveLeadStatus(filters);

  const handleDragStart = useCallback((lead: Lead) => {
    setDraggingLead(lead);
  }, []);

  const handleDragEnd = useCallback(() => {
    setDraggingLead(null);
    setDragOverStatus(null);
  }, []);

  const handleDragEnterColumn = useCallback((status: LeadStatus | null) => {
    setDragOverStatus(status);
  }, []);

  /**
   * Commits a drop.
   *
   * Resolves the dragged lead from state rather than trusting the drop event's payload
   * alone, because the board needs the whole record — `version` for the optimistic lock,
   * and `status` to know which column to remove the card from.
   */
  const handleDrop = useCallback(
    async (status: LeadStatus, lead?: Lead | null) => {
      const target = lead ?? draggingLead;
      setDraggingLead(null);
      setDragOverStatus(null);

      if (!target) return;
      // Dropping a card back where it came from is an abandoned drag, not an edit.
      if (target.status === status) return;

      const label = humanizeForToast(status);

      addToast({
        title: 'Moving lead…',
        message: `Moving "${target.business_name}" to ${label}.`,
        type: 'info',
        duration: 2000,
      });

      try {
        await mutation.mutateAsync({ lead: target, status });
        addToast({
          title: 'Lead moved',
          message: `"${target.business_name}" is now in ${label}.`,
          type: 'success',
        });
      } catch (error) {
        // 409 is the interesting failure: someone else edited this lead, so the version
        // sent with the drop is stale. It needs different advice from a generic error,
        // because retrying the same drag will keep failing until the board refetches.
        const httpStatus = (error as { response?: { status?: number } })?.response?.status;
        addToast({
          title: 'Move failed',
          message:
            httpStatus === 409
              ? `"${target.business_name}" was changed by someone else. The board has been refreshed — please try again.`
              : `Could not move "${target.business_name}". The card has been put back.`,
          type: 'error',
        });
      }
    },
    [draggingLead, mutation, addToast]
  );

  return {
    draggingLead,
    draggingLeadId: draggingLead?.id ?? null,
    dragOverStatus,
    isMoving: mutation.isPending,
    movingLeadId: mutation.isPending ? (mutation.variables?.lead.id ?? null) : null,
    onDragStart: handleDragStart,
    onDragEnd: handleDragEnd,
    onDragEnterColumn: handleDragEnterColumn,
    onDrop: handleDrop,
  };
};

/** "MESSAGE_SENT" -> "Message Sent", for toast copy. */
const humanizeForToast = (status: string): string =>
  status
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');

// ==========================================
// CARD QUICK ACTIONS
// ==========================================

/**
 * The next open follow-up per lead, so cards can show "Follow-up Due".
 *
 * The due date is not a column on `Lead`, and there is no endpoint returning follow-ups
 * for a *set* of leads — `GET /followups?lead_id=` takes one id. Fanning out one request
 * per visible card would mean dozens of requests per board render, so this instead reads
 * the upcoming worklist in bulk (`GET /followups` filtered to PENDING, newest window
 * first) and indexes it by lead.
 *
 * The consequence, stated plainly: a lead whose only open follow-up falls outside the
 * `limit` most imminent tasks shows no due date on its card. That is the right failure —
 * the field is decoration on a card, the Lead Details page is authoritative, and the
 * alternative is an N+1 that would dominate the board's load time.
 */
export const usePipelineFollowUpDueDates = (limit = FOLLOW_UP_LOOKUP_LIMIT) => {
  const query = useQuery({
    queryKey: [...pipelineKeys.board(), 'followups', limit] as const,
    queryFn: () => followUpsService.pending(limit),
    staleTime: 60_000,
  });

  /** leadId -> soonest pending `scheduled_at`. */
  const byLead = useMemo(() => {
    const map = new Map<string, string>();
    (query.data?.items ?? []).forEach((task: FollowUpTask) => {
      const existing = map.get(task.lead_id);
      // Keep the soonest, since a lead may legitimately have several open tasks and the
      // card has room for exactly one date.
      if (!existing || new Date(task.scheduled_at) < new Date(existing)) {
        map.set(task.lead_id, task.scheduled_at);
      }
    });
    return map;
  }, [query.data]);

  const resolveFollowUpDue = useCallback(
    (leadId: string): string | null => byLead.get(leadId) ?? null,
    [byLead]
  );

  return { resolveFollowUpDue, isLoading: query.isLoading };
};

/**
 * Creating a follow-up from a card.
 *
 * Unlike `useCreateLeadFollowUp` in detailHooks.ts, this is not bound to a lead id at
 * hook-construction time — the board does not know which card will raise the action until
 * it is raised — so the lead is part of the mutation's arguments instead.
 */
export const usePipelineCreateFollowUp = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      leadId,
      payload,
    }: {
      leadId: string;
      payload: Omit<FollowUpCreatePayload, 'lead_id'>;
    }) => followUpsService.create({ ...payload, lead_id: leadId }),

    onSuccess: (_task, { leadId }) => {
      // The card's due-date badge, the lead's own follow-up list and timeline, and the
      // dashboard's follow-up counters are all now stale.
      queryClient.invalidateQueries({ queryKey: [...pipelineKeys.board(), 'followups'] });
      queryClient.invalidateQueries({ queryKey: leadDetailKeys.followUps(leadId) });
      queryClient.invalidateQueries({ queryKey: leadDetailKeys.activities(leadId) });
      queryClient.invalidateQueries({ queryKey: leadKeys.followUpsToday() });
      queryClient.invalidateQueries({ queryKey: leadKeys.followUpStats() });
    },
  });
};

/** Adding a note from a card. Lead-agnostic, for the same reason as the hook above. */
export const usePipelineCreateNote = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ leadId, note }: { leadId: string; note: string }) =>
      leadNotesService.create(leadId, note),

    onSuccess: (_note, { leadId }) => {
      queryClient.invalidateQueries({ queryKey: leadDetailKeys.notes(leadId) });
      queryClient.invalidateQueries({ queryKey: leadDetailKeys.activities(leadId) });
    },
  });
};
