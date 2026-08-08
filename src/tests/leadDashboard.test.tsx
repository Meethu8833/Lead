/**
 * src/tests/leadDashboard.test.tsx
 *
 * Unit tests for the Lead CRM dashboard module.
 *
 * The suite is organised by layer, mirroring the architecture:
 *   - services  — that the right URLs and query parameters are sent
 *   - hooks     — the aggregation, join and sort logic, which is where the real
 *                 complexity lives (the replies fan-out, the counters, the chart series)
 *   - widgets   — that each section renders loading, empty and error correctly, and that
 *                 the actions fire
 *   - RBAC      — that sections and quick actions hide without the right permission
 *
 * Recharts is stubbed out: it measures its container, which jsdom reports as 0×0, so the
 * real components would render nothing and warn. The charts' data is verified through
 * the hooks instead, which is where it is actually computed.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as React from 'react';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { renderHook } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import dayjs from 'dayjs';

// Recharts renders nothing meaningful in jsdom (zero-size container), so it is stubbed.
vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: any) => <div data-testid="responsive-container">{children}</div>,
  PieChart: ({ children }: any) => <div data-testid="pie-chart">{children}</div>,
  Pie: ({ children }: any) => <div data-testid="pie">{children}</div>,
  BarChart: ({ children }: any) => <div data-testid="bar-chart">{children}</div>,
  Bar: () => <div data-testid="bar" />,
  LineChart: ({ children }: any) => <div data-testid="line-chart">{children}</div>,
  Line: () => <div data-testid="line" />,
  Cell: () => <div data-testid="cell" />,
  XAxis: () => <div data-testid="xaxis" />,
  YAxis: () => <div data-testid="yaxis" />,
  CartesianGrid: () => <div data-testid="grid" />,
  Tooltip: () => <div data-testid="tooltip" />,
  Legend: () => <div data-testid="legend" />,
}));

import { api } from '../services/api';
import {
  campaignsService,
  followUpsService,
  leadEmployeesService,
  leadsService,
} from '../services/leads';
import {
  useCampaignSummary,
  useLeadCharts,
  useLeadSummary,
  useRecentReplies,
  useTodaysFollowUps,
  GROWTH_WINDOW_DAYS,
} from '../features/leads/hooks';
import { LeadSummaryCards } from '../features/leads/components/LeadSummaryCards';
import { RecentReplies } from '../features/leads/components/RecentReplies';
import { TodaysFollowUps } from '../features/leads/components/TodaysFollowUps';
import { RecentImports } from '../features/leads/components/RecentImports';
import { CampaignSummary } from '../features/leads/components/CampaignSummary';
import { QuickActions } from '../features/leads/components/QuickActions';
import { LeadStatusBadge, humanizeStatus } from '../features/leads/components/LeadStatusBadge';
import { DashboardSection } from '../features/leads/components/DashboardSection';
import { isNavItemActive } from '../layouts/AppLayout';
import { useAuthStore } from '../app/store';
import {
  CampaignRecipient,
  FollowUpTask,
  ImportJob,
  Lead,
  LeadSummaryCounts,
  WhatsAppCampaign,
} from '../features/leads/types';

// ==========================================
// FIXTURES
// ==========================================

const makeLead = (overrides: Partial<Lead> = {}): Lead => ({
  id: 'lead-1',
  business_name: 'Sunrise Studio',
  contact_person: 'Ravi',
  phone: '9876543210',
  whatsapp: '9876543210',
  email: null,
  instagram: null,
  facebook: null,
  youtube: null,
  website: null,
  address: null,
  city: 'Kochi',
  district: 'Ernakulam',
  state: 'Kerala',
  country: 'India',
  latitude: null,
  longitude: null,
  source: 'GOOGLE_MAPS',
  status: 'NEW',
  assigned_employee_id: null,
  remarks: null,
  is_converted: false,
  last_contacted_at: null,
  version: 1,
  created_at: dayjs().toISOString(),
  updated_at: dayjs().toISOString(),
  ...overrides,
});

const makeTask = (overrides: Partial<FollowUpTask> = {}): FollowUpTask => ({
  id: 'task-1',
  lead_id: 'lead-1',
  assigned_employee_id: 'emp-1',
  title: 'Call about album pricing',
  description: null,
  follow_up_type: 'CALL',
  priority: 'HIGH',
  status: 'PENDING',
  scheduled_at: dayjs().hour(14).minute(30).toISOString(),
  completed_at: null,
  remarks: null,
  is_overdue: false,
  version: 1,
  created_at: dayjs().toISOString(),
  updated_at: dayjs().toISOString(),
  ...overrides,
});

const makeCampaign = (overrides: Partial<WhatsAppCampaign> = {}): WhatsAppCampaign => ({
  id: 'camp-1',
  template_id: 'tpl-1',
  name: 'Monsoon Offer',
  description: null,
  status: 'COMPLETED',
  scheduled_at: null,
  started_at: dayjs().toISOString(),
  completed_at: null,
  total_recipients: 100,
  total_sent: 90,
  total_delivered: 85,
  total_read: 60,
  total_replied: 12,
  total_failed: 10,
  created_by: null,
  version: 1,
  created_at: dayjs().toISOString(),
  updated_at: dayjs().toISOString(),
  ...overrides,
});

const makeRecipient = (overrides: Partial<CampaignRecipient> = {}): CampaignRecipient => ({
  id: 'rec-1',
  campaign_id: 'camp-1',
  lead_id: 'lead-1',
  phone: '9876543210',
  message_status: 'REPLIED',
  rendered_message: 'Hello!',
  provider_message_id: null,
  error_message: null,
  reply_text: 'Yes, I am interested in your album packages.',
  sent_at: dayjs().subtract(3, 'hour').toISOString(),
  delivered_at: dayjs().subtract(3, 'hour').toISOString(),
  read_at: dayjs().subtract(2, 'hour').toISOString(),
  replied_at: dayjs().subtract(1, 'hour').toISOString(),
  created_at: dayjs().toISOString(),
  updated_at: dayjs().toISOString(),
  ...overrides,
});

const makeImportJob = (overrides: Partial<ImportJob> = {}): ImportJob => ({
  id: 'job-1',
  provider: 'google_maps',
  query: 'photographers in kochi',
  status: 'COMPLETED',
  started_at: dayjs().subtract(1, 'day').toISOString(),
  completed_at: dayjs().subtract(1, 'day').toISOString(),
  total_found: 120,
  new_leads: 80,
  updated_leads: 10,
  duplicate_leads: 30,
  failed_records: 10,
  error_message: null,
  source_filename: null,
  retry_of_job_id: null,
  created_by: null,
  version: 1,
  created_at: dayjs().subtract(1, 'day').toISOString(),
  updated_at: dayjs().subtract(1, 'day').toISOString(),
  ...overrides,
});

const emptyCounts: LeadSummaryCounts = {
  total: 0,
  new: 0,
  messageSent: 0,
  replied: 0,
  interested: 0,
  negotiation: 0,
  followUpToday: 0,
  lost: 0,
};

/** Paginated envelope helper. */
const page = <T,>(items: T[], total = items.length) => ({ items, total, skip: 0, limit: 100 });

// ==========================================
// HARNESS
// ==========================================

/** A QueryClient with retries off, so an error test fails fast instead of backing off. */
const makeQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider client={makeQueryClient()}>
    <MemoryRouter>{children}</MemoryRouter>
  </QueryClientProvider>
);

const renderWithProviders = (ui: React.ReactElement) => render(ui, { wrapper });

/**
 * Grants the signed-in employee a permission set for RBAC-sensitive components.
 *
 * Wrapped in `act` because writing to the Zustand store re-renders any mounted subscriber
 * outside React's own batching, which React otherwise reports as an unwrapped update.
 */
const setPermissions = (permissions: string[], roleName = 'Operator') => {
  act(() => {
    useAuthStore.setState({
      permissions,
      user: {
        id: 'emp-1',
        role: { id: 'role-1', name: roleName, description: '', is_system: false, created_at: '' },
      } as any,
    });
  });
};

beforeEach(() => {
  vi.restoreAllMocks();
  setPermissions(['*:*'], 'Administrator');
});

afterEach(() => {
  act(() => {
    useAuthStore.setState({ permissions: [], user: null });
  });
});

// ==========================================
// SERVICES
// ==========================================

describe('leadsService', () => {
  it('requests a count with limit=1 and returns only the total', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ data: page([makeLead()], 427) } as any);

    const total = await leadsService.count({ status: 'NEW' });

    expect(total).toBe(427);
    // limit=1 is the whole point of the count probe: the total is computed server-side
    // ignoring pagination, so one row of payload buys an accurate figure.
    expect(getSpy).toHaveBeenCalledWith('/leads', {
      params: { status: 'NEW', skip: 0, limit: 1 },
    });
  });

  it('passes filters straight through to GET /leads', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ data: page([]) } as any);

    await leadsService.list({ status: 'REPLIED', city: 'Kochi', limit: 25 });

    expect(getSpy).toHaveBeenCalledWith('/leads', {
      params: { status: 'REPLIED', city: 'Kochi', limit: 25 },
    });
  });
});

describe('followUpsService', () => {
  it('fetches today’s worklist from /followups/today', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ data: page([makeTask()]) } as any);

    const result = await followUpsService.today();

    expect(getSpy).toHaveBeenCalledWith('/followups/today', { params: { skip: 0, limit: 50 } });
    expect(result.items).toHaveLength(1);
  });

  it('completes a task via PUT /followups/{id}/complete', async () => {
    const putSpy = vi.spyOn(api, 'put').mockResolvedValue({ data: makeTask() } as any);

    await followUpsService.complete('task-9', { remarks: 'Done' });

    expect(putSpy).toHaveBeenCalledWith('/followups/task-9/complete', { remarks: 'Done' });
  });

  it('reschedules a task via PUT /followups/{id}/reschedule', async () => {
    const putSpy = vi.spyOn(api, 'put').mockResolvedValue({ data: makeTask() } as any);
    const when = dayjs().add(2, 'day').toISOString();

    await followUpsService.reschedule('task-9', { scheduled_at: when, remarks: null });

    expect(putSpy).toHaveBeenCalledWith('/followups/task-9/reschedule', {
      scheduled_at: when,
      remarks: null,
    });
  });
});

describe('campaignsService', () => {
  it('filters recipients by message status when fetching replies', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ data: page([makeRecipient()]) } as any);

    await campaignsService.recipients('camp-7', 'REPLIED');

    expect(getSpy).toHaveBeenCalledWith('/whatsapp/campaigns/camp-7/recipients', {
      params: { skip: 0, limit: 100, message_status: 'REPLIED' },
    });
  });

  it('omits the status filter when none is given', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ data: page([]) } as any);

    await campaignsService.recipients('camp-7');

    expect(getSpy).toHaveBeenCalledWith('/whatsapp/campaigns/camp-7/recipients', {
      params: { skip: 0, limit: 100 },
    });
  });
});

describe('leadEmployeesService', () => {
  it('normalises a bare array response to an array', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: [{ id: 'emp-1', full_name: 'Asha' }] } as any);

    await expect(leadEmployeesService.list()).resolves.toEqual([{ id: 'emp-1', full_name: 'Asha' }]);
  });

  it('normalises a paginated envelope response to an array', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      data: page([{ id: 'emp-2', full_name: 'Bala' }]),
    } as any);

    await expect(leadEmployeesService.list()).resolves.toEqual([{ id: 'emp-2', full_name: 'Bala' }]);
  });
});

// ==========================================
// HOOKS
// ==========================================

describe('useLeadSummary', () => {
  it('maps each status probe onto its own counter and takes follow-ups from statistics', async () => {
    // Distinct totals per status prove each card is wired to the right probe rather than
    // all eight accidentally reading the same query.
    const totalsByStatus: Record<string, number> = {
      ALL: 500,
      NEW: 120,
      MESSAGE_SENT: 90,
      REPLIED: 45,
      INTERESTED: 30,
      NEGOTIATION: 12,
      LOST: 60,
    };

    vi.spyOn(api, 'get').mockImplementation((url: string, config?: any) => {
      if (url === '/leads') {
        const status = config?.params?.status ?? 'ALL';
        return Promise.resolve({ data: page([], totalsByStatus[status]) } as any);
      }
      if (url === '/followups/statistics') {
        return Promise.resolve({ data: { due_today: 7 } } as any);
      }
      return Promise.resolve({ data: page([]) } as any);
    });

    const { result } = renderHook(() => useLeadSummary(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.counts).toEqual({
      total: 500,
      new: 120,
      messageSent: 90,
      replied: 45,
      interested: 30,
      negotiation: 12,
      followUpToday: 7,
      lost: 60,
    });
  });

  it('reports empty only when the CRM genuinely holds no leads', async () => {
    vi.spyOn(api, 'get').mockImplementation((url: string) =>
      url === '/followups/statistics'
        ? (Promise.resolve({ data: { due_today: 0 } }) as any)
        : (Promise.resolve({ data: page([], 0) }) as any)
    );

    const { result } = renderHook(() => useLeadSummary(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isEmpty).toBe(true);
  });

  it('surfaces an error rather than reporting zero counts', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('network down'));

    const { result } = renderHook(() => useLeadSummary(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    // The distinction matters: a failed request must not look like an empty pipeline.
    expect(result.current.isEmpty).toBe(false);
  });
});

describe('useRecentReplies', () => {
  it('merges replies across campaigns, joins the lead, and sorts newest first', async () => {
    const oldReply = makeRecipient({
      id: 'rec-old',
      campaign_id: 'camp-1',
      lead_id: 'lead-1',
      replied_at: dayjs().subtract(5, 'hour').toISOString(),
      reply_text: 'Older reply',
    });
    const newReply = makeRecipient({
      id: 'rec-new',
      campaign_id: 'camp-2',
      lead_id: 'lead-2',
      replied_at: dayjs().subtract(10, 'minute').toISOString(),
      reply_text: 'Newer reply',
    });

    vi.spyOn(api, 'get').mockImplementation((url: string) => {
      if (url === '/whatsapp/campaigns') {
        return Promise.resolve({
          data: page([
            makeCampaign({ id: 'camp-1', name: 'Campaign One' }),
            makeCampaign({ id: 'camp-2', name: 'Campaign Two' }),
          ]),
        } as any);
      }
      if (url === '/whatsapp/campaigns/camp-1/recipients') {
        return Promise.resolve({ data: page([oldReply]) } as any);
      }
      if (url === '/whatsapp/campaigns/camp-2/recipients') {
        return Promise.resolve({ data: page([newReply]) } as any);
      }
      if (url === '/leads') {
        return Promise.resolve({
          data: page([
            makeLead({ id: 'lead-1', business_name: 'Sunrise Studio', status: 'REPLIED' }),
            makeLead({ id: 'lead-2', business_name: 'Moonlight Photos', status: 'INTERESTED' }),
          ]),
        } as any);
      }
      return Promise.resolve({ data: page([]) } as any);
    });

    const { result } = renderHook(() => useRecentReplies(), { wrapper });

    await waitFor(() => expect(result.current.replies).toHaveLength(2));

    // Sorted by replied_at descending, regardless of which campaign they came from.
    expect(result.current.replies[0].recipientId).toBe('rec-new');
    expect(result.current.replies[0].leadName).toBe('Moonlight Photos');
    expect(result.current.replies[0].leadStatus).toBe('INTERESTED');
    expect(result.current.replies[0].campaignName).toBe('Campaign Two');
    expect(result.current.replies[1].recipientId).toBe('rec-old');
  });

  it('falls back to the recipient phone when the lead is outside the cached sample', async () => {
    vi.spyOn(api, 'get').mockImplementation((url: string) => {
      if (url === '/whatsapp/campaigns') {
        return Promise.resolve({ data: page([makeCampaign({ id: 'camp-1' })]) } as any);
      }
      if (url === '/whatsapp/campaigns/camp-1/recipients') {
        return Promise.resolve({
          data: page([makeRecipient({ lead_id: 'lead-missing', phone: '9998887777' })]),
        } as any);
      }
      if (url === '/leads') return Promise.resolve({ data: page([]) } as any);
      return Promise.resolve({ data: page([]) } as any);
    });

    const { result } = renderHook(() => useRecentReplies(), { wrapper });

    await waitFor(() => expect(result.current.replies).toHaveLength(1));
    // Showing the number beats showing "Unknown".
    expect(result.current.replies[0].leadName).toBe('9998887777');
    expect(result.current.replies[0].leadStatus).toBeNull();
  });

  it('caps the number of replies returned', async () => {
    const many = Array.from({ length: 20 }, (_, i) =>
      makeRecipient({ id: `rec-${i}`, replied_at: dayjs().subtract(i, 'minute').toISOString() })
    );

    vi.spyOn(api, 'get').mockImplementation((url: string) => {
      if (url === '/whatsapp/campaigns') {
        return Promise.resolve({ data: page([makeCampaign({ id: 'camp-1' })]) } as any);
      }
      if (url === '/whatsapp/campaigns/camp-1/recipients') {
        return Promise.resolve({ data: page(many) } as any);
      }
      return Promise.resolve({ data: page([]) } as any);
    });

    const { result } = renderHook(() => useRecentReplies(5), { wrapper });

    await waitFor(() => expect(result.current.replies.length).toBe(5));
  });
});

describe('useTodaysFollowUps', () => {
  it('joins each task to its lead and assignee', async () => {
    vi.spyOn(api, 'get').mockImplementation((url: string) => {
      if (url === '/followups/today') {
        return Promise.resolve({
          data: page([makeTask({ id: 'task-1', lead_id: 'lead-1', assigned_employee_id: 'emp-9' })]),
        } as any);
      }
      if (url === '/leads') {
        return Promise.resolve({
          data: page([makeLead({ id: 'lead-1', business_name: 'Sunrise Studio', phone: '9876543210' })]),
        } as any);
      }
      if (url === '/employees') {
        return Promise.resolve({ data: [{ id: 'emp-9', full_name: 'Asha Menon' }] } as any);
      }
      return Promise.resolve({ data: page([]) } as any);
    });

    const { result } = renderHook(() => useTodaysFollowUps(), { wrapper });

    await waitFor(() => expect(result.current.followUps).toHaveLength(1));
    expect(result.current.followUps[0].leadName).toBe('Sunrise Studio');
    expect(result.current.followUps[0].assigneeName).toBe('Asha Menon');
  });

  it('keeps an unassigned task on the worklist with a null assignee', async () => {
    vi.spyOn(api, 'get').mockImplementation((url: string) => {
      if (url === '/followups/today') {
        return Promise.resolve({
          data: page([makeTask({ assigned_employee_id: null })]),
        } as any);
      }
      if (url === '/employees') return Promise.resolve({ data: [] } as any);
      return Promise.resolve({ data: page([]) } as any);
    });

    const { result } = renderHook(() => useTodaysFollowUps(), { wrapper });

    await waitFor(() => expect(result.current.followUps).toHaveLength(1));
    // Degrading one field is right; dropping the row would hide real work.
    expect(result.current.followUps[0].assigneeName).toBeNull();
  });
});

describe('useLeadCharts', () => {
  it('tallies sources and statuses, sorted by frequency', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      data: page([
        makeLead({ id: '1', source: 'GOOGLE_MAPS', status: 'NEW' }),
        makeLead({ id: '2', source: 'GOOGLE_MAPS', status: 'NEW' }),
        makeLead({ id: '3', source: 'INSTAGRAM', status: 'REPLIED' }),
      ]),
    } as any);

    const { result } = renderHook(() => useLeadCharts(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.sources).toEqual([
      { name: 'GOOGLE_MAPS', value: 2 },
      { name: 'INSTAGRAM', value: 1 },
    ]);
    expect(result.current.statusDistribution[0]).toEqual({ name: 'NEW', value: 2 });
  });

  it('emits a zero-filled daily series covering the whole window', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      data: page([
        makeLead({ id: '1', created_at: dayjs().toISOString() }),
        makeLead({ id: '2', created_at: dayjs().toISOString() }),
      ]),
    } as any);

    const { result } = renderHook(() => useLeadCharts(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    // Quiet days must be present as zeroes, not omitted, or the x-axis spacing lies.
    expect(result.current.dailyGrowth).toHaveLength(GROWTH_WINDOW_DAYS);
    const today = result.current.dailyGrowth[GROWTH_WINDOW_DAYS - 1];
    expect(today.date).toBe(dayjs().format('YYYY-MM-DD'));
    expect(today.count).toBe(2);
    expect(result.current.dailyGrowth[0].count).toBe(0);
  });

  it('ignores leads created outside the growth window', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      data: page([makeLead({ id: '1', created_at: dayjs().subtract(90, 'day').toISOString() })]),
    } as any);

    const { result } = renderHook(() => useLeadCharts(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.dailyGrowth.every((d) => d.count === 0)).toBe(true);
  });
});

describe('useCampaignSummary', () => {
  it('counts recipients whose lead is currently INTERESTED', async () => {
    vi.spyOn(api, 'get').mockImplementation((url: string) => {
      if (url === '/whatsapp/campaigns') {
        return Promise.resolve({ data: page([makeCampaign({ id: 'camp-1' })]) } as any);
      }
      if (url === '/whatsapp/campaigns/camp-1/recipients') {
        return Promise.resolve({
          data: page([
            makeRecipient({ id: 'r1', lead_id: 'lead-1' }),
            makeRecipient({ id: 'r2', lead_id: 'lead-2' }),
            makeRecipient({ id: 'r3', lead_id: 'lead-3' }),
          ]),
        } as any);
      }
      if (url === '/leads') {
        return Promise.resolve({
          data: page([
            makeLead({ id: 'lead-1', status: 'INTERESTED' }),
            makeLead({ id: 'lead-2', status: 'INTERESTED' }),
            makeLead({ id: 'lead-3', status: 'LOST' }),
          ]),
        } as any);
      }
      return Promise.resolve({ data: page([]) } as any);
    });

    const { result } = renderHook(() => useCampaignSummary(), { wrapper });

    await waitFor(() => expect(result.current.rows).toHaveLength(1));
    await waitFor(() => expect(result.current.rows[0].interestedLeads).toBe(2));
  });
});

// ==========================================
// WIDGETS — STATES
// ==========================================

describe('DashboardSection states', () => {
  it('prefers the error state over loading and empty', () => {
    renderWithProviders(
      <DashboardSection title="Test" isError isLoading isEmpty data-testid="sec">
        <div>content</div>
      </DashboardSection>
    );

    // An error hidden behind a skeleton would look like a slow request forever.
    expect(screen.getByTestId('sec-error')).toBeInTheDocument();
    expect(screen.queryByTestId('sec-loading')).not.toBeInTheDocument();
    expect(screen.queryByText('content')).not.toBeInTheDocument();
  });

  it('prefers loading over empty so an in-flight fetch never reads as "no data"', () => {
    renderWithProviders(
      <DashboardSection title="Test" isLoading isEmpty data-testid="sec">
        <div>content</div>
      </DashboardSection>
    );

    expect(screen.getByTestId('sec-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('sec-empty')).not.toBeInTheDocument();
  });

  it('renders children when settled with data', () => {
    renderWithProviders(
      <DashboardSection title="Test" data-testid="sec">
        <div>content</div>
      </DashboardSection>
    );

    expect(screen.getByText('content')).toBeInTheDocument();
  });

  it('invokes the retry callback from the error state', () => {
    const onRetry = vi.fn();
    renderWithProviders(
      <DashboardSection title="Test" isError onRetry={onRetry} data-testid="sec">
        <div>content</div>
      </DashboardSection>
    );

    fireEvent.click(screen.getByTestId('error-state-retry-button'));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe('LeadSummaryCards', () => {
  const counts: LeadSummaryCounts = {
    total: 1240,
    new: 300,
    messageSent: 210,
    replied: 88,
    interested: 40,
    negotiation: 15,
    followUpToday: 6,
    lost: 120,
  };

  it('renders all eight counters', () => {
    renderWithProviders(<LeadSummaryCards counts={counts} />);

    expect(screen.getAllByTestId('stat-card')).toHaveLength(8);
    ['Total Leads', 'New Leads', 'Message Sent', 'Replied', 'Interested', 'Negotiation', 'Follow-up Today', 'Lost'].forEach(
      (label) => expect(screen.getByText(label)).toBeInTheDocument()
    );
  });

  it('formats large values with thousands separators', () => {
    renderWithProviders(<LeadSummaryCards counts={counts} />);
    expect(screen.getByText('1,240')).toBeInTheDocument();
  });

  it('shows skeletons while loading', () => {
    renderWithProviders(<LeadSummaryCards counts={emptyCounts} isLoading />);
    expect(screen.getAllByTestId('stat-card-skeleton')).toHaveLength(8);
  });

  it('shows an error instead of eight zeroes when the counters fail', () => {
    renderWithProviders(<LeadSummaryCards counts={emptyCounts} isError />);

    expect(screen.getByTestId('lead-summary-error')).toBeInTheDocument();
    expect(screen.queryByTestId('lead-summary-cards')).not.toBeInTheDocument();
  });

  it('shows an empty state prompting the first import', () => {
    renderWithProviders(<LeadSummaryCards counts={emptyCounts} isEmpty />);
    expect(screen.getByTestId('lead-summary-empty')).toBeInTheDocument();
  });
});

describe('RecentReplies', () => {
  const replies = [
    {
      recipientId: 'rec-1',
      leadId: 'lead-1',
      leadName: 'Sunrise Studio',
      phone: '9876543210',
      replyText: 'Yes, please send the pricing.',
      repliedAt: dayjs().subtract(2, 'hour').toISOString(),
      leadStatus: 'REPLIED' as const,
      campaignId: 'camp-1',
      campaignName: 'Monsoon Offer',
    },
  ];

  it('renders name, phone, preview, time, status and an open button', () => {
    renderWithProviders(<RecentReplies replies={replies} />);

    expect(screen.getByTestId('recent-reply-name')).toHaveTextContent('Sunrise Studio');
    expect(screen.getByTestId('recent-reply-phone')).toHaveTextContent('98765 43210');
    expect(screen.getByTestId('recent-reply-preview')).toHaveTextContent('Yes, please send the pricing.');
    expect(screen.getByTestId('recent-reply-time')).toHaveTextContent('2h ago');
    expect(screen.getByTestId('lead-status-badge')).toHaveTextContent('Replied');
    expect(screen.getByTestId('recent-reply-open')).toBeInTheDocument();
  });

  it('links the open button to the lead', () => {
    renderWithProviders(<RecentReplies replies={replies} />);
    expect(screen.getByTestId('recent-reply-open').closest('a')).toHaveAttribute('href', '/leads/lead-1');
  });

  it('truncates a long reply preview', () => {
    const long = 'x'.repeat(300);
    renderWithProviders(
      <RecentReplies replies={[{ ...replies[0], replyText: long }]} />
    );
    expect(screen.getByTestId('recent-reply-preview').textContent!.length).toBeLessThan(200);
  });

  it('handles a reply with no timestamp without crashing', () => {
    renderWithProviders(<RecentReplies replies={[{ ...replies[0], repliedAt: null }]} />);
    expect(screen.getByTestId('recent-reply-time')).toHaveTextContent('Unknown time');
  });

  it('renders empty and error states', () => {
    const { unmount } = renderWithProviders(<RecentReplies replies={[]} isEmpty />);
    expect(screen.getByTestId('recent-replies-empty')).toBeInTheDocument();
    unmount();

    renderWithProviders(<RecentReplies replies={[]} isError />);
    expect(screen.getByTestId('recent-replies-error')).toBeInTheDocument();
  });
});

describe('TodaysFollowUps', () => {
  const followUps = [
    {
      task: makeTask({ id: 'task-1', scheduled_at: dayjs().hour(14).minute(30).toISOString() }),
      leadName: 'Sunrise Studio',
      leadPhone: '9876543210',
      assigneeName: 'Asha Menon',
    },
  ];

  it('renders lead, phone, time, type and assignee', () => {
    renderWithProviders(<TodaysFollowUps followUps={followUps} />);

    expect(screen.getByTestId('followup-lead-name')).toHaveTextContent('Sunrise Studio');
    expect(screen.getByTestId('followup-phone')).toHaveTextContent('98765 43210');
    expect(screen.getByTestId('followup-time')).toHaveTextContent('14:30');
    expect(screen.getByTestId('followup-assignee')).toHaveTextContent('Asha Menon');
    expect(screen.getByTestId('lead-status-badge')).toHaveTextContent('Call');
  });

  it('labels an unassigned task', () => {
    renderWithProviders(
      <TodaysFollowUps followUps={[{ ...followUps[0], assigneeName: null }]} />
    );
    expect(screen.getByTestId('followup-assignee')).toHaveTextContent('Unassigned');
  });

  it('flags an overdue task', () => {
    renderWithProviders(
      <TodaysFollowUps
        followUps={[{ ...followUps[0], task: makeTask({ is_overdue: true }) }]}
      />
    );
    expect(screen.getByTestId('followup-overdue')).toBeInTheDocument();
  });

  it('fires onComplete with the task id', () => {
    const onComplete = vi.fn();
    renderWithProviders(<TodaysFollowUps followUps={followUps} onComplete={onComplete} />);

    fireEvent.click(screen.getByTestId('followup-complete'));
    expect(onComplete).toHaveBeenCalledWith('task-1');
  });

  it('opens the reschedule dialog and submits a future time', async () => {
    const onReschedule = vi.fn();
    renderWithProviders(<TodaysFollowUps followUps={followUps} onReschedule={onReschedule} />);

    fireEvent.click(screen.getByTestId('followup-reschedule'));
    await waitFor(() => expect(screen.getByTestId('reschedule-dialog')).toBeInTheDocument());

    const future = dayjs().add(3, 'day').format('YYYY-MM-DDTHH:mm');
    fireEvent.change(screen.getByTestId('reschedule-datetime-input'), {
      target: { value: future },
    });
    fireEvent.click(screen.getByTestId('reschedule-confirm'));

    await waitFor(() => expect(onReschedule).toHaveBeenCalledTimes(1));
    expect(onReschedule.mock.calls[0][0]).toBe('task-1');
    // The API demands a timezone-aware value, so the local input must be converted.
    expect(onReschedule.mock.calls[0][1]).toContain('T');
  });

  it('rejects a past reschedule time instead of calling the API', async () => {
    const onReschedule = vi.fn();
    renderWithProviders(<TodaysFollowUps followUps={followUps} onReschedule={onReschedule} />);

    fireEvent.click(screen.getByTestId('followup-reschedule'));
    await waitFor(() => expect(screen.getByTestId('reschedule-dialog')).toBeInTheDocument());

    fireEvent.change(screen.getByTestId('reschedule-datetime-input'), {
      target: { value: dayjs().subtract(3, 'day').format('YYYY-MM-DDTHH:mm') },
    });
    fireEvent.click(screen.getByTestId('reschedule-confirm'));

    await waitFor(() => expect(screen.getByTestId('reschedule-error')).toBeInTheDocument());
    expect(onReschedule).not.toHaveBeenCalled();
  });

  it('disables only the row being mutated', () => {
    const twoTasks = [
      followUps[0],
      { ...followUps[0], task: makeTask({ id: 'task-2' }), leadName: 'Moonlight Photos' },
    ];
    renderWithProviders(<TodaysFollowUps followUps={twoTasks} pendingTaskId="task-1" />);

    const buttons = screen.getAllByTestId('followup-complete');
    expect(buttons[0]).toBeDisabled();
    expect(buttons[1]).not.toBeDisabled();
  });

  it('hides the action buttons without update permission', () => {
    renderWithProviders(<TodaysFollowUps followUps={followUps} canUpdate={false} />);
    expect(screen.queryByTestId('followup-complete')).not.toBeInTheDocument();
    expect(screen.queryByTestId('followup-reschedule')).not.toBeInTheDocument();
  });

  it('renders the empty state when nothing is due', () => {
    renderWithProviders(<TodaysFollowUps followUps={[]} isEmpty />);
    expect(screen.getByTestId('todays-followups-empty')).toBeInTheDocument();
  });
});

describe('RecentImports', () => {
  const imports = [makeImportJob()];

  it('renders provider, time, counts and status', () => {
    renderWithProviders(<RecentImports imports={imports} />);

    // "google_maps" is humanised for display.
    expect(screen.getAllByText('Google Maps').length).toBeGreaterThan(0);
    expect(screen.getAllByText('120').length).toBeGreaterThan(0);
    expect(screen.getAllByText('80').length).toBeGreaterThan(0);
    expect(screen.getAllByText('30').length).toBeGreaterThan(0);
    expect(screen.getAllByTestId('lead-status-badge')[0]).toHaveTextContent('Completed');
  });

  it('renders both the desktop table and the mobile card list', () => {
    renderWithProviders(<RecentImports imports={imports} />);
    expect(screen.getByTestId('recent-imports-table')).toBeInTheDocument();
    expect(screen.getByTestId('recent-imports-mobile')).toBeInTheDocument();
  });

  it('falls back to created_at when a run never started', () => {
    renderWithProviders(
      <RecentImports imports={[makeImportJob({ started_at: null })]} />
    );
    // A dash would mean the timestamp column silently lost its value.
    expect(screen.queryAllByText('-')).toHaveLength(0);
  });

  it('renders the empty state', () => {
    renderWithProviders(<RecentImports imports={[]} isEmpty />);
    expect(screen.getByTestId('recent-imports-empty')).toBeInTheDocument();
  });
});

describe('CampaignSummary', () => {
  const rows = [{ campaign: makeCampaign(), interestedLeads: 7 }];

  it('renders the full funnel plus interested leads', () => {
    renderWithProviders(<CampaignSummary rows={rows} />);

    expect(screen.getAllByText('Monsoon Offer').length).toBeGreaterThan(0);
    expect(screen.getAllByText('90').length).toBeGreaterThan(0); // sent
    expect(screen.getAllByText('85').length).toBeGreaterThan(0); // delivered
    expect(screen.getAllByText('60').length).toBeGreaterThan(0); // read
    expect(screen.getAllByText('12').length).toBeGreaterThan(0); // replies
    expect(screen.getByTestId('campaign-summary-interested')).toHaveTextContent('7');
  });

  it('renders the empty state', () => {
    renderWithProviders(<CampaignSummary rows={[]} isEmpty />);
    expect(screen.getByTestId('campaign-summary-empty')).toBeInTheDocument();
  });
});

// ==========================================
// RBAC
// ==========================================

describe('QuickActions RBAC', () => {
  it('renders all four actions for an administrator', () => {
    setPermissions(['*:*'], 'Administrator');
    renderWithProviders(<QuickActions />);

    expect(screen.getByTestId('quick-actions').children).toHaveLength(4);
  });

  it('hides actions the employee lacks permission for', () => {
    setPermissions(['leads:view'], 'Viewer');
    renderWithProviders(<QuickActions />);

    expect(screen.getByText('View Leads')).toBeInTheDocument();
    expect(screen.queryByText('Import Leads')).not.toBeInTheDocument();
    expect(screen.queryByText('Create Campaign')).not.toBeInTheDocument();
    expect(screen.queryByText("Today's Follow-ups")).not.toBeInTheDocument();
  });

  it('renders nothing at all when no action is permitted', () => {
    setPermissions([], 'Viewer');
    const { container } = renderWithProviders(<QuickActions />);

    expect(container.querySelector('[data-testid="quick-actions"]')).toBeNull();
  });

  it('honours wildcard module permissions', () => {
    setPermissions(['leads:*'], 'Viewer');
    renderWithProviders(<QuickActions />);

    expect(screen.getByText('View Leads')).toBeInTheDocument();
    expect(screen.getByText('Import Leads')).toBeInTheDocument();
  });
});

// ==========================================
// HELPERS
// ==========================================

describe('humanizeStatus', () => {
  it('turns an enum member into a readable label', () => {
    expect(humanizeStatus('MESSAGE_SENT')).toBe('Message Sent');
    expect(humanizeStatus('NEW')).toBe('New');
  });
});

describe('LeadStatusBadge', () => {
  it('renders a readable label for a known status', () => {
    renderWithProviders(<LeadStatusBadge status="MESSAGE_SENT" />);
    expect(screen.getByTestId('lead-status-badge')).toHaveTextContent('Message Sent');
  });

  it('renders "Unknown" for a missing status rather than an empty pill', () => {
    renderWithProviders(<LeadStatusBadge status={null} />);
    expect(screen.getByTestId('lead-status-badge')).toHaveTextContent('Unknown');
  });

  it('does not crash on an unrecognised status', () => {
    renderWithProviders(<LeadStatusBadge status="SOMETHING_NEW" />);
    expect(screen.getByTestId('lead-status-badge')).toHaveTextContent('Something New');
  });
});

describe('isNavItemActive', () => {
  const paths = ['/', '/leads', '/leads/import', '/campaigns', '/followups'];

  it('matches the dashboard only at the root', () => {
    expect(isNavItemActive('/', '/', paths)).toBe(true);
    expect(isNavItemActive('/', '/leads', paths)).toBe(false);
  });

  it('keeps a parent active on its own sub-routes', () => {
    expect(isNavItemActive('/leads', '/leads/abc-123', paths)).toBe(true);
  });

  it('yields to a more specific nav path', () => {
    // Without this, "/leads" and "/leads/import" would both highlight at once.
    expect(isNavItemActive('/leads', '/leads/import', paths)).toBe(false);
    expect(isNavItemActive('/leads/import', '/leads/import', paths)).toBe(true);
  });

  it('does not match on a shared string prefix', () => {
    expect(isNavItemActive('/leads', '/leadsomething', paths)).toBe(false);
  });
});
