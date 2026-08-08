/**
 * src/features/leads/detailHooks.ts
 *
 * Business logic for the Lead Details workspace. As with `hooks.ts`, components in this
 * feature render what these hooks return and nothing more — every fan-out, join, sort and
 * cache-invalidation decision lives here.
 *
 * These live in their own module rather than in `hooks.ts` because the dashboard hooks are
 * about aggregate/cross-lead questions ("how many leads are INTERESTED", "who replied
 * recently"), while everything here is scoped to a single lead id. Splitting them keeps
 * the dashboard's bundle from pulling in the whole detail surface and vice versa.
 *
 * Two shapes are forced by the API rather than chosen:
 *
 *  - The timeline pages with `skip`/`limit` and is accumulated client-side by
 *    `useLeadActivities`, because the endpoint has no cursor and the page wants a growing
 *    "Load More" list rather than discrete pages.
 *  - WhatsApp history is assembled by fanning out over recent campaigns
 *    (`useLeadWhatsAppHistory`), because recipient rows are only reachable per-campaign:
 *    there is no `lead_id` filter on `GET /whatsapp/campaigns/{id}/recipients` and no
 *    lead-scoped message-history route. This is an N+1 by necessity, bounded by
 *    `LEAD_CAMPAIGN_HISTORY_LIMIT`.
 */

import { useCallback, useMemo, useState } from 'react';
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import dayjs from 'dayjs';
import {
  campaignsService,
  followUpsService,
  leadActivitiesService,
  leadNotesService,
  leadsService,
} from '../../services/leads';
import { leadKeys, useLeadEmployees } from './hooks';
import {
  CampaignRecipient,
  EmployeeSummary,
  FollowUpCancelPayload,
  FollowUpCompletePayload,
  FollowUpCreatePayload,
  FollowUpReschedulePayload,
  FollowUpTask,
  Lead,
  LeadActivity,
  LeadStatus,
  LeadUpdatePayload,
  LeadWhatsAppHistoryEntry,
  Paginated,
} from './types';

/** How many activities one timeline page holds. Each "Load More" adds another page. */
export const ACTIVITY_PAGE_SIZE = 20;

/**
 * How many recent campaigns the WhatsApp-history fan-out will visit.
 *
 * Bounds the N+1 described in the module docstring. A lead messaged only by campaigns
 * older than these N will show an empty history, which the UI states explicitly rather
 * than implying the lead was never contacted.
 */
export const LEAD_CAMPAIGN_HISTORY_LIMIT = 10;

/**
 * Query keys for the detail workspace, namespaced under one lead id.
 *
 * `detail(id)` is the shared prefix, so invalidating it after a status change refreshes
 * the profile, timeline, notes and follow-ups in one call — which is exactly what the
 * spec's "refresh all related queries after update" requires.
 */
export const leadDetailKeys = {
  detail: (leadId: string) => [...leadKeys.all, 'detail', leadId] as const,
  profile: (leadId: string) => [...leadKeys.all, 'detail', leadId, 'profile'] as const,
  activities: (leadId: string) => [...leadKeys.all, 'detail', leadId, 'activities'] as const,
  activityPage: (leadId: string, skip: number) =>
    [...leadKeys.all, 'detail', leadId, 'activities', skip] as const,
  notes: (leadId: string) => [...leadKeys.all, 'detail', leadId, 'notes'] as const,
  followUps: (leadId: string) => [...leadKeys.all, 'detail', leadId, 'followups'] as const,
  whatsapp: (leadId: string) => [...leadKeys.all, 'detail', leadId, 'whatsapp'] as const,
};

// ==========================================
// 1. LEAD PROFILE
// ==========================================

/** A single lead, the anchor query for the whole page. */
export const useLead = (leadId: string) => {
  const query = useQuery({
    queryKey: leadDetailKeys.profile(leadId),
    queryFn: () => leadsService.getById(leadId),
    enabled: !!leadId,
  });

  const employeesQuery = useLeadEmployees();

  /**
   * The assignee's display name, or null when unassigned or not in the directory.
   * Resolved here so the profile card never has to know the employee endpoint exists.
   */
  const assigneeName = useMemo<string | null>(() => {
    const lead = query.data;
    if (!lead?.assigned_employee_id) return null;
    const employee = (employeesQuery.data ?? []).find(
      (candidate: EmployeeSummary) => candidate.id === lead.assigned_employee_id
    );
    return employee?.full_name ?? employee?.name ?? null;
  }, [query.data, employeesQuery.data]);

  return {
    lead: query.data ?? null,
    assigneeName,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    refetch: query.refetch,
  };
};

/**
 * Editing a lead, used by both the Edit Lead dialog and the Status Panel.
 *
 * On success it invalidates the lead's whole `detail(id)` subtree — profile, timeline,
 * notes and follow-ups — because a status change writes a STATUS_CHANGED activity that
 * the timeline must pick up, and the dashboard counters that are derived from lead
 * statuses go stale too.
 */
export const useUpdateLead = (leadId: string) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: LeadUpdatePayload) => leadsService.update(leadId, payload),
    onSuccess: (updated: Lead) => {
      // Seed the profile cache so the page re-renders from the server's response (and its
      // new `version`) without waiting for the refetch the invalidation below triggers.
      queryClient.setQueryData(leadDetailKeys.profile(leadId), updated);
      queryClient.invalidateQueries({ queryKey: leadDetailKeys.detail(leadId) });
      // The dashboard's per-status counters and lead sample now disagree with the server.
      queryClient.invalidateQueries({ queryKey: leadKeys.summary() });
      queryClient.invalidateQueries({ queryKey: leadKeys.sample() });
    },
  });
};

/**
 * Changing only the lead's status.
 *
 * A thin wrapper over `useUpdateLead` that exists so the Status Panel does not have to
 * assemble an update payload or remember to send `version`. Sending the version means a
 * status change made from a stale page fails loudly with a 409 rather than silently
 * clobbering a concurrent edit.
 */
export const useUpdateLeadStatus = (leadId: string) => {
  const mutation = useUpdateLead(leadId);

  return {
    ...mutation,
    updateStatus: (status: LeadStatus, version?: number) =>
      mutation.mutateAsync({ status, ...(version !== undefined ? { version } : {}) }),
  };
};

// ==========================================
// 2. ACTIVITY TIMELINE
// ==========================================

/**
 * The lead's activity timeline, newest first, with Load More.
 *
 * Pages are accumulated rather than replaced: `pageCount` grows by one per "Load More"
 * and every page 0..n-1 is fetched in parallel by `useQueries`, then concatenated. Each
 * page is its own cache entry, so loading page 3 never refetches pages 1 and 2, and an
 * invalidation after (say) adding a note correctly refreshes all the loaded pages.
 *
 * `total` comes from the envelope and is what decides whether `hasMore` is true — the UI
 * never has to guess by checking whether the last page came back short.
 */
export const useLeadActivities = (leadId: string, pageSize = ACTIVITY_PAGE_SIZE) => {
  const [pageCount, setPageCount] = useState(1);

  const pageQueries = useQueries({
    queries: Array.from({ length: pageCount }, (_, page) => ({
      queryKey: leadDetailKeys.activityPage(leadId, page * pageSize),
      queryFn: () =>
        leadActivitiesService.list(leadId, { skip: page * pageSize, limit: pageSize }),
      enabled: !!leadId,
    })),
  });

  const activities = useMemo<LeadActivity[]>(() => {
    const rows: LeadActivity[] = [];
    pageQueries.forEach((query) => {
      const data = query.data as Paginated<LeadActivity> | undefined;
      if (data?.items) rows.push(...data.items);
    });
    // De-duplicate defensively: a new activity written between two page fetches shifts
    // every later row down by one, which can otherwise surface the same id twice and
    // trigger duplicate-key warnings in the list.
    const seen = new Set<string>();
    return rows.filter((activity) => {
      if (seen.has(activity.id)) return false;
      seen.add(activity.id);
      return true;
    });
  }, [pageQueries]);

  // `total` is authoritative and identical on every page, so the first page that has
  // loaded answers it.
  const total =
    (pageQueries.find((query) => query.data)?.data as Paginated<LeadActivity> | undefined)?.total ??
    0;

  const isLoading = pageQueries.some((query) => query.isLoading);
  const isError = pageQueries.some((query) => query.isError);

  const loadMore = useCallback(() => setPageCount((count) => count + 1), []);

  const refetch = useCallback(() => {
    pageQueries.forEach((query) => query.refetch());
  }, [pageQueries]);

  return {
    activities,
    total,
    isLoading,
    isError,
    isEmpty: !isLoading && !isError && activities.length === 0,
    hasMore: activities.length < total,
    isLoadingMore: pageCount > 1 && isLoading,
    loadMore,
    refetch,
  };
};

// ==========================================
// 3. NOTES
// ==========================================

/** The lead's notes, newest first, each joined to its author's display name. */
export const useLeadNotes = (leadId: string) => {
  const query = useQuery({
    queryKey: leadDetailKeys.notes(leadId),
    queryFn: () => leadNotesService.list(leadId),
    enabled: !!leadId,
  });

  const employeesQuery = useLeadEmployees();

  /**
   * Author names resolved from the employee directory. A note whose author record was
   * removed (the FK is ON DELETE SET NULL) degrades to null rather than dropping the note.
   */
  const authorNames = useMemo<Record<string, string>>(() => {
    const names: Record<string, string> = {};
    (employeesQuery.data ?? []).forEach((employee: EmployeeSummary) => {
      const name = employee.full_name ?? employee.name;
      if (name) names[employee.id] = name;
    });
    return names;
  }, [employeesQuery.data]);

  return {
    notes: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    authorNames,
    isLoading: query.isLoading,
    isError: query.isError,
    isEmpty: !query.isLoading && !query.isError && (query.data?.items?.length ?? 0) === 0,
    refetch: query.refetch,
  };
};

/**
 * The three note mutations, sharing one invalidation rule.
 *
 * Adding a note also writes a NOTE entry to the timeline server-side, so the activities
 * subtree is invalidated alongside the notes list. Editing and deleting deliberately do
 * NOT write timeline entries (the backend treats an edit as a correction and preserves
 * the original NOTE entry), but they are invalidated the same way for simplicity — a
 * redundant refetch is cheaper than a stale timeline.
 */
const useNoteMutation = <TArgs>(
  leadId: string,
  mutationFn: (args: TArgs) => Promise<unknown>
) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: leadDetailKeys.notes(leadId) });
      queryClient.invalidateQueries({ queryKey: leadDetailKeys.activities(leadId) });
    },
  });
};

/** Adding a note. Also appends a NOTE entry to the timeline server-side. */
export const useCreateLeadNote = (leadId: string) =>
  useNoteMutation<string>(leadId, (note) => leadNotesService.create(leadId, note));

/** Editing a note body. */
export const useUpdateLeadNote = (leadId: string) =>
  useNoteMutation<{ noteId: string; note: string }>(leadId, ({ noteId, note }) =>
    leadNotesService.update(noteId, note)
  );

/** Soft-deleting a note. The timeline entry announcing it is preserved server-side. */
export const useDeleteLeadNote = (leadId: string) =>
  useNoteMutation<string>(leadId, (noteId) => leadNotesService.remove(noteId));

// ==========================================
// 4. FOLLOW-UPS
// ==========================================

/**
 * Every follow-up about this lead — open, completed and cancelled alike.
 *
 * Sorted client-side into worklist order: overdue first (most overdue at the top), then
 * other open tasks by soonest due, then closed tasks by most recently due. The backend
 * orders by due date and priority only, which would bury an overdue task below a
 * completed one scheduled for tomorrow.
 */
export const useLeadFollowUps = (leadId: string) => {
  const query = useQuery({
    queryKey: leadDetailKeys.followUps(leadId),
    queryFn: () => followUpsService.listByLead(leadId),
    enabled: !!leadId,
  });

  const employeesQuery = useLeadEmployees();

  const assigneeNames = useMemo<Record<string, string>>(() => {
    const names: Record<string, string> = {};
    (employeesQuery.data ?? []).forEach((employee: EmployeeSummary) => {
      const name = employee.full_name ?? employee.name;
      if (name) names[employee.id] = name;
    });
    return names;
  }, [employeesQuery.data]);

  const followUps = useMemo<FollowUpTask[]>(() => {
    const rows = [...(query.data?.items ?? [])];
    const isOpen = (task: FollowUpTask) =>
      task.status === 'PENDING' || task.status === 'OVERDUE';

    return rows.sort((a, b) => {
      // `is_overdue` is computed server-side and stays truthful even when the stored
      // status still reads PENDING (there is no background sweeper).
      const aOverdue = a.is_overdue && isOpen(a);
      const bOverdue = b.is_overdue && isOpen(b);
      if (aOverdue !== bOverdue) return aOverdue ? -1 : 1;

      const aOpen = isOpen(a);
      const bOpen = isOpen(b);
      if (aOpen !== bOpen) return aOpen ? -1 : 1;

      const aTime = dayjs(a.scheduled_at).valueOf();
      const bTime = dayjs(b.scheduled_at).valueOf();
      // Open tasks: soonest first. Closed tasks: most recent first.
      return aOpen ? aTime - bTime : bTime - aTime;
    });
  }, [query.data]);

  const overdueCount = useMemo(
    () =>
      followUps.filter(
        (task) => task.is_overdue && (task.status === 'PENDING' || task.status === 'OVERDUE')
      ).length,
    [followUps]
  );

  return {
    followUps,
    total: query.data?.total ?? 0,
    overdueCount,
    assigneeNames,
    isLoading: query.isLoading,
    isError: query.isError,
    isEmpty: !query.isLoading && !query.isError && followUps.length === 0,
    refetch: query.refetch,
  };
};

/**
 * The four follow-up lifecycle mutations, sharing one invalidation rule.
 *
 * Every one of them writes a timeline entry server-side (TASK_CREATED, TASK_COMPLETED,
 * TASK_RESCHEDULED, TASK_CANCELLED), so the activities subtree is invalidated alongside
 * this lead's follow-up list. The dashboard's today/statistics queries are invalidated
 * too, since a task completed here is a task gone from the global worklist.
 */
const useFollowUpMutation = <TArgs>(
  leadId: string,
  mutationFn: (args: TArgs) => Promise<unknown>
) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: leadDetailKeys.followUps(leadId) });
      queryClient.invalidateQueries({ queryKey: leadDetailKeys.activities(leadId) });
      queryClient.invalidateQueries({ queryKey: leadKeys.followUpsToday() });
      queryClient.invalidateQueries({ queryKey: leadKeys.followUpStats() });
    },
  });
};

/** Creating a follow-up against this lead. */
export const useCreateLeadFollowUp = (leadId: string) =>
  useFollowUpMutation<Omit<FollowUpCreatePayload, 'lead_id'>>(leadId, (payload) =>
    followUpsService.create({ ...payload, lead_id: leadId })
  );

/** Marking a follow-up complete. */
export const useCompleteLeadFollowUp = (leadId: string) =>
  useFollowUpMutation<{ id: string; payload?: FollowUpCompletePayload }>(
    leadId,
    ({ id, payload }) => followUpsService.complete(id, payload ?? {})
  );

/** Moving a follow-up to a new due time. */
export const useRescheduleLeadFollowUp = (leadId: string) =>
  useFollowUpMutation<{ id: string; payload: FollowUpReschedulePayload }>(
    leadId,
    ({ id, payload }) => followUpsService.reschedule(id, payload)
  );

/** Cancelling a follow-up, preserving it on the timeline. */
export const useCancelLeadFollowUp = (leadId: string) =>
  useFollowUpMutation<{ id: string; payload?: FollowUpCancelPayload }>(
    leadId,
    ({ id, payload }) => followUpsService.cancel(id, payload ?? {})
  );

// ==========================================
// 5. WHATSAPP HISTORY
// ==========================================

/**
 * This lead's WhatsApp campaign history, newest message first.
 *
 * Assembled by fetching the most recent campaigns and then each campaign's recipient
 * rows, keeping only the row belonging to this lead. See the module docstring for why
 * this fan-out is unavoidable. `isSampled` reports whether the campaign list was
 * truncated, so the UI can say the history covers only recent campaigns rather than
 * implying it is complete.
 */
export const useLeadWhatsAppHistory = (
  leadId: string,
  campaignLimit = LEAD_CAMPAIGN_HISTORY_LIMIT
) => {
  const campaignsQuery = useQuery({
    queryKey: [...leadDetailKeys.whatsapp(leadId), 'campaigns', campaignLimit] as const,
    queryFn: () => campaignsService.list(campaignLimit),
    enabled: !!leadId,
  });

  const campaigns = campaignsQuery.data?.items ?? [];

  const recipientQueries = useQueries({
    queries: campaigns.map((campaign) => ({
      queryKey: [...leadDetailKeys.whatsapp(leadId), 'recipients', campaign.id] as const,
      // Unfiltered by message_status: the history shows every state this lead's message
      // reached, not only replies.
      queryFn: () => campaignsService.recipients(campaign.id),
      enabled: !!campaign.id && !!leadId,
    })),
  });

  const history = useMemo<LeadWhatsAppHistoryEntry[]>(() => {
    const rows: LeadWhatsAppHistoryEntry[] = [];

    recipientQueries.forEach((query, index) => {
      const campaign = campaigns[index];
      const data = query.data as Paginated<CampaignRecipient> | undefined;
      if (!campaign || !data) return;

      data.items
        .filter((recipient) => recipient.lead_id === leadId)
        .forEach((recipient) => {
          rows.push({
            recipientId: recipient.id,
            campaignId: campaign.id,
            campaignName: campaign.name,
            messageStatus: recipient.message_status,
            sentAt: recipient.sent_at,
            deliveredAt: recipient.delivered_at,
            readAt: recipient.read_at,
            repliedAt: recipient.replied_at,
            replyText: recipient.reply_text,
            errorMessage: recipient.error_message,
          });
        });
    });

    return rows.sort((a, b) => {
      // Order by the most recent thing that happened to each message, so a lead that
      // replied to an old campaign still sorts above one merely sent a newer one.
      const latest = (row: LeadWhatsAppHistoryEntry) =>
        Math.max(
          row.repliedAt ? dayjs(row.repliedAt).valueOf() : 0,
          row.readAt ? dayjs(row.readAt).valueOf() : 0,
          row.deliveredAt ? dayjs(row.deliveredAt).valueOf() : 0,
          row.sentAt ? dayjs(row.sentAt).valueOf() : 0
        );
      return latest(b) - latest(a);
    });
  }, [recipientQueries, campaigns, leadId]);

  const isLoading = campaignsQuery.isLoading || recipientQueries.some((query) => query.isLoading);
  const isError = campaignsQuery.isError || recipientQueries.some((query) => query.isError);

  const refetch = useCallback(() => {
    campaignsQuery.refetch();
    recipientQueries.forEach((query) => query.refetch());
  }, [campaignsQuery, recipientQueries]);

  return {
    history,
    isLoading,
    isError,
    isEmpty: !isLoading && !isError && history.length === 0,
    /** True when there may be older campaigns this fan-out did not visit. */
    isSampled: (campaignsQuery.data?.total ?? 0) > campaigns.length,
    refetch,
  };
};
