/**
 * src/features/leads/hooks.ts
 *
 * Business logic for the Lead CRM dashboard. Components in this feature render what
 * these hooks return and nothing more — every fan-out, join, aggregation and date
 * calculation happens here, which is what keeps the widgets dumb enough to unit test.
 *
 * Two shapes recur, both forced by the API surface rather than chosen:
 *
 *  - Counts are fetched one request per status (`useLeadSummary`), because no endpoint
 *    returns a status histogram. Each is a `limit=1` call read for its `total`, and
 *    TanStack Query issues them concurrently.
 *  - Replies are assembled by fanning out over recent campaigns (`useRecentReplies`),
 *    because reply text is only reachable per-campaign. This is an N+1 by necessity and
 *    is bounded by RECENT_CAMPAIGN_LIMIT.
 */

import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient, useQueries } from '@tanstack/react-query';
import dayjs from 'dayjs';
import {
  campaignsService,
  followUpsService,
  leadEmployeesService,
  leadImportsService,
  leadsService,
} from '../../services/leads';
import {
  CampaignPerformanceDatum,
  CampaignRecipient,
  ChartDatum,
  DailyGrowthDatum,
  EmployeeSummary,
  FollowUpCompletePayload,
  FollowUpReschedulePayload,
  Lead,
  LeadSummaryCounts,
  Paginated,
  RecentReply,
  TodayFollowUp,
  WhatsAppCampaign,
} from './types';

/** How many recent campaigns the replies fan-out will visit. Bounds the N+1. */
export const RECENT_CAMPAIGN_LIMIT = 5;

/** How many assembled replies the Recent Replies widget shows. */
export const RECENT_REPLIES_LIMIT = 8;

/** How many days of history the Daily Lead Growth chart plots. */
export const GROWTH_WINDOW_DAYS = 14;

/**
 * Ceiling on the lead sample used for the source/growth charts.
 *
 * The API caps `limit` at 500, and there is no aggregation endpoint, so these two charts
 * describe the most recent 500 leads rather than the whole table. `useLeadCharts`
 * returns `isSampled` so the UI can say so instead of implying a full-table figure.
 */
export const CHART_SAMPLE_LIMIT = 500;

export const leadKeys = {
  all: ['leads'] as const,
  summary: () => [...leadKeys.all, 'summary'] as const,
  count: (status?: string) => [...leadKeys.all, 'count', status ?? 'ALL'] as const,
  sample: () => [...leadKeys.all, 'sample'] as const,
  followUpsToday: () => [...leadKeys.all, 'followups', 'today'] as const,
  followUpStats: () => [...leadKeys.all, 'followups', 'statistics'] as const,
  imports: () => [...leadKeys.all, 'imports'] as const,
  campaigns: () => [...leadKeys.all, 'campaigns'] as const,
  campaignReplies: (ids: string[]) => [...leadKeys.all, 'campaign-replies', ...ids] as const,
  employees: () => [...leadKeys.all, 'employees'] as const,
};

// ==========================================
// 1. LEAD SUMMARY CARDS
// ==========================================

/**
 * The eight headline counters.
 *
 * Seven come from `GET /leads` count probes (one unfiltered for Total, six by status);
 * "Follow-up Today" comes from `GET /followups/statistics.due_today`, which counts tasks
 * due today rather than leads sitting in the FOLLOW_UP status — those are different
 * questions, and the card is labelled for the former.
 */
export const useLeadSummary = () => {
  const countQueries = useQueries({
    queries: [
      { queryKey: leadKeys.count(), queryFn: () => leadsService.count() },
      { queryKey: leadKeys.count('NEW'), queryFn: () => leadsService.count({ status: 'NEW' }) },
      {
        queryKey: leadKeys.count('MESSAGE_SENT'),
        queryFn: () => leadsService.count({ status: 'MESSAGE_SENT' }),
      },
      {
        queryKey: leadKeys.count('REPLIED'),
        queryFn: () => leadsService.count({ status: 'REPLIED' }),
      },
      {
        queryKey: leadKeys.count('INTERESTED'),
        queryFn: () => leadsService.count({ status: 'INTERESTED' }),
      },
      {
        queryKey: leadKeys.count('NEGOTIATION'),
        queryFn: () => leadsService.count({ status: 'NEGOTIATION' }),
      },
      { queryKey: leadKeys.count('LOST'), queryFn: () => leadsService.count({ status: 'LOST' }) },
    ],
  });

  const statsQuery = useQuery({
    queryKey: leadKeys.followUpStats(),
    queryFn: followUpsService.statistics,
  });

  const [total, newLeads, messageSent, replied, interested, negotiation, lost] = countQueries;

  const isLoading = countQueries.some((q) => q.isLoading) || statsQuery.isLoading;
  const isError = countQueries.some((q) => q.isError) || statsQuery.isError;
  const isFetching = countQueries.some((q) => q.isFetching) || statsQuery.isFetching;

  const counts: LeadSummaryCounts = {
    total: total.data ?? 0,
    new: newLeads.data ?? 0,
    messageSent: messageSent.data ?? 0,
    replied: replied.data ?? 0,
    interested: interested.data ?? 0,
    negotiation: negotiation.data ?? 0,
    followUpToday: statsQuery.data?.due_today ?? 0,
    lost: lost.data ?? 0,
  };

  /** True only when every probe succeeded and each returned zero — a genuinely empty CRM. */
  const isEmpty = !isLoading && !isError && counts.total === 0;

  const refetch = () => {
    countQueries.forEach((q) => q.refetch());
    statsQuery.refetch();
  };

  return { counts, isLoading, isError, isFetching, isEmpty, refetch };
};

// ==========================================
// 2. RECENT REPLIES
// ==========================================

/** Newest campaigns, the entry point for both the replies fan-out and the funnel chart. */
export const useRecentCampaigns = (limit = RECENT_CAMPAIGN_LIMIT) =>
  useQuery({
    queryKey: [...leadKeys.campaigns(), limit],
    queryFn: () => campaignsService.list(limit),
  });

/**
 * Latest WhatsApp replies across recent campaigns.
 *
 * Steps: list recent campaigns -> fetch each one's REPLIED recipients -> resolve each
 * recipient's lead for its name and current status -> flatten, sort by `replied_at`
 * descending, and truncate. Lead lookups reuse the cached chart sample where possible,
 * so the common case costs no extra requests.
 */
export const useRecentReplies = (limit = RECENT_REPLIES_LIMIT) => {
  const campaignsQuery = useRecentCampaigns();
  const campaigns = campaignsQuery.data?.items ?? [];

  const recipientQueries = useQueries({
    queries: campaigns.map((campaign) => ({
      queryKey: [...leadKeys.all, 'replies', campaign.id] as const,
      queryFn: () => campaignsService.recipients(campaign.id, 'REPLIED'),
      enabled: !!campaign.id,
    })),
  });

  // The lead sample doubles as a name/status lookup table for the replies below.
  const leadsQuery = useQuery({
    queryKey: leadKeys.sample(),
    queryFn: () => leadsService.list({ skip: 0, limit: CHART_SAMPLE_LIMIT }),
  });

  const replies = useMemo<RecentReply[]>(() => {
    const leadsById = new Map<string, Lead>(
      (leadsQuery.data?.items ?? []).map((lead) => [lead.id, lead])
    );

    const rows: RecentReply[] = [];
    recipientQueries.forEach((query, index) => {
      const campaign = campaigns[index];
      if (!campaign || !query.data) return;

      (query.data as Paginated<CampaignRecipient>).items.forEach((recipient) => {
        const lead = leadsById.get(recipient.lead_id);
        rows.push({
          recipientId: recipient.id,
          leadId: recipient.lead_id,
          // Falls back to the phone number when the lead is outside the cached sample:
          // showing the number beats showing "Unknown".
          leadName: lead?.business_name ?? recipient.phone,
          phone: lead?.whatsapp ?? lead?.phone ?? recipient.phone,
          replyText: recipient.reply_text,
          repliedAt: recipient.replied_at,
          leadStatus: lead?.status ?? null,
          campaignId: campaign.id,
          campaignName: campaign.name,
        });
      });
    });

    return rows
      .sort((a, b) => {
        // Rows without a timestamp sort last rather than corrupting the ordering.
        const aTime = a.repliedAt ? dayjs(a.repliedAt).valueOf() : 0;
        const bTime = b.repliedAt ? dayjs(b.repliedAt).valueOf() : 0;
        return bTime - aTime;
      })
      .slice(0, limit);
  }, [recipientQueries, campaigns, leadsQuery.data, limit]);

  const isLoading =
    campaignsQuery.isLoading ||
    leadsQuery.isLoading ||
    recipientQueries.some((q) => q.isLoading);
  const isError = campaignsQuery.isError || recipientQueries.some((q) => q.isError);

  const refetch = () => {
    campaignsQuery.refetch();
    leadsQuery.refetch();
    recipientQueries.forEach((q) => q.refetch());
  };

  return { replies, isLoading, isError, isEmpty: !isLoading && !isError && replies.length === 0, refetch };
};

// ==========================================
// 3. TODAY'S FOLLOW-UPS
// ==========================================

/** Employee directory, used only to turn `assigned_employee_id` into a readable name. */
export const useLeadEmployees = () =>
  useQuery({
    queryKey: leadKeys.employees(),
    queryFn: () => leadEmployeesService.list(),
    staleTime: 5 * 60 * 1000,
  });

/**
 * Today's follow-up worklist, each task joined to its lead and assignee.
 *
 * A missing lead or employee degrades to `null` on that one field rather than dropping
 * the row: an unassigned task still needs to appear on the worklist.
 */
export const useTodaysFollowUps = () => {
  const tasksQuery = useQuery({
    queryKey: leadKeys.followUpsToday(),
    queryFn: () => followUpsService.today(),
  });

  const employeesQuery = useLeadEmployees();

  const leadsQuery = useQuery({
    queryKey: leadKeys.sample(),
    queryFn: () => leadsService.list({ skip: 0, limit: CHART_SAMPLE_LIMIT }),
  });

  const followUps = useMemo<TodayFollowUp[]>(() => {
    const leadsById = new Map<string, Lead>(
      (leadsQuery.data?.items ?? []).map((lead) => [lead.id, lead])
    );
    const employeesById = new Map<string, EmployeeSummary>(
      (employeesQuery.data ?? []).map((employee) => [employee.id, employee])
    );

    return (tasksQuery.data?.items ?? []).map((task) => {
      const lead = leadsById.get(task.lead_id);
      const employee = task.assigned_employee_id
        ? employeesById.get(task.assigned_employee_id)
        : undefined;

      return {
        task,
        leadName: lead?.business_name ?? null,
        leadPhone: lead?.whatsapp ?? lead?.phone ?? null,
        assigneeName: employee?.full_name ?? employee?.name ?? null,
      };
    });
  }, [tasksQuery.data, leadsQuery.data, employeesQuery.data]);

  return {
    followUps,
    total: tasksQuery.data?.total ?? 0,
    isLoading: tasksQuery.isLoading,
    isError: tasksQuery.isError,
    isEmpty: !tasksQuery.isLoading && !tasksQuery.isError && followUps.length === 0,
    refetch: tasksQuery.refetch,
  };
};

/**
 * Completing a follow-up.
 *
 * Invalidates the worklist and the statistics together, since "Follow-up Today" on the
 * summary cards is derived from the same statistics call and would otherwise keep
 * showing the pre-completion number.
 */
export const useCompleteFollowUp = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload?: FollowUpCompletePayload }) =>
      followUpsService.complete(id, payload ?? {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: leadKeys.followUpsToday() });
      queryClient.invalidateQueries({ queryKey: leadKeys.followUpStats() });
    },
  });
};

/** Rescheduling a follow-up. Same invalidation reasoning as completion. */
export const useRescheduleFollowUp = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: FollowUpReschedulePayload }) =>
      followUpsService.reschedule(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: leadKeys.followUpsToday() });
      queryClient.invalidateQueries({ queryKey: leadKeys.followUpStats() });
    },
  });
};

// ==========================================
// 4. RECENT LEAD IMPORTS
// ==========================================

/** The most recent import runs, newest first. */
export const useRecentImports = (limit = 5) => {
  const query = useQuery({
    queryKey: [...leadKeys.imports(), limit],
    queryFn: () => leadImportsService.listJobs(limit),
  });

  return {
    imports: query.data?.items ?? [],
    isLoading: query.isLoading,
    isError: query.isError,
    isEmpty: !query.isLoading && !query.isError && (query.data?.items?.length ?? 0) === 0,
    refetch: query.refetch,
  };
};

// ==========================================
// 5. WHATSAPP CAMPAIGN SUMMARY
// ==========================================

/**
 * Recent campaigns plus their per-campaign interested-lead count.
 *
 * "Interested Leads" is not a campaign counter on the backend, so it is computed here:
 * the campaign's recipients are matched against leads currently in INTERESTED status.
 * That count therefore reflects each lead's status now, not at the time of the send.
 */
export const useCampaignSummary = (limit = RECENT_CAMPAIGN_LIMIT) => {
  const campaignsQuery = useRecentCampaigns(limit);
  const campaigns = campaignsQuery.data?.items ?? [];

  const recipientQueries = useQueries({
    queries: campaigns.map((campaign) => ({
      queryKey: [...leadKeys.all, 'recipients', campaign.id] as const,
      queryFn: () => campaignsService.recipients(campaign.id),
      enabled: !!campaign.id,
    })),
  });

  const leadsQuery = useQuery({
    queryKey: leadKeys.sample(),
    queryFn: () => leadsService.list({ skip: 0, limit: CHART_SAMPLE_LIMIT }),
  });

  const rows = useMemo(() => {
    const interestedLeadIds = new Set(
      (leadsQuery.data?.items ?? [])
        .filter((lead) => lead.status === 'INTERESTED')
        .map((lead) => lead.id)
    );

    return campaigns.map((campaign: WhatsAppCampaign, index: number) => {
      const recipients =
        (recipientQueries[index]?.data as Paginated<CampaignRecipient> | undefined)?.items ?? [];
      const interested = recipients.filter((r) => interestedLeadIds.has(r.lead_id)).length;

      return { campaign, interestedLeads: interested };
    });
  }, [campaigns, recipientQueries, leadsQuery.data]);

  return {
    rows,
    isLoading: campaignsQuery.isLoading,
    isError: campaignsQuery.isError,
    isEmpty: !campaignsQuery.isLoading && !campaignsQuery.isError && rows.length === 0,
    refetch: campaignsQuery.refetch,
  };
};

// ==========================================
// 7. CHARTS
// ==========================================

/**
 * Data for the Lead Sources, Lead Status Distribution and Daily Lead Growth charts.
 *
 * All three are derived from one lead sample rather than three requests, since no
 * aggregation endpoint exists. `isSampled` is true when the sample hit its ceiling,
 * meaning the charts describe recent leads only — the UI surfaces that caveat.
 */
export const useLeadCharts = () => {
  const query = useQuery({
    queryKey: leadKeys.sample(),
    queryFn: () => leadsService.list({ skip: 0, limit: CHART_SAMPLE_LIMIT }),
  });

  const leads = useMemo(() => query.data?.items ?? [], [query.data]);

  const sources = useMemo<ChartDatum[]>(() => {
    const tally = new Map<string, number>();
    leads.forEach((lead) => tally.set(lead.source, (tally.get(lead.source) ?? 0) + 1));
    return Array.from(tally.entries())
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value);
  }, [leads]);

  const statusDistribution = useMemo<ChartDatum[]>(() => {
    const tally = new Map<string, number>();
    leads.forEach((lead) => tally.set(lead.status, (tally.get(lead.status) ?? 0) + 1));
    return Array.from(tally.entries())
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value);
  }, [leads]);

  const dailyGrowth = useMemo<DailyGrowthDatum[]>(() => {
    // Seed every day in the window at zero first, so quiet days render as gaps in the
    // line rather than being skipped and distorting the x-axis spacing.
    const buckets = new Map<string, number>();
    const today = dayjs().startOf('day');
    for (let i = GROWTH_WINDOW_DAYS - 1; i >= 0; i--) {
      buckets.set(today.subtract(i, 'day').format('YYYY-MM-DD'), 0);
    }

    leads.forEach((lead) => {
      const day = dayjs(lead.created_at).format('YYYY-MM-DD');
      if (buckets.has(day)) buckets.set(day, (buckets.get(day) ?? 0) + 1);
    });

    return Array.from(buckets.entries()).map(([date, count]) => ({ date, count }));
  }, [leads]);

  return {
    sources,
    statusDistribution,
    dailyGrowth,
    isSampled: leads.length >= CHART_SAMPLE_LIMIT,
    sampleSize: leads.length,
    isLoading: query.isLoading,
    isError: query.isError,
    isEmpty: !query.isLoading && !query.isError && leads.length === 0,
    refetch: query.refetch,
  };
};

/** The Campaign Performance chart's funnel series, read off each campaign's counters. */
export const useCampaignPerformance = (limit = RECENT_CAMPAIGN_LIMIT) => {
  const query = useRecentCampaigns(limit);

  const data = useMemo<CampaignPerformanceDatum[]>(
    () =>
      (query.data?.items ?? []).map((campaign) => ({
        name: campaign.name,
        sent: campaign.total_sent,
        delivered: campaign.total_delivered,
        read: campaign.total_read,
        replied: campaign.total_replied,
      })),
    [query.data]
  );

  return {
    data,
    isLoading: query.isLoading,
    isError: query.isError,
    isEmpty: !query.isLoading && !query.isError && data.length === 0,
    refetch: query.refetch,
  };
};
