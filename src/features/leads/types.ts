/**
 * src/features/leads/types.ts
 *
 * Types for the Lead CRM domain. These mirror the backend Pydantic response schemas
 * exactly (app/schemas/lead.py, follow_up.py, import_job.py, whatsapp.py) so that a
 * shape change on the server surfaces here as a TypeScript error rather than as
 * `undefined` at runtime.
 */

// ==========================================
// ENUMS (mirror app/models/lead.py)
// ==========================================

/**
 * CRM lifecycle status of a lead. Mirrors LeadStatus in app/models/lead.py.
 *
 * `CONVERTED` was named `CUSTOMER` until the pipeline board was built; both the enum and
 * the Postgres type were renamed (migration a1f4c7b93e02), so this union is the whole
 * truth — there is no legacy value still reachable over the wire.
 */
export type LeadStatus =
  | 'NEW'
  | 'CONTACTED'
  | 'MESSAGE_SENT'
  | 'REPLIED'
  | 'INTERESTED'
  | 'FOLLOW_UP'
  | 'NEGOTIATION'
  | 'CONVERTED'
  | 'LOST';

/** Origin channel of a lead. Mirrors LeadSource in app/models/lead.py. */
export type LeadSource =
  | 'MANUAL'
  | 'GOOGLE_MAPS'
  | 'INSTAGRAM'
  | 'FACEBOOK'
  | 'JUSTDIAL'
  | 'REFERRAL'
  | 'CSV_IMPORT'
  | 'OTHER';

/** Lifecycle status of a follow-up task. Mirrors FollowUpStatus in app/models/follow_up.py. */
export type FollowUpStatus = 'PENDING' | 'COMPLETED' | 'CANCELLED' | 'OVERDUE';

/** Channel through which a follow-up is performed. Mirrors FollowUpType. */
export type FollowUpType = 'CALL' | 'WHATSAPP' | 'EMAIL' | 'MEETING' | 'VISIT' | 'OTHER';

/** Urgency of a follow-up task. Mirrors FollowUpPriority. */
export type FollowUpPriority = 'LOW' | 'MEDIUM' | 'HIGH' | 'URGENT';

/** Lifecycle status of a lead-import run. Mirrors ImportJobStatus. */
export type ImportJobStatus =
  | 'PENDING'
  | 'RUNNING'
  | 'COMPLETED'
  | 'PARTIAL'
  | 'FAILED'
  | 'CANCELLED';

/** Lifecycle status of a WhatsApp campaign. Mirrors CampaignStatus. */
export type CampaignStatus =
  | 'DRAFT'
  | 'SCHEDULED'
  | 'RUNNING'
  | 'PAUSED'
  | 'COMPLETED'
  | 'CANCELLED'
  | 'FAILED';

/** Per-recipient delivery status. Mirrors MessageStatus. */
export type MessageStatus =
  | 'PENDING'
  | 'QUEUED'
  | 'SENT'
  | 'DELIVERED'
  | 'READ'
  | 'REPLIED'
  | 'FAILED';

// ==========================================
// GENERIC PAGINATION ENVELOPE
// ==========================================

/**
 * Every list endpoint in this API returns the same envelope. `total` is the count
 * ignoring skip/limit, which is what the summary cards read (with limit=1) so that a
 * count never requires downloading the rows it counts.
 */
export interface Paginated<T> {
  items: T[];
  total: number;
  skip: number;
  limit: number;
}

// ==========================================
// LEAD
// ==========================================

/** Mirrors LeadResponse in app/schemas/lead.py. */
export interface Lead {
  id: string;
  business_name: string;
  contact_person: string | null;
  phone: string;
  whatsapp: string | null;
  email: string | null;
  instagram: string | null;
  facebook: string | null;
  youtube: string | null;
  website: string | null;
  address: string | null;
  city: string | null;
  district: string | null;
  state: string | null;
  country: string | null;
  latitude: number | null;
  longitude: number | null;
  source: LeadSource;
  status: LeadStatus;
  assigned_employee_id: string | null;
  remarks: string | null;
  is_converted: boolean;
  /**
   * Maintained server-side by the WhatsApp campaign module (on dispatch and on reply),
   * never written by this client. Null until the lead has been contacted at least once.
   */
  last_contacted_at: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

/**
 * Request body for PUT /leads/{id}. Mirrors LeadUpdate in app/schemas/lead.py.
 *
 * Every field is optional so the form can submit only what changed. `version` carries the
 * lead's current version for optimistic locking — a mismatch returns 409 VERSION_CONFLICT.
 */
export interface LeadUpdatePayload {
  business_name?: string;
  contact_person?: string | null;
  phone?: string;
  whatsapp?: string | null;
  email?: string | null;
  instagram?: string | null;
  facebook?: string | null;
  youtube?: string | null;
  website?: string | null;
  address?: string | null;
  city?: string | null;
  district?: string | null;
  state?: string | null;
  country?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  source?: LeadSource;
  status?: LeadStatus;
  assigned_employee_id?: string | null;
  remarks?: string | null;
  is_converted?: boolean;
  version?: number;
}

/** Query filters accepted by GET /leads. */
export interface LeadListParams {
  skip?: number;
  limit?: number;
  status?: LeadStatus;
  source?: LeadSource;
  district?: string;
  city?: string;
  assigned_employee_id?: string;
  created_from?: string;
  created_to?: string;
  search?: string;
}

// ==========================================
// LEAD ACTIVITY (TIMELINE) & NOTES
// ==========================================

/**
 * Kind of timeline entry. Mirrors ActivityType in app/models/lead_activity.py.
 *
 * Note the naming mismatch against the spec's wording: "Lead Imported" is emitted as
 * CREATED, "Note Added" as NOTE, "Follow-up Created"/"Completed" as TASK_CREATED /
 * TASK_COMPLETED, and "Lead Updated" as UPDATED. The presentation layer maps these.
 */
export type ActivityType =
  | 'CREATED'
  | 'UPDATED'
  | 'WHATSAPP_SENT'
  | 'WHATSAPP_DELIVERED'
  | 'WHATSAPP_READ'
  | 'WHATSAPP_REPLIED'
  | 'PHONE_CALL'
  | 'FOLLOW_UP'
  | 'TASK_CREATED'
  | 'TASK_COMPLETED'
  | 'TASK_RESCHEDULED'
  | 'TASK_CANCELLED'
  | 'MEETING_SCHEDULED'
  | 'NOTE'
  | 'STATUS_CHANGED'
  | 'CONVERTED'
  | 'DELETED';

/**
 * Mirrors LeadActivityResponse in app/schemas/lead_activity.py.
 *
 * The wire field is `metadata`, even though the ORM attribute is `activity_metadata` —
 * the backend schema renames it on serialization to dodge SQLAlchemy's reserved word.
 */
export interface LeadActivity {
  id: string;
  lead_id: string;
  activity_type: ActivityType;
  title: string;
  description: string | null;
  created_by_employee_id: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

/** Mirrors LeadNoteResponse in app/schemas/lead_activity.py. */
export interface LeadNote {
  id: string;
  lead_id: string;
  note: string;
  created_by_employee_id: string | null;
  created_at: string;
  updated_at: string;
}

// ==========================================
// FOLLOW-UP TASK
// ==========================================

/** Mirrors FollowUpTaskResponse in app/schemas/follow_up.py. */
export interface FollowUpTask {
  id: string;
  lead_id: string;
  assigned_employee_id: string | null;
  title: string;
  description: string | null;
  follow_up_type: FollowUpType;
  priority: FollowUpPriority;
  status: FollowUpStatus;
  scheduled_at: string;
  completed_at: string | null;
  remarks: string | null;
  is_overdue: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

/** Mirrors FollowUpStatisticsResponse. */
export interface FollowUpStatistics {
  total: number;
  pending: number;
  completed: number;
  cancelled: number;
  overdue: number;
  due_today: number;
  due_this_week: number;
  completion_rate: number;
  by_status: Record<string, number>;
  by_type: Record<string, number>;
  by_priority: Record<string, number>;
  assigned_employee_id: string | null;
}

/** Request body for PUT /followups/{id}/complete. */
export interface FollowUpCompletePayload {
  remarks?: string | null;
  completed_at?: string | null;
}

/** Request body for PUT /followups/{id}/reschedule. */
export interface FollowUpReschedulePayload {
  scheduled_at: string;
  remarks?: string | null;
}

/** Request body for PUT /followups/{id}/cancel. */
export interface FollowUpCancelPayload {
  remarks?: string | null;
}

/**
 * Request body for POST /followups. Mirrors FollowUpTaskCreate.
 *
 * `lead_id` sits in the body rather than the path because follow-ups are addressed as a
 * top-level `/followups` collection, not as a lead sub-resource.
 */
export interface FollowUpCreatePayload {
  lead_id: string;
  title: string;
  description?: string | null;
  follow_up_type?: FollowUpType;
  priority?: FollowUpPriority;
  scheduled_at: string;
  assigned_employee_id?: string | null;
  remarks?: string | null;
}

// ==========================================
// LEAD IMPORT
// ==========================================

/** Mirrors ImportJobResponse in app/schemas/import_job.py. */
export interface ImportJob {
  id: string;
  provider: string;
  query: string | null;
  status: ImportJobStatus;
  started_at: string | null;
  completed_at: string | null;
  total_found: number;
  new_leads: number;
  updated_leads: number;
  duplicate_leads: number;
  failed_records: number;
  error_message: string | null;
  source_filename: string | null;
  retry_of_job_id: string | null;
  created_by: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

/**
 * Mirrors ImportJobDetailResponse. The detail endpoint is the only one that carries
 * `logs`; the list endpoint omits them deliberately (a thousand-record run carries a
 * thousand entries), which is why this is a separate type rather than an optional field
 * bolted onto every row of the history table.
 */
export interface ImportJobDetail extends ImportJob {
  logs: ImportJobLogEntry[] | null;
}

/**
 * One per-record diagnostic from a run. The backend types this as a free-form dict, so
 * every field is optional here — the UI reads what is present and never assumes a shape.
 */
export interface ImportJobLogEntry {
  [key: string]: unknown;
  level?: string;
  message?: string;
  record?: string;
  reason?: string;
}

/** Mirrors ProviderInfo in app/schemas/import_job.py. */
export interface ImportProvider {
  key: string;
  display_name: string;
  lead_source: string;
  requires_query: boolean;
  requires_file: boolean;
  is_available: boolean;
}

/** Mirrors ProviderListResponse. */
export interface ImportProviderList {
  items: ImportProvider[];
  total: number;
}

/** Mirrors ImportRunRequest — the JSON body of a query-driven import. */
export interface ImportRunPayload {
  provider: string;
  query?: string | null;
  limit: number;
  city?: string | null;
  state?: string | null;
  options?: Record<string, unknown> | null;
}

/** Mirrors ImportStatisticsResponse — lifetime aggregates across every run. */
export interface ImportStatistics {
  total_jobs: number;
  total_found: number;
  new_leads: number;
  updated_leads: number;
  duplicate_leads: number;
  failed_records: number;
  jobs_by_status: Record<string, number>;
}

// ==========================================
// LEAD DISCOVERY (POST /leads/discover)
// ==========================================

/**
 * Mirrors DiscoveryRunRequest in app/schemas/import_job.py.
 *
 * Distinct from `ImportRunPayload` and deliberately so: an import names a *provider* and
 * hands it a free-text query, while discovery names a *place* and runs the fixed
 * city -> Overpass -> website -> contacts -> dedup pipeline. There is no `provider` field
 * here because the pipeline owns its own first stage.
 *
 * `radius_km` is omitted rather than sent as null when the operator leaves it blank, so the
 * backend adapter applies its own default instead of interpreting a None.
 */
export interface DiscoveryRunPayload {
  city: string;
  category?: string | null;
  radius_km?: number;
  limit: number;
  state?: string | null;
  discover_websites: boolean;
  extract_contacts: boolean;
}

/**
 * Outreach priority band, derived from stored fields by the backend.
 *
 * HIGH   a reachable number plus a second channel.
 * MEDIUM a reachable number only.
 * LOW    no number — only a website or social presence.
 * NONE   nothing actionable.
 */
export type ContactQuality = 'HIGH' | 'MEDIUM' | 'LOW' | 'NONE';

/** Mirrors DiscoveryRecord — one lead a run created or enriched. */
export interface DiscoveryRecord {
  id: string;
  business_name: string | null;
  phone: string | null;
  email: string | null;
  city: string | null;
  website: string | null;
  /** Stored contact channels, as written. A merge reports the kept value, not the rejected one. */
  whatsapp: string | null;
  instagram: string | null;
  facebook: string | null;
  youtube: string | null;
  source: string | null;
  /** True only when a source identified the number as a WhatsApp number. */
  is_whatsapp_ready: boolean;
  /** Derived outreach priority band. Never stored. */
  contact_quality: ContactQuality;
  /** Fields this run filled in on an existing lead. Empty for a newly created lead. */
  enriched_fields: string[];
}

/** Mirrors DiscoveryEnrichmentStats — what a run actually landed. */
export interface DiscoveryEnrichment {
  websites_discovered: number;
  contacts_extracted: number;
  emails_found: number;
  phones_found: number;
  whatsapp_found: number;
  instagram_found: number;
  facebook_found: number;
  youtube_found: number;
}

/** Mirrors DiscoveryFailure — one record that could not be stored, and why. */
export interface DiscoveryFailure {
  business_name: string | null;
  reason: string;
}

/** Mirrors DiscoveryStage — one pipeline stage's effect on the batch. */
export interface DiscoveryStage {
  stage: string;
  records_in: number;
  records_enriched: number;
}

/**
 * Mirrors DiscoveryRunResponse.
 *
 * The five counters reconcile: `imported + merged + duplicates + failed === found`. The
 * record arrays stay in step with their counters, which is what lets the results tables
 * show rows rather than only totals. Note there is no `duplicates_records`: a duplicate
 * matched an existing lead and added nothing, so the backend records only its count.
 */
export interface DiscoveryRunResult {
  found: number;
  imported: number;
  duplicates: number;
  merged: number;
  failed: number;
  imported_records: DiscoveryRecord[];
  merged_records: DiscoveryRecord[];
  failed_records: DiscoveryFailure[];
  stages: DiscoveryStage[];
  city: string | null;
  provider: string | null;
  enrichment: DiscoveryEnrichment;
}

/** Filters accepted by `GET /leads/imports`, used by the history table. */
export interface ImportJobListParams {
  skip?: number;
  limit?: number;
  provider?: string;
  status?: ImportJobStatus;
  created_from?: string;
  created_to?: string;
}

// ==========================================
// WHATSAPP CAMPAIGN
// ==========================================

/** Mirrors WhatsAppCampaignResponse in app/schemas/whatsapp.py. */
export interface WhatsAppCampaign {
  id: string;
  template_id: string;
  name: string;
  description: string | null;
  status: CampaignStatus;
  scheduled_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  total_recipients: number;
  total_sent: number;
  total_delivered: number;
  total_read: number;
  total_replied: number;
  total_failed: number;
  created_by: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

/** Mirrors CampaignRecipientResponse. Carries the reply text used by Recent Replies. */
export interface CampaignRecipient {
  id: string;
  campaign_id: string;
  lead_id: string;
  phone: string;
  message_status: MessageStatus;
  rendered_message: string | null;
  provider_message_id: string | null;
  error_message: string | null;
  reply_text: string | null;
  sent_at: string | null;
  delivered_at: string | null;
  read_at: string | null;
  replied_at: string | null;
  created_at: string;
  updated_at: string;
}

// ==========================================
// EMPLOYEE (minimal projection for assignee names)
// ==========================================

/** The subset of the employee record the follow-up list needs to name an assignee. */
export interface EmployeeSummary {
  id: string;
  full_name?: string | null;
  name?: string | null;
  email?: string | null;
}

// ==========================================
// DERIVED / VIEW-MODEL TYPES
// ==========================================

/**
 * One reply row as rendered by the Recent Replies widget.
 *
 * This is assembled on the client rather than returned by any single endpoint: the API
 * exposes replies only per-campaign (GET /whatsapp/campaigns/{id}/recipients), so the
 * hook fans out over recent campaigns and joins each recipient to its lead.
 */
export interface RecentReply {
  recipientId: string;
  leadId: string;
  leadName: string;
  phone: string;
  replyText: string | null;
  repliedAt: string | null;
  leadStatus: LeadStatus | null;
  campaignId: string;
  campaignName: string;
}

/**
 * One row of the Lead Details WhatsApp History table.
 *
 * Assembled client-side by joining a campaign to this lead's recipient row within it,
 * because the API exposes recipients only per-campaign — there is no `lead_id` filter on
 * `GET /whatsapp/campaigns/{id}/recipients` and no lead-scoped message history route.
 * The fan-out is therefore bounded to the most recent campaigns; see
 * `LEAD_CAMPAIGN_HISTORY_LIMIT` in hooks.ts.
 */
export interface LeadWhatsAppHistoryEntry {
  recipientId: string;
  campaignId: string;
  campaignName: string;
  messageStatus: MessageStatus;
  /** Timestamp the message was dispatched; null while still queued/pending. */
  sentAt: string | null;
  deliveredAt: string | null;
  readAt: string | null;
  repliedAt: string | null;
  replyText: string | null;
  errorMessage: string | null;
}

/** One follow-up row enriched with the lead and assignee it refers to. */
export interface TodayFollowUp {
  task: FollowUpTask;
  leadName: string | null;
  leadPhone: string | null;
  assigneeName: string | null;
}

/** The eight headline counters rendered by the Lead Summary Cards section. */
export interface LeadSummaryCounts {
  total: number;
  new: number;
  messageSent: number;
  replied: number;
  interested: number;
  negotiation: number;
  followUpToday: number;
  lost: number;
}

/** A single {name, value} datum, the shape every chart in this module consumes. */
export interface ChartDatum {
  name: string;
  value: number;
}

/** A point on the daily lead-growth series. */
export interface DailyGrowthDatum {
  date: string;
  count: number;
}

/** One campaign's funnel, as plotted by the Campaign Performance chart. */
export interface CampaignPerformanceDatum {
  name: string;
  sent: number;
  delivered: number;
  read: number;
  replied: number;
}

// ==========================================
// LEAD PIPELINE (KANBAN BOARD)
// ==========================================

/**
 * How the board orders the cards inside every column.
 *
 * These map onto client-side comparators rather than API parameters: `GET /leads` accepts
 * no `sort` or `order_by`, so ordering is applied to each fetched page after it arrives.
 * The consequence is documented where it bites — see `sortLeads` in utils.ts.
 */
export type PipelineSort = 'NEWEST' | 'OLDEST' | 'LAST_CONTACTED' | 'NAME';

/**
 * The board-wide filter bar's state.
 *
 * Every field is a plain string (rather than `LeadSource | undefined`, say) because these
 * are bound straight to inputs and selects, where "no choice" is the empty string. The
 * service layer strips the blanks before they reach the query string.
 */
export interface PipelineFilters {
  search: string;
  source: LeadSource | '';
  assigned_employee_id: string;
  city: string;
  district: string;
}

/**
 * One column's slice of board state, as the column component consumes it.
 *
 * `total` is the server's count for this status under the current filters — not
 * `leads.length`, which is only what has been loaded so far. Keeping both is what lets the
 * header read "12 of 47" and the Load More button know whether anything remains.
 */
export interface PipelineColumnState {
  status: LeadStatus;
  leads: Lead[];
  total: number;
  loadedCount: number;
  hasMore: boolean;
  isLoading: boolean;
  isFetchingMore: boolean;
  isError: boolean;
  loadMore: () => void;
}
