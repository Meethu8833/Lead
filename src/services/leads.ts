/**
 * src/services/leads.ts
 *
 * All HTTP access for the Lead CRM domain. Per the project's architecture rule, no
 * component or hook talks to axios directly — they call these functions, which own
 * URL shapes, query-parameter names and response typing.
 *
 * Every endpoint used here is read-only except the two follow-up mutations, and none of
 * them required a backend change: this module consumes the API exactly as it already is.
 */

import { api } from './api';
import {
  ActivityType,
  CampaignRecipient,
  EmployeeSummary,
  FollowUpCancelPayload,
  FollowUpCompletePayload,
  FollowUpCreatePayload,
  FollowUpReschedulePayload,
  FollowUpStatistics,
  FollowUpTask,
  ImportJob,
  ImportJobDetail,
  ImportJobListParams,
  ImportProviderList,
  ImportRunPayload,
  ImportStatistics,
  DiscoveryRunPayload,
  DiscoveryRunResult,
  Lead,
  LeadActivity,
  LeadListParams,
  LeadNote,
  LeadStatus,
  LeadUpdatePayload,
  MessageStatus,
  Paginated,
  WhatsAppCampaign,
} from '../features/leads/types';

/**
 * How long an import request may stay open, in milliseconds.
 *
 * Collection runs synchronously on the backend and a 500-record Google Maps run makes
 * hundreds of upstream calls, so these two endpoints need far more headroom than the
 * shared client's default. Applied per-request rather than by widening that default,
 * which would let every ordinary CRUD call hang for minutes.
 */
export const IMPORT_REQUEST_TIMEOUT_MS = 5 * 60 * 1000;

// ==========================================
// LEADS
// ==========================================

export const leadsService = {
  /** GET /leads — paginated, filterable lead list. */
  list: async (params: LeadListParams = {}): Promise<Paginated<Lead>> => {
    const response = await api.get<Paginated<Lead>>('/leads', { params });
    return response.data;
  },

  /**
   * Returns only the number of leads matching a filter.
   *
   * Issued with `limit=1` deliberately: the backend computes `total` ignoring
   * skip/limit, so one row of payload is enough to read an accurate count. This is what
   * makes the eight summary cards cheap despite being eight separate requests.
   */
  count: async (params: Omit<LeadListParams, 'skip' | 'limit'> = {}): Promise<number> => {
    const response = await api.get<Paginated<Lead>>('/leads', {
      params: { ...params, skip: 0, limit: 1 },
    });
    return response.data.total;
  },

  /** GET /leads/{id} — a single lead. */
  getById: async (id: string): Promise<Lead> => {
    const response = await api.get<Lead>(`/leads/${id}`);
    return response.data;
  },

  /**
   * PUT /leads/{id} — partial update of a lead.
   *
   * Backs both the Edit Lead form and the Status Panel, which is why it takes an
   * arbitrary partial rather than a full lead: the status change sends `{status, version}`
   * and nothing else. `version` drives optimistic locking — omitting it skips the check,
   * so callers should pass the version they rendered from.
   */
  update: async (id: string, payload: LeadUpdatePayload): Promise<Lead> => {
    const response = await api.put<Lead>(`/leads/${id}`, payload);
    return response.data;
  },
};

// ==========================================
// LEAD ACTIVITIES (TIMELINE)
// ==========================================

export const leadActivitiesService = {
  /**
   * GET /leads/{id}/activities — the lead's timeline, newest first.
   *
   * The backend caps `limit` at 200. Pagination is by `skip`, and `total` lets the UI
   * decide whether a "Load More" button still has anything to load.
   */
  list: async (
    leadId: string,
    params: { skip?: number; limit?: number; activity_type?: ActivityType } = {}
  ): Promise<Paginated<LeadActivity>> => {
    const { skip = 0, limit = 20, activity_type } = params;
    const response = await api.get<Paginated<LeadActivity>>(`/leads/${leadId}/activities`, {
      params: { skip, limit, ...(activity_type ? { activity_type } : {}) },
    });
    return response.data;
  },
};

// ==========================================
// LEAD NOTES
// ==========================================

/**
 * Notes are addressed under two different roots, mirroring the backend router: the
 * collection hangs off the lead (`/leads/{id}/notes`), while an individual note is
 * mutated by its own identity (`/lead-notes/{id}`).
 */
export const leadNotesService = {
  /** GET /leads/{id}/notes — the lead's notes, newest first. */
  list: async (
    leadId: string,
    params: { skip?: number; limit?: number } = {}
  ): Promise<Paginated<LeadNote>> => {
    const { skip = 0, limit = 50 } = params;
    const response = await api.get<Paginated<LeadNote>>(`/leads/${leadId}/notes`, {
      params: { skip, limit },
    });
    return response.data;
  },

  /** POST /leads/{id}/notes — add a note (also appends a NOTE entry to the timeline). */
  create: async (leadId: string, note: string): Promise<LeadNote> => {
    const response = await api.post<LeadNote>(`/leads/${leadId}/notes`, { note });
    return response.data;
  },

  /** PUT /lead-notes/{id} — edit a note body. */
  update: async (noteId: string, note: string): Promise<LeadNote> => {
    const response = await api.put<LeadNote>(`/lead-notes/${noteId}`, { note });
    return response.data;
  },

  /** DELETE /lead-notes/{id} — soft delete a note. Returns 204, hence no payload. */
  remove: async (noteId: string): Promise<void> => {
    await api.delete(`/lead-notes/${noteId}`);
  },
};

// ==========================================
// FOLLOW-UP TASKS
// ==========================================

export const followUpsService = {
  /** GET /followups/today — open tasks due at some point today, soonest first. */
  today: async (limit = 50): Promise<Paginated<FollowUpTask>> => {
    const response = await api.get<Paginated<FollowUpTask>>('/followups/today', {
      params: { skip: 0, limit },
    });
    return response.data;
  },

  /** GET /followups/statistics — headline follow-up counters and breakdowns. */
  statistics: async (): Promise<FollowUpStatistics> => {
    const response = await api.get<FollowUpStatistics>('/followups/statistics');
    return response.data;
  },

  /**
   * GET /followups?lead_id={id} — every follow-up about one lead.
   *
   * Unfiltered by status on purpose: the Lead Details page shows the complete history of
   * what was planned for this lead, including completed and cancelled tasks, rather than
   * only the open worklist that /followups/today and /followups/overdue return.
   */
  listByLead: async (leadId: string, limit = 50): Promise<Paginated<FollowUpTask>> => {
    const response = await api.get<Paginated<FollowUpTask>>('/followups', {
      params: { skip: 0, limit, lead_id: leadId },
    });
    return response.data;
  },

  /**
   * GET /followups?status=PENDING — the open worklist, soonest due first.
   *
   * Backs the pipeline board's "Follow-up Due" badges, which need the next open task for
   * many leads at once. There is no bulk-by-lead-ids endpoint, so this reads the open
   * queue in one request and the hook indexes it by `lead_id` — see
   * `usePipelineFollowUpDueDates` for what that means for leads far down the queue.
   *
   * The backend orders by `scheduled_at` ascending and caps `limit` at 200, so a truncated
   * response drops the *furthest-off* tasks, which is the right end to lose.
   */
  pending: async (limit = 200): Promise<Paginated<FollowUpTask>> => {
    const response = await api.get<Paginated<FollowUpTask>>('/followups', {
      params: { skip: 0, limit, status: 'PENDING' },
    });
    return response.data;
  },

  /** POST /followups — create a task against a lead. */
  create: async (payload: FollowUpCreatePayload): Promise<FollowUpTask> => {
    const response = await api.post<FollowUpTask>('/followups', payload);
    return response.data;
  },

  /** PUT /followups/{id}/cancel — cancel a task, preserving it on the timeline. */
  cancel: async (id: string, payload: FollowUpCancelPayload = {}): Promise<FollowUpTask> => {
    const response = await api.put<FollowUpTask>(`/followups/${id}/cancel`, payload);
    return response.data;
  },

  /** PUT /followups/{id}/complete — mark a task done. */
  complete: async (id: string, payload: FollowUpCompletePayload = {}): Promise<FollowUpTask> => {
    const response = await api.put<FollowUpTask>(`/followups/${id}/complete`, payload);
    return response.data;
  },

  /** PUT /followups/{id}/reschedule — move a task to a new due time. */
  reschedule: async (id: string, payload: FollowUpReschedulePayload): Promise<FollowUpTask> => {
    const response = await api.put<FollowUpTask>(`/followups/${id}/reschedule`, payload);
    return response.data;
  },
};

// ==========================================
// LEAD IMPORTS
// ==========================================

export const leadImportsService = {
  /** GET /leads/imports — import-run history, newest first. */
  listJobs: async (limit = 5): Promise<Paginated<ImportJob>> => {
    const response = await api.get<Paginated<ImportJob>>('/leads/imports', {
      params: { skip: 0, limit },
    });
    return response.data;
  },

  /**
   * GET /leads/imports — the same history with the backend's full filter surface.
   *
   * Kept alongside `listJobs` rather than replacing it: the dashboard's Recent Imports
   * widget only ever wants "the newest N", and rewriting its call site to pass an object
   * would churn a working screen for no gain.
   */
  listJobsFiltered: async (
    params: ImportJobListParams = {}
  ): Promise<Paginated<ImportJob>> => {
    const { skip = 0, limit = 10, ...rest } = params;
    const response = await api.get<Paginated<ImportJob>>('/leads/imports', {
      params: { skip, limit, ...rest },
    });
    return response.data;
  },

  /** GET /leads/imports/{id} — one run including its per-record diagnostic log. */
  getJob: async (id: string): Promise<ImportJobDetail> => {
    const response = await api.get<ImportJobDetail>(`/leads/imports/${id}`);
    return response.data;
  },

  /** GET /leads/imports/statistics — lifetime aggregates across every run. */
  getStatistics: async (): Promise<ImportStatistics> => {
    const response = await api.get<ImportStatistics>('/leads/imports/statistics');
    return response.data;
  },

  /** GET /leads/import/providers — the live provider registry and its capabilities. */
  listProviders: async (): Promise<ImportProviderList> => {
    const response = await api.get<ImportProviderList>('/leads/import/providers');
    return response.data;
  },

  /**
   * POST /leads/import — runs one query-driven import and returns the finished job.
   *
   * The backend runs collection synchronously, so this request stays open for the whole
   * run and resolves with the completed job rather than an id to poll. That is why the
   * caller gets statistics straight back, and why the mutation needs a longer timeout
   * than the shared client's default.
   */
  runImport: async (payload: ImportRunPayload): Promise<ImportJobDetail> => {
    const response = await api.post<ImportJobDetail>('/leads/import', payload, {
      timeout: IMPORT_REQUEST_TIMEOUT_MS,
    });
    return response.data;
  },

  /**
   * POST /leads/import/csv — uploads a CSV and returns the finished job.
   *
   * `onUploadProgress` is forwarded so the page can show real transfer progress. Note it
   * only describes the upload; once the bytes are sent the server still parses and dedups,
   * which is why the UI switches to an indeterminate state at 100%.
   */
  importCsv: async (
    file: File,
    limit: number,
    onUploadProgress?: (percent: number) => void
  ): Promise<ImportJobDetail> => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('limit', String(limit));

    const response = await api.post<ImportJobDetail>('/leads/import/csv', formData, {
      timeout: IMPORT_REQUEST_TIMEOUT_MS,
      onUploadProgress: (event) => {
        if (!onUploadProgress) return;
        const total = event.total ?? file.size;
        if (!total) return;
        onUploadProgress(Math.min(100, Math.round((event.loaded * 100) / total)));
      },
    });
    return response.data;
  },

  /** POST /leads/imports/{id}/retry — re-runs a failed/partial job as a new job. */
  retryJob: async (id: string): Promise<ImportJobDetail> => {
    const response = await api.post<ImportJobDetail>(
      `/leads/imports/${id}/retry`,
      undefined,
      { timeout: IMPORT_REQUEST_TIMEOUT_MS }
    );
    return response.data;
  },
};

// ==========================================
// LEAD DISCOVERY
// ==========================================

/**
 * How long a discovery run may stay open, in milliseconds.
 *
 * Longer than `IMPORT_REQUEST_TIMEOUT_MS` because discovery is strictly more work than a
 * provider import: it geocodes the city, queries Overpass, and then may fetch one page per
 * discovered website across two enrichment stages. A 200-record run with both stages on is
 * hundreds of sequential network calls, and timing it out client-side would abandon a run
 * the server is still completing — the leads would land with nobody watching.
 */
export const DISCOVERY_REQUEST_TIMEOUT_MS = 10 * 60 * 1000;

export const leadDiscoveryService = {
  /**
   * POST /leads/discover — runs the city pipeline and returns what it did.
   *
   * Synchronous like the import endpoints: the request stays open for the whole run and
   * resolves with the finished result rather than a job id to poll. `radius_km` is dropped
   * from the body entirely when absent so the backend adapter applies its own default.
   */
  discover: async (payload: DiscoveryRunPayload): Promise<DiscoveryRunResult> => {
    const { radius_km, ...rest } = payload;
    const body: Record<string, unknown> = { ...rest };
    if (typeof radius_km === 'number') {
      body.radius_km = radius_km;
    }

    const response = await api.post<DiscoveryRunResult>('/leads/discover', body, {
      timeout: DISCOVERY_REQUEST_TIMEOUT_MS,
    });
    return response.data;
  },
};

// ==========================================
// WHATSAPP CAMPAIGNS
// ==========================================

export const campaignsService = {
  /** GET /whatsapp/campaigns — campaign list, newest first. */
  list: async (limit = 5): Promise<Paginated<WhatsAppCampaign>> => {
    const response = await api.get<Paginated<WhatsAppCampaign>>('/whatsapp/campaigns', {
      params: { skip: 0, limit },
    });
    return response.data;
  },

  /**
   * GET /whatsapp/campaigns/{id}/recipients — one campaign's recipient rows.
   *
   * Filtering to `message_status=REPLIED` is how the Recent Replies section gets its
   * data: reply text lives on the recipient row, and there is no cross-campaign replies
   * endpoint to query instead.
   */
  recipients: async (
    campaignId: string,
    messageStatus?: MessageStatus,
    limit = 100
  ): Promise<Paginated<CampaignRecipient>> => {
    const response = await api.get<Paginated<CampaignRecipient>>(
      `/whatsapp/campaigns/${campaignId}/recipients`,
      { params: { skip: 0, limit, ...(messageStatus ? { message_status: messageStatus } : {}) } }
    );
    return response.data;
  },
};

// ==========================================
// EMPLOYEES (assignee names for the follow-up list)
// ==========================================

export const leadEmployeesService = {
  /**
   * GET /employees — used only to resolve `assigned_employee_id` into a display name.
   *
   * The response envelope differs across deployments (a bare array in some, a paginated
   * envelope in others), so both are normalised to an array here rather than forcing
   * every caller to branch.
   */
  list: async (limit = 200): Promise<EmployeeSummary[]> => {
    const response = await api.get<EmployeeSummary[] | Paginated<EmployeeSummary>>('/employees', {
      params: { skip: 0, limit },
    });
    const data = response.data;
    if (Array.isArray(data)) return data;
    return data?.items ?? [];
  },
};

/**
 * The lead statuses the summary cards count, in display order.
 *
 * Exported so the hook layer and its tests agree on exactly which counts are fetched
 * without duplicating the list.
 */
export const SUMMARY_LEAD_STATUSES: LeadStatus[] = [
  'NEW',
  'MESSAGE_SENT',
  'REPLIED',
  'INTERESTED',
  'NEGOTIATION',
  'LOST',
];

// ==========================================
// LEAD PIPELINE (KANBAN BOARD)
// ==========================================

/**
 * One page of a single pipeline column.
 *
 * The board fetches per column rather than fetching all leads and grouping client-side.
 * That is forced by the API: `GET /leads` caps `limit` at 500 and returns no status
 * histogram, so a client-side grouping would both truncate unpredictably and report
 * column totals that are really "totals within the first 500 rows". One filtered request
 * per column instead gives each column an exact `total` straight from the envelope, and
 * lets a column paginate without disturbing its neighbours.
 */
export const leadPipelineService = {
  /**
   * GET /leads?status=… — one column's page.
   *
   * `params` carries the board-wide filters (search / source / assignee / city /
   * district); `status`, `skip` and `limit` are the column's own. Blank filter values are
   * stripped rather than sent as empty strings, because the backend treats `city=` as a
   * literal empty-string match and would return nothing.
   */
  column: async (
    status: LeadStatus,
    params: Omit<LeadListParams, 'status'> = {}
  ): Promise<Paginated<Lead>> => {
    const { skip = 0, limit = 20, ...filters } = params;

    const cleaned = Object.fromEntries(
      Object.entries(filters).filter(([, value]) => value !== undefined && value !== '')
    );

    const response = await api.get<Paginated<Lead>>('/leads', {
      params: { ...cleaned, status, skip, limit },
    });
    return response.data;
  },

  /**
   * PUT /leads/{id} — the write behind a card drop.
   *
   * Deliberately narrower than `leadsService.update`: a drop may only ever change the
   * status, so this cannot be handed a payload that renames a business by accident.
   * `version` is required, not optional — the board always renders from a fetched lead,
   * so it always has one, and sending it means a drop from a stale board fails with a
   * 409 instead of silently overwriting a concurrent edit.
   */
  moveToStatus: async (id: string, status: LeadStatus, version: number): Promise<Lead> => {
    const response = await api.put<Lead>(`/leads/${id}`, { status, version });
    return response.data;
  },
};
