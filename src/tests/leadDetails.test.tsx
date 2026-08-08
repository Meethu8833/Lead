/**
 * src/tests/leadDetails.test.tsx
 *
 * Unit tests for the Lead Details workspace.
 *
 * Organised by the layers the architecture separates, and by the six areas the spec
 * names:
 *   - utils     — the pure derivations (Maps URL, contact links, address assembly)
 *   - services  — that the right URLs, bodies and query parameters are sent
 *   - hooks     — the paging accumulation, the WhatsApp fan-out join, the follow-up
 *                 ordering, and the cache invalidation that "refresh all related
 *                 queries" depends on
 *   - sections  — lead profile rendering, timeline loading + Load More, notes CRUD,
 *                 follow-up actions, status updates
 *   - RBAC      — that every mutating control disappears without its permission
 *
 * The API is stubbed at the axios instance (`api.get/put/post/delete`) rather than with a
 * network mock, matching `leadDashboard.test.tsx`: it keeps the service layer under test
 * instead of bypassing it.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as React from 'react';
import { render, screen, waitFor, fireEvent, act, within } from '@testing-library/react';
import { renderHook } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import dayjs from 'dayjs';

import { api } from '../services/api';
import {
  followUpsService,
  leadActivitiesService,
  leadNotesService,
  leadsService,
} from '../services/leads';
import {
  useLead,
  useLeadActivities,
  useLeadFollowUps,
  useLeadNotes,
  useLeadWhatsAppHistory,
} from '../features/leads/detailHooks';
import {
  contactQualityOf,
  externalHref,
  formatAddress,
  isWhatsAppReady,
  instagramHref,
  mailtoHref,
  mapsUrlFor,
  normalizePhone,
  telHref,
  whatsAppHref,
} from '../features/leads/utils';
import { LeadProfileCard } from '../features/leads/components/LeadProfileCard';
import { LeadStatusPanel } from '../features/leads/components/LeadStatusPanel';
import { LeadQuickActions } from '../features/leads/components/LeadQuickActions';
import { LeadActivityTimeline, presentationFor } from '../features/leads/components/LeadActivityTimeline';
import { LeadNotesSection } from '../features/leads/components/LeadNotesSection';
import { LeadFollowUpsSection } from '../features/leads/components/LeadFollowUpsSection';
import { LeadWhatsAppHistory } from '../features/leads/components/LeadWhatsAppHistory';
import { LeadDetailsPage } from '../features/leads/pages/LeadDetailsPage';
import { useAuthStore } from '../app/store';
import {
  ActivityType,
  CampaignRecipient,
  FollowUpTask,
  Lead,
  LeadActivity,
  LeadNote,
  LeadWhatsAppHistoryEntry,
  WhatsAppCampaign,
} from '../features/leads/types';

// ==========================================
// FIXTURES
// ==========================================

const makeLead = (overrides: Partial<Lead> = {}): Lead => ({
  id: 'lead-1',
  business_name: 'Sunrise Studio',
  contact_person: 'Ravi Kumar',
  phone: '+91 98765 43210',
  whatsapp: '9876543210',
  email: 'hello@sunrise.example',
  instagram: '@sunrisestudio',
  facebook: null,
  youtube: null,
  website: 'sunrise.example',
  address: '12 MG Road',
  city: 'Kochi',
  district: 'Ernakulam',
  state: 'Kerala',
  country: 'India',
  latitude: 9.9312,
  longitude: 76.2673,
  source: 'GOOGLE_MAPS',
  status: 'NEW',
  assigned_employee_id: 'emp-1',
  remarks: null,
  is_converted: false,
  last_contacted_at: null,
  version: 3,
  created_at: '2026-01-15T10:00:00.000Z',
  updated_at: '2026-01-15T10:00:00.000Z',
  ...overrides,
});

const makeActivity = (overrides: Partial<LeadActivity> = {}): LeadActivity => ({
  id: 'act-1',
  lead_id: 'lead-1',
  activity_type: 'CREATED',
  title: 'Lead imported from Google Maps',
  description: null,
  created_by_employee_id: null,
  metadata: null,
  created_at: dayjs().subtract(2, 'day').toISOString(),
  ...overrides,
});

const makeNote = (overrides: Partial<LeadNote> = {}): LeadNote => ({
  id: 'note-1',
  lead_id: 'lead-1',
  note: 'Asked for the wedding album price list.',
  created_by_employee_id: 'emp-1',
  created_at: dayjs().subtract(1, 'day').toISOString(),
  updated_at: dayjs().subtract(1, 'day').toISOString(),
  ...overrides,
});

const makeTask = (overrides: Partial<FollowUpTask> = {}): FollowUpTask => ({
  id: 'task-1',
  lead_id: 'lead-1',
  assigned_employee_id: 'emp-1',
  title: 'Call about album pricing',
  description: null,
  follow_up_type: 'CALL',
  priority: 'MEDIUM',
  status: 'PENDING',
  scheduled_at: dayjs().add(1, 'day').toISOString(),
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
  reply_text: 'Yes, send me the packages.',
  sent_at: dayjs().subtract(3, 'hour').toISOString(),
  delivered_at: dayjs().subtract(3, 'hour').toISOString(),
  read_at: dayjs().subtract(2, 'hour').toISOString(),
  replied_at: dayjs().subtract(1, 'hour').toISOString(),
  created_at: dayjs().toISOString(),
  updated_at: dayjs().toISOString(),
  ...overrides,
});

const makeHistoryEntry = (
  overrides: Partial<LeadWhatsAppHistoryEntry> = {}
): LeadWhatsAppHistoryEntry => ({
  recipientId: 'rec-1',
  campaignId: 'camp-1',
  campaignName: 'Monsoon Offer',
  messageStatus: 'REPLIED',
  sentAt: dayjs().subtract(3, 'hour').toISOString(),
  deliveredAt: dayjs().subtract(3, 'hour').toISOString(),
  readAt: dayjs().subtract(2, 'hour').toISOString(),
  repliedAt: dayjs().subtract(1, 'hour').toISOString(),
  replyText: 'Yes, send me the packages.',
  errorMessage: null,
  ...overrides,
});

/** Paginated envelope helper. */
const page = <T,>(items: T[], total = items.length) => ({ items, total, skip: 0, limit: 50 });

// ==========================================
// HARNESS
// ==========================================

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

/** Mounts the page at /leads/lead-1 so `useParams` resolves a real id. */
const renderPage = () =>
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={['/leads/lead-1']}>
        <Routes>
          <Route path="/leads/:id" element={<LeadDetailsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );

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

/**
 * Routes a stubbed GET by URL, so a component that issues six different requests can be
 * driven from one mock without depending on call order.
 */
const stubGet = (routes: Record<string, unknown>, fallback: unknown = page([])) =>
  vi.spyOn(api, 'get').mockImplementation((url: string) => {
    const match = Object.keys(routes).find((key) => url.includes(key));
    return Promise.resolve({ data: match ? routes[match] : fallback } as any);
  });

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
// UTILS
// ==========================================

describe('lead detail utils', () => {
  it('derives a Google Maps URL from latitude and longitude', () => {
    expect(mapsUrlFor(makeLead())).toBe(
      'https://www.google.com/maps/search/?api=1&query=9.9312,76.2673'
    );
  });

  it('returns null for a Maps URL when the lead has no coordinates', () => {
    // There is no google_maps_url column, so a lead without coordinates simply has no
    // link — the profile hides the row rather than rendering a dead one.
    expect(mapsUrlFor(makeLead({ latitude: null, longitude: null }))).toBeNull();
    expect(mapsUrlFor(makeLead({ latitude: 9.93, longitude: null }))).toBeNull();
  });

  it('strips formatting from phone numbers but keeps a leading +', () => {
    expect(normalizePhone('+91 98765-43210')).toBe('+919876543210');
    expect(normalizePhone('(0484) 123 4567')).toBe('04841234567');
    expect(normalizePhone(null)).toBe('');
  });

  it('builds tel: and wa.me links, dropping the + only for wa.me', () => {
    expect(telHref('+91 98765 43210')).toBe('tel:+919876543210');
    // wa.me rejects the leading +.
    expect(whatsAppHref(makeLead({ whatsapp: '+91 98765 43210' }))).toBe(
      'https://wa.me/919876543210'
    );
  });

  it('builds a wa.me link only from the dedicated WhatsApp number, never the phone', () => {
    expect(whatsAppHref(makeLead({ whatsapp: '111111111', phone: '222222222' }))).toBe(
      'https://wa.me/111111111'
    );
    // An ordinary phone number is NOT assumed to be on WhatsApp: the pipeline only fills
    // `whatsapp` when a source identified the number as one. Falling back to `phone` here
    // would send the operator into conversations that do not exist.
    expect(whatsAppHref(makeLead({ whatsapp: null, phone: '222222222' }))).toBeNull();
  });

  it('reports WhatsApp readiness from the whatsapp column alone', () => {
    expect(isWhatsAppReady(makeLead({ whatsapp: '+91 98765 43210' }))).toBe(true);
    expect(isWhatsAppReady(makeLead({ whatsapp: null, phone: '222222222' }))).toBe(false);
    expect(isWhatsAppReady(makeLead({ whatsapp: '   ' }))).toBe(false);
  });

  it('classifies contact quality from stored fields only', () => {
    // A number plus a second channel is the band worth calling first.
    expect(contactQualityOf({ phone: '222222222', website: 'https://a.example' })).toBe('HIGH');
    expect(contactQualityOf({ whatsapp: '111111111', instagram: 'studio' })).toBe('HIGH');
    // A number and nothing else.
    expect(contactQualityOf({ phone: '222222222' })).toBe('MEDIUM');
    // Reachable only through a page.
    expect(contactQualityOf({ website: 'https://a.example' })).toBe('LOW');
    expect(contactQualityOf({ facebook: 'https://fb.example/x' })).toBe('LOW');
    expect(contactQualityOf({})).toBe('NONE');
  });

  it('adds a scheme to schemeless website and instagram values', () => {
    expect(externalHref('sunrise.example')).toBe('https://sunrise.example');
    expect(externalHref('https://sunrise.example')).toBe('https://sunrise.example');
    expect(instagramHref('@sunrisestudio')).toBe('https://instagram.com/sunrisestudio');
    expect(mailtoHref('a@b.example')).toBe('mailto:a@b.example');
    expect(externalHref('   ')).toBeNull();
  });

  it('joins only the address parts that are present', () => {
    expect(formatAddress(makeLead())).toBe('12 MG Road, Kochi, Ernakulam, Kerala, India');
    expect(
      formatAddress(makeLead({ address: null, city: 'Kochi', district: null, state: 'Kerala' }))
    ).toBe('Kochi, Kerala, India');
    expect(
      formatAddress({ address: null, city: null, district: null, state: null, country: null })
    ).toBeNull();
  });
});

// ==========================================
// SERVICES
// ==========================================

describe('lead detail services', () => {
  it('requests the activity timeline with skip/limit', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ data: page([makeActivity()]) } as any);

    await leadActivitiesService.list('lead-1', { skip: 20, limit: 20 });

    expect(getSpy).toHaveBeenCalledWith('/leads/lead-1/activities', {
      params: { skip: 20, limit: 20 },
    });
  });

  it('passes an activity_type filter through only when given', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ data: page([]) } as any);

    await leadActivitiesService.list('lead-1');
    expect(getSpy).toHaveBeenCalledWith('/leads/lead-1/activities', {
      params: { skip: 0, limit: 20 },
    });

    await leadActivitiesService.list('lead-1', { activity_type: 'NOTE' });
    expect(getSpy).toHaveBeenLastCalledWith('/leads/lead-1/activities', {
      params: { skip: 0, limit: 20, activity_type: 'NOTE' },
    });
  });

  it('addresses notes under the lead for the collection and by id for mutations', async () => {
    // Mirrors the backend router's two roots: /leads/{id}/notes vs /lead-notes/{id}.
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: makeNote() } as any);
    const putSpy = vi.spyOn(api, 'put').mockResolvedValue({ data: makeNote() } as any);
    const deleteSpy = vi.spyOn(api, 'delete').mockResolvedValue({ data: null } as any);

    await leadNotesService.create('lead-1', 'A new note');
    await leadNotesService.update('note-1', 'An edited note');
    await leadNotesService.remove('note-1');

    expect(postSpy).toHaveBeenCalledWith('/leads/lead-1/notes', { note: 'A new note' });
    expect(putSpy).toHaveBeenCalledWith('/lead-notes/note-1', { note: 'An edited note' });
    expect(deleteSpy).toHaveBeenCalledWith('/lead-notes/note-1');
  });

  it('fetches a lead’s follow-ups unfiltered by status', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ data: page([makeTask()]) } as any);

    await followUpsService.listByLead('lead-1');

    // No `status` param: the detail page shows completed and cancelled history too.
    expect(getSpy).toHaveBeenCalledWith('/followups', {
      params: { skip: 0, limit: 50, lead_id: 'lead-1' },
    });
  });

  it('sends lead_id in the body when creating a follow-up', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: makeTask() } as any);

    await followUpsService.create({
      lead_id: 'lead-1',
      title: 'Call back',
      scheduled_at: '2026-09-01T10:00:00.000Z',
    });

    expect(postSpy).toHaveBeenCalledWith('/followups', {
      lead_id: 'lead-1',
      title: 'Call back',
      scheduled_at: '2026-09-01T10:00:00.000Z',
    });
  });

  it('PUTs cancel and update to their own endpoints', async () => {
    const putSpy = vi.spyOn(api, 'put').mockResolvedValue({ data: makeTask() } as any);

    await followUpsService.cancel('task-1', { remarks: 'Lead went cold' });
    expect(putSpy).toHaveBeenCalledWith('/followups/task-1/cancel', {
      remarks: 'Lead went cold',
    });

    await leadsService.update('lead-1', { status: 'INTERESTED', version: 3 });
    expect(putSpy).toHaveBeenLastCalledWith('/leads/lead-1', {
      status: 'INTERESTED',
      version: 3,
    });
  });
});

// ==========================================
// HOOKS
// ==========================================

describe('useLead', () => {
  it('resolves the assignee id into a display name', async () => {
    stubGet({
      '/leads/lead-1': makeLead({ assigned_employee_id: 'emp-7' }),
      '/employees': [{ id: 'emp-7', full_name: 'Anita Menon' }],
    });

    const { result } = renderHook(() => useLead('lead-1'), { wrapper });

    await waitFor(() => expect(result.current.assigneeName).toBe('Anita Menon'));
  });

  it('leaves the assignee null when the lead is unassigned', async () => {
    stubGet({
      '/leads/lead-1': makeLead({ assigned_employee_id: null }),
      '/employees': [{ id: 'emp-7', full_name: 'Anita Menon' }],
    });

    const { result } = renderHook(() => useLead('lead-1'), { wrapper });

    await waitFor(() => expect(result.current.lead).not.toBeNull());
    expect(result.current.assigneeName).toBeNull();
  });
});

describe('useLeadActivities', () => {
  it('reports hasMore from the envelope total, not from the page length', async () => {
    stubGet({ '/activities': page([makeActivity()], 45) });

    const { result } = renderHook(() => useLeadActivities('lead-1'), { wrapper });

    await waitFor(() => expect(result.current.activities).toHaveLength(1));
    expect(result.current.total).toBe(45);
    expect(result.current.hasMore).toBe(true);
  });

  it('accumulates pages on Load More instead of replacing them', async () => {
    vi.spyOn(api, 'get').mockImplementation((url: string, config: any) => {
      if (!url.includes('/activities')) return Promise.resolve({ data: page([]) } as any);
      const skip = config?.params?.skip ?? 0;
      return Promise.resolve({
        data: page([makeActivity({ id: `act-${skip}` })], 40),
      } as any);
    });

    const { result } = renderHook(() => useLeadActivities('lead-1'), { wrapper });

    await waitFor(() => expect(result.current.activities).toHaveLength(1));

    act(() => result.current.loadMore());

    await waitFor(() => expect(result.current.activities).toHaveLength(2));
    // Page 2 was fetched at skip=20 and appended below page 1.
    expect(result.current.activities.map((a) => a.id)).toEqual(['act-0', 'act-20']);
  });

  it('de-duplicates a row that shifted between two page fetches', async () => {
    // A new activity written between page 1 and page 2 pushes the boundary row down, so
    // the same id can arrive twice.
    vi.spyOn(api, 'get').mockImplementation((url: string, config: any) => {
      if (!url.includes('/activities')) return Promise.resolve({ data: page([]) } as any);
      const skip = config?.params?.skip ?? 0;
      return Promise.resolve({
        data: page([makeActivity({ id: skip === 0 ? 'act-a' : 'act-a' })], 40),
      } as any);
    });

    const { result } = renderHook(() => useLeadActivities('lead-1'), { wrapper });
    await waitFor(() => expect(result.current.activities).toHaveLength(1));

    act(() => result.current.loadMore());

    await waitFor(() => expect(result.current.total).toBe(40));
    expect(result.current.activities).toHaveLength(1);
  });
});

describe('useLeadFollowUps', () => {
  it('sorts overdue first, then open by soonest, then closed', async () => {
    const overdue = makeTask({
      id: 'overdue',
      is_overdue: true,
      status: 'PENDING',
      scheduled_at: dayjs().subtract(3, 'day').toISOString(),
    });
    const soon = makeTask({
      id: 'soon',
      scheduled_at: dayjs().add(1, 'hour').toISOString(),
    });
    const later = makeTask({
      id: 'later',
      scheduled_at: dayjs().add(5, 'day').toISOString(),
    });
    const done = makeTask({
      id: 'done',
      status: 'COMPLETED',
      scheduled_at: dayjs().add(2, 'day').toISOString(),
    });

    stubGet({ '/followups': page([done, later, soon, overdue]) });

    const { result } = renderHook(() => useLeadFollowUps('lead-1'), { wrapper });

    await waitFor(() => expect(result.current.followUps).toHaveLength(4));
    expect(result.current.followUps.map((t) => t.id)).toEqual([
      'overdue',
      'soon',
      'later',
      'done',
    ]);
    expect(result.current.overdueCount).toBe(1);
  });

  it('does not count a completed task as overdue even if its due time passed', async () => {
    // `is_overdue` can be true on a row whose status has since moved on; only open tasks
    // are genuinely overdue.
    const closedButLate = makeTask({
      status: 'COMPLETED',
      is_overdue: true,
      scheduled_at: dayjs().subtract(2, 'day').toISOString(),
    });
    stubGet({ '/followups': page([closedButLate]) });

    const { result } = renderHook(() => useLeadFollowUps('lead-1'), { wrapper });

    await waitFor(() => expect(result.current.followUps).toHaveLength(1));
    expect(result.current.overdueCount).toBe(0);
  });
});

describe('useLeadWhatsAppHistory', () => {
  it('keeps only this lead’s recipient rows from the campaign fan-out', async () => {
    stubGet({
      '/whatsapp/campaigns/camp-1/recipients': page([
        makeRecipient({ id: 'mine', lead_id: 'lead-1' }),
        makeRecipient({ id: 'someone-else', lead_id: 'lead-999' }),
      ]),
      '/whatsapp/campaigns': page([makeCampaign()]),
    });

    const { result } = renderHook(() => useLeadWhatsAppHistory('lead-1'), { wrapper });

    await waitFor(() => expect(result.current.history).toHaveLength(1));
    expect(result.current.history[0].recipientId).toBe('mine');
    expect(result.current.history[0].campaignName).toBe('Monsoon Offer');
  });

  it('flags the history as sampled when older campaigns were not visited', async () => {
    stubGet({
      '/whatsapp/campaigns/camp-1/recipients': page([makeRecipient()]),
      // 30 campaigns exist but only the page of 1 was fetched.
      '/whatsapp/campaigns': page([makeCampaign()], 30),
    });

    const { result } = renderHook(() => useLeadWhatsAppHistory('lead-1'), { wrapper });

    await waitFor(() => expect(result.current.history).toHaveLength(1));
    expect(result.current.isSampled).toBe(true);
  });
});

describe('useLeadNotes', () => {
  it('builds an author lookup from the employee directory', async () => {
    stubGet({
      '/notes': page([makeNote({ created_by_employee_id: 'emp-3' })]),
      '/employees': [{ id: 'emp-3', full_name: 'Priya Nair' }],
    });

    const { result } = renderHook(() => useLeadNotes('lead-1'), { wrapper });

    await waitFor(() => expect(result.current.notes).toHaveLength(1));
    expect(result.current.authorNames['emp-3']).toBe('Priya Nair');
  });
});

// ==========================================
// 1. LEAD PROFILE RENDERING
// ==========================================

describe('LeadProfileCard', () => {
  it('renders every populated profile field', () => {
    renderWithProviders(<LeadProfileCard lead={makeLead()} assigneeName="Anita Menon" />);

    expect(screen.getByTestId('lead-profile-business-name')).toHaveTextContent('Sunrise Studio');
    expect(screen.getByTestId('lead-field-contact-person')).toHaveTextContent('Ravi Kumar');
    expect(screen.getByTestId('lead-field-phone')).toHaveTextContent('+91 98765 43210');
    expect(screen.getByTestId('lead-field-whatsapp')).toHaveTextContent('9876543210');
    expect(screen.getByTestId('lead-field-email')).toHaveTextContent('hello@sunrise.example');
    expect(screen.getByTestId('lead-field-website')).toHaveTextContent('sunrise.example');
    expect(screen.getByTestId('lead-field-instagram')).toHaveTextContent('@sunrisestudio');
    expect(screen.getByTestId('lead-field-address')).toHaveTextContent('12 MG Road');
    expect(screen.getByTestId('lead-field-city')).toHaveTextContent('Kochi');
    expect(screen.getByTestId('lead-field-district')).toHaveTextContent('Ernakulam');
    expect(screen.getByTestId('lead-field-state')).toHaveTextContent('Kerala');
    expect(screen.getByTestId('lead-field-source')).toHaveTextContent('Google Maps');
    expect(screen.getByTestId('lead-field-assignee')).toHaveTextContent('Anita Menon');
    expect(screen.getByTestId('lead-field-created')).toHaveTextContent('15 Jan 2026');
    expect(screen.getByTestId('lead-field-converted')).toHaveTextContent('No');
  });

  it('links the phone, whatsapp and maps fields', () => {
    renderWithProviders(<LeadProfileCard lead={makeLead()} assigneeName={null} />);

    expect(screen.getByTestId('lead-field-phone').querySelector('a')).toHaveAttribute(
      'href',
      'tel:+919876543210'
    );
    expect(screen.getByTestId('lead-field-whatsapp').querySelector('a')).toHaveAttribute(
      'href',
      'https://wa.me/9876543210'
    );
    expect(screen.getByTestId('lead-field-maps').querySelector('a')).toHaveAttribute(
      'href',
      'https://www.google.com/maps/search/?api=1&query=9.9312,76.2673'
    );
  });

  it('shows "Never contacted" until the lead has been contacted', () => {
    renderWithProviders(<LeadProfileCard lead={makeLead()} assigneeName={null} />);
    expect(screen.getByTestId('lead-field-last-contacted')).toHaveTextContent('Never contacted');
  });

  it('renders last_contacted_at once the backend has stamped it', () => {
    renderWithProviders(
      <LeadProfileCard
        lead={makeLead({ last_contacted_at: '2026-03-02T09:30:00.000Z' })}
        assigneeName={null}
      />
    );
    expect(screen.getByTestId('lead-field-last-contacted')).toHaveTextContent('02 Mar 2026');
  });

  it('renders the social links collected from the business website', () => {
    renderWithProviders(
      <LeadProfileCard
        lead={makeLead({
          facebook: 'https://facebook.com/sunrisestudio',
          youtube: 'https://youtube.com/@sunrisestudio',
        })}
        assigneeName="Anita Menon"
      />
    );

    const facebook = screen.getByTestId('lead-field-facebook');
    expect(facebook).toHaveTextContent('facebook.com/sunrisestudio');
    expect(within(facebook).getByRole('link')).toHaveAttribute('rel', 'noopener noreferrer');

    const youtube = screen.getByTestId('lead-field-youtube');
    expect(youtube).toHaveTextContent('youtube.com/@sunrisestudio');
    expect(within(youtube).getByRole('link')).toHaveAttribute('target', '_blank');
  });

  it('omits fields the lead does not have rather than showing blanks', () => {
    renderWithProviders(
      <LeadProfileCard
        lead={makeLead({ email: null, website: null, instagram: null, contact_person: null })}
        assigneeName={null}
      />
    );

    expect(screen.queryByTestId('lead-field-email')).not.toBeInTheDocument();
    expect(screen.queryByTestId('lead-field-website')).not.toBeInTheDocument();
    expect(screen.queryByTestId('lead-field-instagram')).not.toBeInTheDocument();
    // Facebook and YouTube are null on the base fixture, so they must be absent too — an
    // empty social link is worse than no row: it looks like a lead we can reach.
    expect(screen.queryByTestId('lead-field-facebook')).not.toBeInTheDocument();
    expect(screen.queryByTestId('lead-field-youtube')).not.toBeInTheDocument();
    expect(screen.queryByTestId('lead-field-contact-person')).not.toBeInTheDocument();
  });

  it('hides the Maps row for a lead without coordinates', () => {
    renderWithProviders(
      <LeadProfileCard lead={makeLead({ latitude: null, longitude: null })} assigneeName={null} />
    );
    expect(screen.queryByTestId('lead-field-maps')).not.toBeInTheDocument();
  });

  it('marks a converted lead', () => {
    renderWithProviders(
      <LeadProfileCard lead={makeLead({ is_converted: true })} assigneeName={null} />
    );
    expect(screen.getByTestId('lead-profile-converted')).toBeInTheDocument();
    expect(screen.getByTestId('lead-field-converted')).toHaveTextContent('Yes');
  });

  it('shows a skeleton while loading', () => {
    renderWithProviders(<LeadProfileCard lead={null} assigneeName={null} isLoading />);
    expect(screen.getByTestId('lead-profile-loading')).toBeInTheDocument();
  });
});

// ==========================================
// 2. TIMELINE LOADING
// ==========================================

describe('LeadActivityTimeline', () => {
  const baseProps = {
    activities: [] as LeadActivity[],
    total: 0,
    isLoading: false,
    isError: false,
    isEmpty: false,
    hasMore: false,
    onLoadMore: vi.fn(),
  };

  it('shows a skeleton while the first page is in flight', () => {
    renderWithProviders(
      <LeadActivityTimeline {...baseProps} isLoading activities={[]} />
    );
    expect(screen.getByTestId('lead-activity-timeline-loading')).toBeInTheDocument();
  });

  it('renders entries with their mapped labels', () => {
    renderWithProviders(
      <LeadActivityTimeline
        {...baseProps}
        total={2}
        activities={[
          makeActivity({ id: 'a1', activity_type: 'WHATSAPP_REPLIED', title: 'Lead replied' }),
          makeActivity({ id: 'a2', activity_type: 'STATUS_CHANGED', title: 'NEW → CONTACTED' }),
        ]}
      />
    );

    expect(screen.getByText('Lead replied')).toBeInTheDocument();
    expect(screen.getByText('WhatsApp Replied')).toBeInTheDocument();
    expect(screen.getByText('Status Changed')).toBeInTheDocument();
  });

  it('maps every spec-named event to a label and colour', () => {
    // The spec names ten events; the backend uses different identifiers for several.
    const expectations: Array<[ActivityType, string]> = [
      ['CREATED', 'Lead Imported'],
      ['WHATSAPP_SENT', 'WhatsApp Sent'],
      ['WHATSAPP_DELIVERED', 'WhatsApp Delivered'],
      ['WHATSAPP_READ', 'WhatsApp Read'],
      ['WHATSAPP_REPLIED', 'WhatsApp Replied'],
      ['NOTE', 'Note Added'],
      ['TASK_CREATED', 'Follow-up Created'],
      ['TASK_COMPLETED', 'Follow-up Completed'],
      ['UPDATED', 'Lead Updated'],
      ['STATUS_CHANGED', 'Status Changed'],
    ];

    expectations.forEach(([type, label]) => {
      const presentation = presentationFor(type);
      expect(presentation.label).toBe(label);
      expect(presentation.icon).toBeTruthy();
      expect(presentation.color).toBeTruthy();
    });
  });

  it('shows Load More only when more entries remain, and fires the callback', () => {
    const onLoadMore = vi.fn();
    const { rerender } = renderWithProviders(
      <LeadActivityTimeline
        {...baseProps}
        activities={[makeActivity()]}
        total={40}
        hasMore
        onLoadMore={onLoadMore}
      />
    );

    fireEvent.click(screen.getByTestId('timeline-load-more'));
    expect(onLoadMore).toHaveBeenCalledTimes(1);

    // `rerender` re-uses the wrapper the original render supplied, so the element is
    // passed bare — re-wrapping it here would nest a second Router.
    rerender(
      <LeadActivityTimeline
        {...baseProps}
        activities={[makeActivity()]}
        total={1}
        hasMore={false}
        onLoadMore={onLoadMore}
      />
    );
    expect(screen.queryByTestId('timeline-load-more')).not.toBeInTheDocument();
  });

  it('renders the empty and error states', () => {
    const { unmount } = renderWithProviders(
      <LeadActivityTimeline {...baseProps} isEmpty />
    );
    expect(screen.getByTestId('lead-activity-timeline-empty')).toBeInTheDocument();
    unmount();

    renderWithProviders(<LeadActivityTimeline {...baseProps} isError onRetry={vi.fn()} />);
    expect(screen.getByTestId('lead-activity-timeline-error')).toBeInTheDocument();
  });
});

// ==========================================
// 3. NOTES CRUD
// ==========================================

describe('LeadNotesSection', () => {
  const baseProps = {
    notes: [makeNote()],
    total: 1,
    authorNames: { 'emp-1': 'Priya Nair' },
    isLoading: false,
    isError: false,
    isEmpty: false,
    onCreate: vi.fn().mockResolvedValue(undefined),
    onUpdate: vi.fn().mockResolvedValue(undefined),
    onDelete: vi.fn().mockResolvedValue(undefined),
  };

  it('shows the note body, author and timestamp', () => {
    renderWithProviders(<LeadNotesSection {...baseProps} />);

    expect(screen.getByTestId('note-body')).toHaveTextContent(
      'Asked for the wedding album price list.'
    );
    expect(screen.getByText('Priya Nair')).toBeInTheDocument();
  });

  it('attributes a note with no author to "System"', () => {
    renderWithProviders(
      <LeadNotesSection
        {...baseProps}
        notes={[makeNote({ created_by_employee_id: null })]}
      />
    );
    expect(screen.getByText('System')).toBeInTheDocument();
  });

  it('creates a note and clears the composer', async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<LeadNotesSection {...baseProps} onCreate={onCreate} />);

    const input = screen.getByTestId('note-composer-input');
    fireEvent.change(input, { target: { value: '  Follow up next week  ' } });
    fireEvent.click(screen.getByTestId('note-composer-submit'));

    // Trimmed before submission, matching the backend's own normalisation.
    await waitFor(() => expect(onCreate).toHaveBeenCalledWith('Follow up next week'));
    await waitFor(() => expect(input).toHaveValue(''));
  });

  it('refuses to submit a blank note', () => {
    const onCreate = vi.fn();
    renderWithProviders(<LeadNotesSection {...baseProps} onCreate={onCreate} />);

    fireEvent.change(screen.getByTestId('note-composer-input'), { target: { value: '   ' } });
    expect(screen.getByTestId('note-composer-submit')).toBeDisabled();
    fireEvent.click(screen.getByTestId('note-composer-submit'));
    expect(onCreate).not.toHaveBeenCalled();
  });

  it('edits a note, pre-filling the current body', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<LeadNotesSection {...baseProps} onUpdate={onUpdate} />);

    fireEvent.click(screen.getByTestId('note-edit-note-1'));

    const editInput = screen.getByTestId('note-edit-input');
    expect(editInput).toHaveValue('Asked for the wedding album price list.');

    fireEvent.change(editInput, { target: { value: 'Sent the price list.' } });
    fireEvent.click(screen.getByTestId('note-edit-save'));

    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith('note-1', 'Sent the price list.'));
  });

  it('abandons an edit on cancel', () => {
    const onUpdate = vi.fn();
    renderWithProviders(<LeadNotesSection {...baseProps} onUpdate={onUpdate} />);

    fireEvent.click(screen.getByTestId('note-edit-note-1'));
    fireEvent.change(screen.getByTestId('note-edit-input'), { target: { value: 'discarded' } });
    fireEvent.click(screen.getByTestId('note-edit-cancel'));

    expect(onUpdate).not.toHaveBeenCalled();
    expect(screen.queryByTestId('note-edit-input')).not.toBeInTheDocument();
  });

  it('deletes a note only after confirmation', async () => {
    const onDelete = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<LeadNotesSection {...baseProps} onDelete={onDelete} />);

    fireEvent.click(screen.getByTestId('note-delete-note-1'));
    expect(onDelete).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /^delete$/i }));
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith('note-1'));
  });

  it('marks an edited note', () => {
    renderWithProviders(
      <LeadNotesSection
        {...baseProps}
        notes={[
          makeNote({
            created_at: dayjs().subtract(2, 'day').toISOString(),
            updated_at: dayjs().toISOString(),
          }),
        ]}
      />
    );
    expect(screen.getByText(/edited/)).toBeInTheDocument();
  });

  it('keeps the composer reachable when there are no notes', () => {
    renderWithProviders(<LeadNotesSection {...baseProps} notes={[]} total={0} isEmpty />);
    expect(screen.getByTestId('lead-notes-empty')).toBeInTheDocument();
    expect(screen.getByTestId('note-composer')).toBeInTheDocument();
  });
});

// ==========================================
// 4. FOLLOW-UP ACTIONS
// ==========================================

describe('LeadFollowUpsSection', () => {
  const baseProps = {
    followUps: [makeTask()],
    total: 1,
    overdueCount: 0,
    assigneeNames: { 'emp-1': 'Anita Menon' },
    isLoading: false,
    isError: false,
    isEmpty: false,
    onCreate: vi.fn(),
    onComplete: vi.fn().mockResolvedValue(undefined),
    onCancel: vi.fn().mockResolvedValue(undefined),
    onReschedule: vi.fn(),
  };

  it('renders a task with its assignee, priority and due date', () => {
    renderWithProviders(<LeadFollowUpsSection {...baseProps} />);

    expect(screen.getByText('Call about album pricing')).toBeInTheDocument();
    expect(screen.getByText('Anita Menon')).toBeInTheDocument();
    expect(screen.getByText('MEDIUM')).toBeInTheDocument();
  });

  it('highlights an overdue task', () => {
    renderWithProviders(
      <LeadFollowUpsSection
        {...baseProps}
        overdueCount={1}
        followUps={[
          makeTask({
            id: 'late',
            is_overdue: true,
            scheduled_at: dayjs().subtract(2, 'day').toISOString(),
          }),
        ]}
      />
    );

    expect(screen.getByTestId('followup-late')).toHaveAttribute('data-overdue', 'true');
    expect(screen.getByTestId('followup-overdue-late')).toBeInTheDocument();
  });

  it('does not highlight a task that is merely due later', () => {
    renderWithProviders(<LeadFollowUpsSection {...baseProps} />);
    expect(screen.getByTestId('followup-task-1')).toHaveAttribute('data-overdue', 'false');
  });

  it('completes a task after confirmation', async () => {
    const onComplete = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<LeadFollowUpsSection {...baseProps} onComplete={onComplete} />);

    fireEvent.click(screen.getByTestId('followup-complete-task-1'));
    expect(onComplete).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /^complete$/i }));
    await waitFor(() => expect(onComplete).toHaveBeenCalledWith('task-1'));
  });

  it('cancels a task after confirmation', async () => {
    const onCancel = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<LeadFollowUpsSection {...baseProps} onCancel={onCancel} />);

    fireEvent.click(screen.getByTestId('followup-cancel-task-1'));
    fireEvent.click(screen.getByRole('button', { name: /cancel follow-up/i }));

    await waitFor(() => expect(onCancel).toHaveBeenCalledWith('task-1'));
  });

  it('hands the task to the parent to reschedule', () => {
    const onReschedule = vi.fn();
    renderWithProviders(<LeadFollowUpsSection {...baseProps} onReschedule={onReschedule} />);

    fireEvent.click(screen.getByTestId('followup-reschedule-task-1'));
    expect(onReschedule).toHaveBeenCalledWith(expect.objectContaining({ id: 'task-1' }));
  });

  it('offers no lifecycle actions on a closed task', () => {
    // The backend rejects completing/cancelling/rescheduling a closed task with a 400.
    renderWithProviders(
      <LeadFollowUpsSection
        {...baseProps}
        followUps={[makeTask({ id: 'done', status: 'COMPLETED' })]}
      />
    );

    expect(screen.queryByTestId('followup-complete-done')).not.toBeInTheDocument();
    expect(screen.queryByTestId('followup-cancel-done')).not.toBeInTheDocument();
    expect(screen.queryByTestId('followup-reschedule-done')).not.toBeInTheDocument();
  });

  it('renders the empty state with a create action', () => {
    renderWithProviders(<LeadFollowUpsSection {...baseProps} followUps={[]} total={0} isEmpty />);
    expect(screen.getByTestId('lead-followups-section-empty')).toBeInTheDocument();
  });
});

// ==========================================
// 5. STATUS UPDATES
// ==========================================

describe('LeadStatusPanel', () => {
  it('requires confirmation before changing the status', async () => {
    const onChangeStatus = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <LeadStatusPanel lead={makeLead()} onChangeStatus={onChangeStatus} />
    );

    fireEvent.change(screen.getByTestId('lead-status-select'), {
      target: { value: 'INTERESTED' },
    });
    fireEvent.click(screen.getByTestId('lead-status-apply'));

    // The dialog is up; nothing has been sent yet.
    expect(onChangeStatus).not.toHaveBeenCalled();
    expect(screen.getByText(/change lead status\?/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /change status/i }));

    // Sends the lead's version so a stale page 409s instead of clobbering a concurrent edit.
    await waitFor(() => expect(onChangeStatus).toHaveBeenCalledWith('INTERESTED', 3));
  });

  it('does nothing when the confirmation is dismissed', () => {
    const onChangeStatus = vi.fn();
    renderWithProviders(
      <LeadStatusPanel lead={makeLead()} onChangeStatus={onChangeStatus} />
    );

    fireEvent.change(screen.getByTestId('lead-status-select'), { target: { value: 'LOST' } });
    fireEvent.click(screen.getByTestId('lead-status-apply'));
    fireEvent.click(screen.getByRole('button', { name: /^cancel$/i }));

    expect(onChangeStatus).not.toHaveBeenCalled();
  });

  it('keeps the apply button disabled until a status is chosen', () => {
    renderWithProviders(<LeadStatusPanel lead={makeLead()} onChangeStatus={vi.fn()} />);
    expect(screen.getByTestId('lead-status-apply')).toBeDisabled();
  });

  it('excludes the current status from the options', () => {
    renderWithProviders(
      <LeadStatusPanel lead={makeLead({ status: 'NEW' })} onChangeStatus={vi.fn()} />
    );

    const options = Array.from(
      screen.getByTestId('lead-status-select').querySelectorAll('option')
    ).map((option) => option.getAttribute('value'));

    expect(options).not.toContain('NEW');
    expect(options).toContain('CONTACTED');
  });

  it('explains a version conflict rather than failing silently', async () => {
    const onChangeStatus = vi.fn().mockRejectedValue({ response: { status: 409 } });
    renderWithProviders(
      <LeadStatusPanel lead={makeLead()} onChangeStatus={onChangeStatus} />
    );

    fireEvent.change(screen.getByTestId('lead-status-select'), {
      target: { value: 'INTERESTED' },
    });
    fireEvent.click(screen.getByTestId('lead-status-apply'));
    fireEvent.click(screen.getByRole('button', { name: /change status/i }));

    await waitFor(() =>
      expect(screen.getByTestId('lead-status-error')).toHaveTextContent(
        /changed by someone else/i
      )
    );
  });
});

// ==========================================
// WHATSAPP HISTORY
// ==========================================

describe('LeadWhatsAppHistory', () => {
  const baseProps = {
    history: [makeHistoryEntry()],
    isLoading: false,
    isError: false,
    isEmpty: false,
  };

  it('shows the campaign name, message time and reply preview', () => {
    renderWithProviders(<LeadWhatsAppHistory {...baseProps} />);

    expect(screen.getByTestId('whatsapp-campaign-name')).toHaveTextContent('Monsoon Offer');
    expect(screen.getByTestId('whatsapp-message-time')).toBeInTheDocument();
    expect(screen.getByTestId('whatsapp-reply-preview')).toHaveTextContent(
      'Yes, send me the packages.'
    );
  });

  it('marks each delivery milestone as reached or not', () => {
    renderWithProviders(
      <LeadWhatsAppHistory
        {...baseProps}
        history={[
          makeHistoryEntry({
            messageStatus: 'DELIVERED',
            readAt: null,
            repliedAt: null,
            replyText: null,
          }),
        ]}
      />
    );

    expect(screen.getByTestId('milestone-sent')).toHaveAttribute('data-reached', 'true');
    expect(screen.getByTestId('milestone-delivered')).toHaveAttribute('data-reached', 'true');
    expect(screen.getByTestId('milestone-read')).toHaveAttribute('data-reached', 'false');
    expect(screen.getByTestId('milestone-replied')).toHaveAttribute('data-reached', 'false');
    expect(screen.queryByTestId('whatsapp-reply-preview')).not.toBeInTheDocument();
  });

  it('states that the history covers recent campaigns only when sampled', () => {
    renderWithProviders(<LeadWhatsAppHistory {...baseProps} isSampled />);
    expect(screen.getByTestId('whatsapp-sampled-note')).toBeInTheDocument();
  });

  it('renders the empty state when the lead was never messaged', () => {
    renderWithProviders(<LeadWhatsAppHistory {...baseProps} history={[]} isEmpty />);
    expect(screen.getByTestId('lead-whatsapp-history-empty')).toBeInTheDocument();
  });
});

// ==========================================
// 6. RBAC RESTRICTIONS
// ==========================================

describe('RBAC', () => {
  it('hides Edit Lead without leads:update', () => {
    setPermissions(['leads:view']);
    renderWithProviders(<LeadProfileCard lead={makeLead()} assigneeName={null} />);
    expect(screen.queryByTestId('lead-profile-edit')).not.toBeInTheDocument();
  });

  it('shows Edit Lead with leads:update', () => {
    setPermissions(['leads:view', 'leads:update']);
    renderWithProviders(<LeadProfileCard lead={makeLead()} assigneeName={null} />);
    expect(screen.getByTestId('lead-profile-edit')).toBeInTheDocument();
  });

  it('hides the whole status panel without leads:update', () => {
    setPermissions(['leads:view']);
    renderWithProviders(<LeadStatusPanel lead={makeLead()} onChangeStatus={vi.fn()} />);
    expect(screen.queryByTestId('lead-status-panel')).not.toBeInTheDocument();
  });

  it('hides the note composer and per-note controls without leads:update', () => {
    setPermissions(['leads:view']);
    renderWithProviders(
      <LeadNotesSection
        notes={[makeNote()]}
        total={1}
        authorNames={{}}
        isLoading={false}
        isError={false}
        isEmpty={false}
        onCreate={vi.fn()}
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    // The notes themselves stay readable — only the mutations disappear.
    expect(screen.getByTestId('note-body')).toBeInTheDocument();
    expect(screen.queryByTestId('note-composer')).not.toBeInTheDocument();
    expect(screen.queryByTestId('note-edit-note-1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('note-delete-note-1')).not.toBeInTheDocument();
  });

  it('hides follow-up lifecycle actions without followups:update', () => {
    setPermissions(['leads:view', 'followups:view']);
    renderWithProviders(
      <LeadFollowUpsSection
        followUps={[makeTask()]}
        total={1}
        overdueCount={0}
        assigneeNames={{}}
        isLoading={false}
        isError={false}
        isEmpty={false}
        onCreate={vi.fn()}
        onComplete={vi.fn()}
        onCancel={vi.fn()}
        onReschedule={vi.fn()}
      />
    );

    expect(screen.getByText('Call about album pricing')).toBeInTheDocument();
    expect(screen.queryByTestId('followup-complete-task-1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('followup-cancel-task-1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('followups-create')).not.toBeInTheDocument();
  });

  it('hides the New follow-up button without followups:create but keeps update actions', () => {
    setPermissions(['leads:view', 'followups:view', 'followups:update']);
    renderWithProviders(
      <LeadFollowUpsSection
        followUps={[makeTask()]}
        total={1}
        overdueCount={0}
        assigneeNames={{}}
        isLoading={false}
        isError={false}
        isEmpty={false}
        onCreate={vi.fn()}
        onComplete={vi.fn()}
        onCancel={vi.fn()}
        onReschedule={vi.fn()}
      />
    );

    expect(screen.queryByTestId('followups-create')).not.toBeInTheDocument();
    expect(screen.getByTestId('followup-complete-task-1')).toBeInTheDocument();
  });

  it('gates each quick action on its own permission, leaving the local ones alone', () => {
    setPermissions(['leads:view']);
    renderWithProviders(
      <LeadQuickActions
        lead={makeLead()}
        onCreateFollowUp={vi.fn()}
        onAddNote={vi.fn()}
        onEditLead={vi.fn()}
      />
    );

    // Mutating actions are hidden…
    expect(screen.queryByTestId('quick-action-send-whatsapp')).not.toBeInTheDocument();
    expect(screen.queryByTestId('quick-action-create-followup')).not.toBeInTheDocument();
    expect(screen.queryByTestId('quick-action-add-note')).not.toBeInTheDocument();
    expect(screen.queryByTestId('quick-action-edit-lead')).not.toBeInTheDocument();

    // …while the ones that touch no API remain available.
    expect(screen.getByTestId('quick-action-copy-phone')).toBeInTheDocument();
    expect(screen.getByTestId('quick-action-open-whatsapp')).toBeInTheDocument();
    expect(screen.getByTestId('quick-action-call-now')).toBeInTheDocument();
  });

  it('shows every quick action to an administrator', () => {
    setPermissions(['*:*'], 'Administrator');
    renderWithProviders(
      <LeadQuickActions
        lead={makeLead()}
        onCreateFollowUp={vi.fn()}
        onAddNote={vi.fn()}
        onEditLead={vi.fn()}
      />
    );

    expect(screen.getByTestId('quick-action-send-whatsapp')).toBeInTheDocument();
    expect(screen.getByTestId('quick-action-create-followup')).toBeInTheDocument();
    expect(screen.getByTestId('quick-action-add-note')).toBeInTheDocument();
    expect(screen.getByTestId('quick-action-edit-lead')).toBeInTheDocument();
  });
});

// ==========================================
// QUICK ACTIONS BEHAVIOUR
// ==========================================

describe('LeadQuickActions', () => {
  it('copies the normalised phone number to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    renderWithProviders(
      <LeadQuickActions
        lead={makeLead()}
        onCreateFollowUp={vi.fn()}
        onAddNote={vi.fn()}
        onEditLead={vi.fn()}
      />
    );

    fireEvent.click(screen.getByTestId('quick-action-copy-phone'));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith('+919876543210'));
    await waitFor(() => expect(screen.getByText('Copied!')).toBeInTheDocument());
  });

  it('opens the lead’s wa.me conversation', () => {
    const open = vi.fn();
    vi.stubGlobal('open', open);

    renderWithProviders(
      <LeadQuickActions
        lead={makeLead()}
        onCreateFollowUp={vi.fn()}
        onAddNote={vi.fn()}
        onEditLead={vi.fn()}
      />
    );

    fireEvent.click(screen.getByTestId('quick-action-open-whatsapp'));
    expect(open).toHaveBeenCalledWith(
      'https://wa.me/9876543210',
      '_blank',
      'noopener,noreferrer'
    );
    vi.unstubAllGlobals();
  });

  it('delegates the section shortcuts to the page', () => {
    const onCreateFollowUp = vi.fn();
    const onAddNote = vi.fn();
    const onEditLead = vi.fn();

    renderWithProviders(
      <LeadQuickActions
        lead={makeLead()}
        onCreateFollowUp={onCreateFollowUp}
        onAddNote={onAddNote}
        onEditLead={onEditLead}
      />
    );

    fireEvent.click(screen.getByTestId('quick-action-create-followup'));
    fireEvent.click(screen.getByTestId('quick-action-add-note'));
    fireEvent.click(screen.getByTestId('quick-action-edit-lead'));

    expect(onCreateFollowUp).toHaveBeenCalledTimes(1);
    expect(onAddNote).toHaveBeenCalledTimes(1);
    expect(onEditLead).toHaveBeenCalledTimes(1);
  });
});

// ==========================================
// PAGE INTEGRATION
// ==========================================

describe('LeadDetailsPage', () => {
  it('renders every section for a fully-permissioned user', async () => {
    stubGet({
      '/leads/lead-1/activities': page([makeActivity()]),
      '/leads/lead-1/notes': page([makeNote()]),
      '/leads/lead-1': makeLead(),
      '/followups': page([makeTask()]),
      '/whatsapp/campaigns/camp-1/recipients': page([makeRecipient()]),
      '/whatsapp/campaigns': page([makeCampaign()]),
      '/employees': [{ id: 'emp-1', full_name: 'Anita Menon' }],
    });

    renderPage();

    await waitFor(() => expect(screen.getByTestId('lead-profile')).toBeInTheDocument());
    expect(screen.getByTestId('lead-activity-timeline')).toBeInTheDocument();
    expect(screen.getByTestId('lead-notes-section')).toBeInTheDocument();
    expect(screen.getByTestId('lead-status-panel')).toBeInTheDocument();
    expect(screen.getByTestId('lead-quick-actions')).toBeInTheDocument();
    expect(screen.getByTestId('lead-followups-section')).toBeInTheDocument();
    expect(screen.getByTestId('lead-whatsapp-history')).toBeInTheDocument();
  });

  it('shows a page-level error when the lead cannot be loaded', async () => {
    vi.spyOn(api, 'get').mockImplementation((url: string) => {
      if (url === '/leads/lead-1') return Promise.reject(new Error('404'));
      return Promise.resolve({ data: page([]) } as any);
    });

    renderPage();

    await waitFor(() => expect(screen.getByTestId('lead-details-error')).toBeInTheDocument());
  });

  it('omits the follow-ups and WhatsApp sections without their view permissions', async () => {
    setPermissions(['leads:view']);
    stubGet({
      '/leads/lead-1/activities': page([makeActivity()]),
      '/leads/lead-1/notes': page([]),
      '/leads/lead-1': makeLead(),
      '/employees': [],
    });

    renderPage();

    await waitFor(() => expect(screen.getByTestId('lead-profile')).toBeInTheDocument());
    expect(screen.queryByTestId('lead-followups-section')).not.toBeInTheDocument();
    expect(screen.queryByTestId('lead-whatsapp-history')).not.toBeInTheDocument();
  });
});
