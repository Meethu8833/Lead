/**
 * src/tests/leadPipeline.test.tsx
 *
 * Unit tests for the Lead Pipeline (Kanban) board.
 *
 * Organised by layer, mirroring the architecture:
 *   - utils     — the sort comparators and column definitions, which are pure
 *   - services  — that the right URLs and query parameters are sent
 *   - hooks     — page accumulation, per-column totals, and the optimistic move with its
 *                 rollback, which is where the real complexity lives
 *   - columns   — rendering, totals, empty/loading/error states, Load More
 *   - drag/drop — exercised through real HTML5 drag events rather than mocked, which is
 *                 possible precisely because the board uses the native API and not a
 *                 library that would need stubbing
 *   - filters   — that a filter change re-queries with the right params
 *   - RBAC      — that the mutating quick actions and the move control hide without the
 *                 permission their endpoint enforces
 *
 * `axios` is stubbed at the `api` module boundary, the same approach the other suites in
 * this repo take, so the service layer under test is real code.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as React from 'react';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { renderHook } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import dayjs from 'dayjs';

import { api } from '../services/api';
import { leadPipelineService, followUpsService } from '../services/leads';
import {
  PIPELINE_COLUMNS,
  PIPELINE_DND_MIME,
  EMPTY_PIPELINE_FILTERS,
  hasActiveFilters,
  isMoveAllowed,
  sortLeads,
} from '../features/leads/pipelineUtils';
import {
  usePipelineBoard,
  useMoveLeadStatus,
  usePipelineFollowUpDueDates,
} from '../features/leads/pipelineHooks';
import { PipelineCard } from '../features/leads/components/PipelineCard';
import { PipelineColumn } from '../features/leads/components/PipelineColumn';
import { PipelineFiltersBar } from '../features/leads/components/PipelineFilters';
import { useAuthStore, useNotificationStore } from '../app/store';
import {
  FollowUpTask,
  Lead,
  LeadStatus,
  PipelineColumnState,
  PipelineFilters,
} from '../features/leads/types';

// ==========================================
// FIXTURES & HELPERS
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

const makeColumn = (overrides: Partial<PipelineColumnState> = {}): PipelineColumnState => ({
  status: 'NEW',
  leads: [],
  total: 0,
  loadedCount: 0,
  hasMore: false,
  isLoading: false,
  isFetchingMore: false,
  isError: false,
  loadMore: vi.fn(),
  ...overrides,
});

const page = (items: Lead[], total = items.length, skip = 0, limit = 20) => ({
  items,
  total,
  skip,
  limit,
});

/**
 * A QueryClient with retries off, so a rejected mutation fails once and immediately.
 *
 * `gcTime` is left at its default rather than zeroed. The mutation tests seed cache
 * entries directly and never mount a component that observes them, so with `gcTime: 0`
 * those entries are collected the moment they are written and the optimistic update has
 * nothing left to edit — the test would fail while the product code is correct.
 */
const makeQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

const wrapperWith = (client: QueryClient) =>
  ({ children }: { children: React.ReactNode }) =>
    React.createElement(
      QueryClientProvider,
      { client },
      React.createElement(MemoryRouter, null, children)
    );

/** Renders with router + query client, the two providers every board component needs. */
const renderWithProviders = (ui: React.ReactElement, client = makeQueryClient()) =>
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  );

/** Grants the given permissions to the auth store for a test. */
const grantPermissions = (permissions: string[]) => {
  useAuthStore.setState({
    permissions,
    user: { id: 'emp-1', role: { name: 'Staff' } } as never,
  });
};

/**
 * A DataTransfer stand-in. jsdom's DragEvent carries no dataTransfer, so the drag tests
 * supply one; it only needs get/setData and the two effect fields the handlers touch.
 */
const makeDataTransfer = () => {
  const store: Record<string, string> = {};
  return {
    setData: (type: string, value: string) => {
      store[type] = value;
    },
    getData: (type: string) => store[type] ?? '',
    effectAllowed: '',
    dropEffect: '',
  };
};

beforeEach(() => {
  vi.clearAllMocks();
  useNotificationStore.setState({ toasts: [], unreadCount: 0 });
  grantPermissions(['*:*']);
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ==========================================
// 1. UTILS — COLUMNS & SORTING
// ==========================================

describe('Lead Pipeline — utils', () => {
  it('defines every lead status as a column, in pipeline order', () => {
    expect(PIPELINE_COLUMNS).toEqual([
      'NEW',
      'CONTACTED',
      'MESSAGE_SENT',
      'REPLIED',
      'INTERESTED',
      'NEGOTIATION',
      'FOLLOW_UP',
      'CONVERTED',
      'LOST',
    ]);
  });

  it('includes the eight columns the brief asked for', () => {
    const required: LeadStatus[] = [
      'NEW',
      'MESSAGE_SENT',
      'REPLIED',
      'INTERESTED',
      'NEGOTIATION',
      'FOLLOW_UP',
      'CONVERTED',
      'LOST',
    ];
    required.forEach((status) => expect(PIPELINE_COLUMNS).toContain(status));
  });

  describe('sortLeads', () => {
    const older = makeLead({
      id: 'older',
      business_name: 'Zenith Photos',
      created_at: dayjs().subtract(10, 'day').toISOString(),
      last_contacted_at: dayjs().subtract(1, 'day').toISOString(),
    });
    const newer = makeLead({
      id: 'newer',
      business_name: 'Apex Studio',
      created_at: dayjs().subtract(1, 'day').toISOString(),
      last_contacted_at: dayjs().subtract(9, 'day').toISOString(),
    });
    const never = makeLead({
      id: 'never',
      business_name: 'Meridian Films',
      created_at: dayjs().subtract(5, 'day').toISOString(),
      last_contacted_at: null,
    });

    it('NEWEST puts the most recently created first', () => {
      const sorted = sortLeads([older, newer, never], 'NEWEST');
      expect(sorted.map((l) => l.id)).toEqual(['newer', 'never', 'older']);
    });

    it('OLDEST puts the earliest created first', () => {
      const sorted = sortLeads([newer, older, never], 'OLDEST');
      expect(sorted.map((l) => l.id)).toEqual(['older', 'never', 'newer']);
    });

    it('NAME sorts alphabetically, case-insensitively', () => {
      const lower = makeLead({ id: 'lower', business_name: 'abc studio' });
      const upper = makeLead({ id: 'upper', business_name: 'ZZZ Studio' });
      const sorted = sortLeads([upper, lower], 'NAME');
      // Case-insensitive: "abc" must beat "ZZZ" rather than being exiled below it.
      expect(sorted.map((l) => l.id)).toEqual(['lower', 'upper']);
    });

    it('LAST_CONTACTED puts the most recently contacted first', () => {
      const sorted = sortLeads([newer, older], 'LAST_CONTACTED');
      expect(sorted.map((l) => l.id)).toEqual(['older', 'newer']);
    });

    it('LAST_CONTACTED sinks never-contacted leads to the bottom', () => {
      // The regression this guards: treating a null timestamp as epoch 0 would sort a
      // never-contacted lead as "contacted in 1970" — bottom by luck — but treating it as
      // 0 in a descending sort would instead float it to the top.
      const sorted = sortLeads([never, older, newer], 'LAST_CONTACTED');
      expect(sorted[sorted.length - 1].id).toBe('never');
    });

    it('does not mutate the array it is given', () => {
      const input = [older, newer];
      const snapshot = input.map((l) => l.id);
      sortLeads(input, 'NAME');
      expect(input.map((l) => l.id)).toEqual(snapshot);
    });
  });

  describe('isMoveAllowed', () => {
    it('permits a move to a different status', () => {
      expect(isMoveAllowed(makeLead({ status: 'NEW' }), 'REPLIED')).toBe(true);
    });

    it('rejects a drop back into the same column', () => {
      expect(isMoveAllowed(makeLead({ status: 'NEW' }), 'NEW')).toBe(false);
    });
  });

  describe('hasActiveFilters', () => {
    it('is false for the cleared state', () => {
      expect(hasActiveFilters(EMPTY_PIPELINE_FILTERS)).toBe(false);
    });

    it('is true once any single filter is set', () => {
      expect(hasActiveFilters({ ...EMPTY_PIPELINE_FILTERS, city: 'Kochi' })).toBe(true);
      expect(hasActiveFilters({ ...EMPTY_PIPELINE_FILTERS, source: 'REFERRAL' })).toBe(true);
    });
  });
});

// ==========================================
// 2. SERVICES
// ==========================================

describe('Lead Pipeline — services', () => {
  it('requests one column with its status, skip and limit', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: page([]) } as never);

    await leadPipelineService.column('REPLIED', { skip: 20, limit: 20 });

    expect(get).toHaveBeenCalledWith('/leads', {
      params: { status: 'REPLIED', skip: 20, limit: 20 },
    });
  });

  it('passes the board filters through to the query string', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: page([]) } as never);

    await leadPipelineService.column('NEW', {
      search: 'sunrise',
      source: 'REFERRAL',
      city: 'Kochi',
      district: 'Ernakulam',
      assigned_employee_id: 'emp-1',
    });

    expect(get).toHaveBeenCalledWith('/leads', {
      params: {
        search: 'sunrise',
        source: 'REFERRAL',
        city: 'Kochi',
        district: 'Ernakulam',
        assigned_employee_id: 'emp-1',
        status: 'NEW',
        skip: 0,
        limit: 20,
      },
    });
  });

  it('strips blank filters rather than sending empty strings', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: page([]) } as never);

    await leadPipelineService.column('NEW', { search: '', city: '', district: 'Ernakulam' });

    // `city=` would be a literal empty-string match server-side and return nothing.
    expect(get).toHaveBeenCalledWith('/leads', {
      params: { district: 'Ernakulam', status: 'NEW', skip: 0, limit: 20 },
    });
  });

  it('sends only status and version when moving a lead', async () => {
    const put = vi.spyOn(api, 'put').mockResolvedValue({ data: makeLead() } as never);

    await leadPipelineService.moveToStatus('lead-1', 'INTERESTED', 7);

    // Narrow by design: a drop can never accidentally rewrite another field.
    expect(put).toHaveBeenCalledWith('/leads/lead-1', { status: 'INTERESTED', version: 7 });
  });

  it('reads the open follow-up worklist for the due-date badges', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: page([]) } as never);

    await followUpsService.pending(200);

    expect(get).toHaveBeenCalledWith('/followups', {
      params: { skip: 0, limit: 200, status: 'PENDING' },
    });
  });
});

// ==========================================
// 3. HOOKS — BOARD DATA
// ==========================================

describe('Lead Pipeline — usePipelineBoard', () => {
  it('fetches one query per column and reports each column total', async () => {
    const spy = vi.spyOn(leadPipelineService, 'column').mockImplementation(async (status) => {
      if (status === 'NEW') return page([makeLead({ id: 'a' })], 5);
      if (status === 'REPLIED') return page([makeLead({ id: 'b', status: 'REPLIED' })], 3);
      return page([], 0);
    });

    const { result } = renderHook(
      () => usePipelineBoard(EMPTY_PIPELINE_FILTERS, 'NEWEST'),
      { wrapper: wrapperWith(makeQueryClient()) }
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(spy).toHaveBeenCalledTimes(PIPELINE_COLUMNS.length);
    expect(result.current.columns).toHaveLength(PIPELINE_COLUMNS.length);

    const newColumn = result.current.columns.find((c) => c.status === 'NEW');
    expect(newColumn?.total).toBe(5);
    expect(newColumn?.leads.map((l) => l.id)).toEqual(['a']);

    // The header total is the server's count, not what has been loaded so far.
    expect(newColumn?.loadedCount).toBe(1);
    expect(newColumn?.hasMore).toBe(true);
  });

  it('sums every column into a board-wide total', async () => {
    vi.spyOn(leadPipelineService, 'column').mockImplementation(async (status) =>
      status === 'NEW' ? page([], 4) : status === 'LOST' ? page([], 6) : page([], 0)
    );

    const { result } = renderHook(
      () => usePipelineBoard(EMPTY_PIPELINE_FILTERS, 'NEWEST'),
      { wrapper: wrapperWith(makeQueryClient()) }
    );

    await waitFor(() => expect(result.current.totalLeads).toBe(10));
  });

  it('accumulates pages on loadMore instead of replacing them', async () => {
    vi.spyOn(leadPipelineService, 'column').mockImplementation(async (status, params) => {
      if (status !== 'NEW') return page([], 0);
      return params?.skip === 20
        ? page([makeLead({ id: 'page2' })], 40, 20)
        : page([makeLead({ id: 'page1' })], 40, 0);
    });

    const { result } = renderHook(
      () => usePipelineBoard(EMPTY_PIPELINE_FILTERS, 'NEWEST'),
      { wrapper: wrapperWith(makeQueryClient()) }
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => {
      result.current.columns.find((c) => c.status === 'NEW')!.loadMore();
    });

    await waitFor(() => {
      const column = result.current.columns.find((c) => c.status === 'NEW');
      expect(column?.leads.map((l) => l.id).sort()).toEqual(['page1', 'page2']);
    });
  });

  it('de-duplicates a lead that appears on two pages', async () => {
    // Happens for real: a lead moved by someone else between two page fetches can be
    // returned on both. Rendering it twice would also warn about a duplicate React key.
    vi.spyOn(leadPipelineService, 'column').mockImplementation(async (status, params) => {
      if (status !== 'NEW') return page([], 0);
      return params?.skip === 20
        ? page([makeLead({ id: 'dupe' })], 40, 20)
        : page([makeLead({ id: 'dupe' })], 40, 0);
    });

    const { result } = renderHook(
      () => usePipelineBoard(EMPTY_PIPELINE_FILTERS, 'NEWEST'),
      { wrapper: wrapperWith(makeQueryClient()) }
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    act(() => {
      result.current.columns.find((c) => c.status === 'NEW')!.loadMore();
    });

    await waitFor(() => {
      const column = result.current.columns.find((c) => c.status === 'NEW');
      expect(column?.leads.filter((l) => l.id === 'dupe')).toHaveLength(1);
    });
  });

  it('re-queries with the new filter when a filter changes', async () => {
    const spy = vi.spyOn(leadPipelineService, 'column').mockResolvedValue(page([]));

    const { rerender } = renderHook(
      ({ filters }: { filters: PipelineFilters }) => usePipelineBoard(filters, 'NEWEST'),
      {
        wrapper: wrapperWith(makeQueryClient()),
        initialProps: { filters: EMPTY_PIPELINE_FILTERS },
      }
    );

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(PIPELINE_COLUMNS.length));
    spy.mockClear();

    rerender({ filters: { ...EMPTY_PIPELINE_FILTERS, city: 'Kochi' } });

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith('NEW', expect.objectContaining({ city: 'Kochi' }));
    });
  });

  it('applies the chosen sort to a column', async () => {
    vi.spyOn(leadPipelineService, 'column').mockImplementation(async (status) =>
      status === 'NEW'
        ? page([
            makeLead({ id: 'z', business_name: 'Zenith' }),
            makeLead({ id: 'a', business_name: 'Apex' }),
          ])
        : page([], 0)
    );

    const { result } = renderHook(
      () => usePipelineBoard(EMPTY_PIPELINE_FILTERS, 'NAME'),
      { wrapper: wrapperWith(makeQueryClient()) }
    );

    await waitFor(() => {
      const column = result.current.columns.find((c) => c.status === 'NEW');
      expect(column?.leads.map((l) => l.id)).toEqual(['a', 'z']);
    });
  });

  it('surfaces a column-level error without failing the whole board', async () => {
    vi.spyOn(leadPipelineService, 'column').mockImplementation(async (status) => {
      if (status === 'LOST') throw new Error('boom');
      return page([], 0);
    });

    const { result } = renderHook(
      () => usePipelineBoard(EMPTY_PIPELINE_FILTERS, 'NEWEST'),
      { wrapper: wrapperWith(makeQueryClient()) }
    );

    await waitFor(() => {
      expect(result.current.columns.find((c) => c.status === 'LOST')?.isError).toBe(true);
    });
    expect(result.current.columns.find((c) => c.status === 'NEW')?.isError).toBe(false);
    expect(result.current.isError).toBe(false);
  });
});

// ==========================================
// 4. HOOKS — STATUS UPDATE, OPTIMISM & ROLLBACK
// ==========================================

describe('Lead Pipeline — useMoveLeadStatus', () => {
  it('calls the API with the lead id, target status and version', async () => {
    const spy = vi
      .spyOn(leadPipelineService, 'moveToStatus')
      .mockResolvedValue(makeLead({ status: 'INTERESTED', version: 2 }));

    const { result } = renderHook(() => useMoveLeadStatus(EMPTY_PIPELINE_FILTERS), {
      wrapper: wrapperWith(makeQueryClient()),
    });

    await act(async () => {
      await result.current.mutateAsync({
        lead: makeLead({ version: 4 }),
        status: 'INTERESTED',
      });
    });

    expect(spy).toHaveBeenCalledWith('lead-1', 'INTERESTED', 4);
  });

  it('optimistically moves the card between columns before the server replies', async () => {
    const client = makeQueryClient();
    const lead = makeLead({ status: 'NEW' });

    const sourceKey = ['leads', 'pipeline', 'NEW', EMPTY_PIPELINE_FILTERS, 0];
    const targetKey = ['leads', 'pipeline', 'INTERESTED', EMPTY_PIPELINE_FILTERS, 0];
    client.setQueryData(sourceKey, page([lead], 1));
    client.setQueryData(targetKey, page([], 0));

    // Never resolves during the assertion window, so what is observed is purely the
    // optimistic state rather than the settled one.
    vi.spyOn(leadPipelineService, 'moveToStatus').mockImplementation(
      () => new Promise(() => {})
    );

    const { result } = renderHook(() => useMoveLeadStatus(EMPTY_PIPELINE_FILTERS), {
      wrapper: wrapperWith(client),
    });

    act(() => {
      result.current.mutate({ lead, status: 'INTERESTED' });
    });

    await waitFor(() => {
      const source = client.getQueryData<ReturnType<typeof page>>(sourceKey);
      const target = client.getQueryData<ReturnType<typeof page>>(targetKey);
      expect(source?.items).toHaveLength(0);
      expect(target?.items.map((l) => l.id)).toEqual(['lead-1']);
    });
  });

  it('moves the column totals with the card', async () => {
    const client = makeQueryClient();
    const lead = makeLead({ status: 'NEW' });
    const sourceKey = ['leads', 'pipeline', 'NEW', EMPTY_PIPELINE_FILTERS, 0];
    const targetKey = ['leads', 'pipeline', 'INTERESTED', EMPTY_PIPELINE_FILTERS, 0];
    client.setQueryData(sourceKey, page([lead], 9));
    client.setQueryData(targetKey, page([], 4));

    vi.spyOn(leadPipelineService, 'moveToStatus').mockImplementation(
      () => new Promise(() => {})
    );

    const { result } = renderHook(() => useMoveLeadStatus(EMPTY_PIPELINE_FILTERS), {
      wrapper: wrapperWith(client),
    });

    act(() => {
      result.current.mutate({ lead, status: 'INTERESTED' });
    });

    await waitFor(() => {
      expect(client.getQueryData<ReturnType<typeof page>>(sourceKey)?.total).toBe(8);
      expect(client.getQueryData<ReturnType<typeof page>>(targetKey)?.total).toBe(5);
    });
  });

  it('rolls the whole board back when the update fails', async () => {
    const client = makeQueryClient();
    const lead = makeLead({ status: 'NEW' });
    const sourceKey = ['leads', 'pipeline', 'NEW', EMPTY_PIPELINE_FILTERS, 0];
    const targetKey = ['leads', 'pipeline', 'INTERESTED', EMPTY_PIPELINE_FILTERS, 0];
    client.setQueryData(sourceKey, page([lead], 1));
    client.setQueryData(targetKey, page([], 0));

    vi.spyOn(leadPipelineService, 'moveToStatus').mockRejectedValue(new Error('network'));

    const { result } = renderHook(() => useMoveLeadStatus(EMPTY_PIPELINE_FILTERS), {
      wrapper: wrapperWith(client),
    });

    await act(async () => {
      await result.current
        .mutateAsync({ lead, status: 'INTERESTED' })
        .catch(() => undefined);
    });

    // Both the card and both totals must be exactly as they were.
    await waitFor(() => {
      const source = client.getQueryData<ReturnType<typeof page>>(sourceKey);
      const target = client.getQueryData<ReturnType<typeof page>>(targetKey);
      expect(source?.items.map((l) => l.id)).toEqual(['lead-1']);
      expect(source?.total).toBe(1);
      expect(target?.items).toHaveLength(0);
      expect(target?.total).toBe(0);
    });
  });

  it('rolls back a 409 version conflict just like any other failure', async () => {
    const client = makeQueryClient();
    const lead = makeLead({ status: 'NEW' });
    const sourceKey = ['leads', 'pipeline', 'NEW', EMPTY_PIPELINE_FILTERS, 0];
    client.setQueryData(sourceKey, page([lead], 1));

    vi.spyOn(leadPipelineService, 'moveToStatus').mockRejectedValue({
      response: { status: 409 },
    });

    const { result } = renderHook(() => useMoveLeadStatus(EMPTY_PIPELINE_FILTERS), {
      wrapper: wrapperWith(client),
    });

    await act(async () => {
      await result.current
        .mutateAsync({ lead, status: 'INTERESTED' })
        .catch(() => undefined);
    });

    await waitFor(() => {
      expect(
        client.getQueryData<ReturnType<typeof page>>(sourceKey)?.items.map((l) => l.id)
      ).toEqual(['lead-1']);
    });
  });
});

// ==========================================
// 5. HOOKS — FOLLOW-UP DUE DATES
// ==========================================

describe('Lead Pipeline — usePipelineFollowUpDueDates', () => {
  const makeTask = (overrides: Partial<FollowUpTask> = {}): FollowUpTask => ({
    id: 'task-1',
    lead_id: 'lead-1',
    assigned_employee_id: null,
    title: 'Call back',
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

  it('indexes open follow-ups by lead', async () => {
    const due = dayjs().add(2, 'day').toISOString();
    vi.spyOn(followUpsService, 'pending').mockResolvedValue(
      page([makeTask({ scheduled_at: due })] as never, 1) as never
    );

    const { result } = renderHook(() => usePipelineFollowUpDueDates(), {
      wrapper: wrapperWith(makeQueryClient()),
    });

    await waitFor(() => expect(result.current.resolveFollowUpDue('lead-1')).toBe(due));
    expect(result.current.resolveFollowUpDue('lead-unknown')).toBeNull();
  });

  it('keeps the soonest task when a lead has several open', async () => {
    const soon = dayjs().add(1, 'day').toISOString();
    const later = dayjs().add(9, 'day').toISOString();
    vi.spyOn(followUpsService, 'pending').mockResolvedValue(
      page(
        [
          makeTask({ id: 't-later', scheduled_at: later }),
          makeTask({ id: 't-soon', scheduled_at: soon }),
        ] as never,
        2
      ) as never
    );

    const { result } = renderHook(() => usePipelineFollowUpDueDates(), {
      wrapper: wrapperWith(makeQueryClient()),
    });

    await waitFor(() => expect(result.current.resolveFollowUpDue('lead-1')).toBe(soon));
  });
});

// ==========================================
// 6. COLUMN RENDERING
// ==========================================

describe('Lead Pipeline — column rendering', () => {
  const columnProps = (column: PipelineColumnState, overrides = {}) => ({
    column,
    resolveAssignee: () => 'Priya',
    resolveFollowUpDue: () => null,
    isDragActive: false,
    isDragOver: false,
    draggingLeadId: null,
    movingLeadId: null,
    onDragStart: vi.fn(),
    onDragEnd: vi.fn(),
    onDragEnterColumn: vi.fn(),
    onDrop: vi.fn(),
    onCreateFollowUp: vi.fn(),
    onAddNote: vi.fn(),
    onMoveTo: vi.fn(),
    ...overrides,
  });

  it('renders the column title and its total', () => {
    renderWithProviders(
      <PipelineColumn {...columnProps(makeColumn({ status: 'MESSAGE_SENT', total: 12 }))} />
    );

    expect(screen.getByText('Message Sent')).toBeInTheDocument();
    expect(screen.getByTestId('pipeline-total-MESSAGE_SENT')).toHaveTextContent('12');
  });

  it('renders a card per lead', () => {
    const leads = [
      makeLead({ id: 'l1', business_name: 'Sunrise Studio' }),
      makeLead({ id: 'l2', business_name: 'Moonlight Films' }),
    ];
    renderWithProviders(
      <PipelineColumn
        {...columnProps(makeColumn({ leads, total: 2, loadedCount: 2 }))}
      />
    );

    expect(screen.getByTestId('pipeline-card-l1')).toBeInTheDocument();
    expect(screen.getByTestId('pipeline-card-l2')).toBeInTheDocument();
    expect(screen.getByText('Sunrise Studio')).toBeInTheDocument();
  });

  it('shows a skeleton while the first page loads', () => {
    renderWithProviders(
      <PipelineColumn {...columnProps(makeColumn({ isLoading: true }))} />
    );
    expect(screen.getByTestId('pipeline-skeleton-NEW')).toBeInTheDocument();
  });

  it('shows an empty state when the column has no leads', () => {
    renderWithProviders(<PipelineColumn {...columnProps(makeColumn())} />);
    expect(screen.getByTestId('pipeline-empty-NEW')).toBeInTheDocument();
    expect(screen.getByText('No leads')).toBeInTheDocument();
  });

  it('invites a drop into an empty column during a drag', () => {
    renderWithProviders(
      <PipelineColumn {...columnProps(makeColumn(), { isDragActive: true })} />
    );
    // An empty column must still be reachable — otherwise it could never be filled.
    expect(screen.getByText('Drop here')).toBeInTheDocument();
  });

  it('shows an error state for a failed column', () => {
    renderWithProviders(
      <PipelineColumn {...columnProps(makeColumn({ isError: true }))} />
    );
    expect(screen.getByTestId('pipeline-error-NEW')).toBeInTheDocument();
  });

  it('offers Load More with the remaining count, and calls it', () => {
    const loadMore = vi.fn();
    renderWithProviders(
      <PipelineColumn
        {...columnProps(
          makeColumn({
            leads: [makeLead({ id: 'l1' })],
            total: 30,
            loadedCount: 1,
            hasMore: true,
            loadMore,
          })
        )}
      />
    );

    const button = screen.getByTestId('pipeline-load-more-NEW');
    expect(button).toHaveTextContent('29 left');
    fireEvent.click(button);
    expect(loadMore).toHaveBeenCalled();
  });

  it('reports loaded-of-total while a column is partially loaded', () => {
    renderWithProviders(
      <PipelineColumn
        {...columnProps(
          makeColumn({
            leads: [makeLead({ id: 'l1' })],
            total: 30,
            loadedCount: 1,
            hasMore: true,
          })
        )}
      />
    );
    expect(screen.getByTestId('pipeline-loaded-NEW')).toHaveTextContent('Showing 1 of 30');
  });

  it('hides Load More once everything is loaded', () => {
    renderWithProviders(
      <PipelineColumn
        {...columnProps(
          makeColumn({ leads: [makeLead({ id: 'l1' })], total: 1, loadedCount: 1 })
        )}
      />
    );
    expect(screen.queryByTestId('pipeline-load-more-NEW')).not.toBeInTheDocument();
  });
});

// ==========================================
// 7. CARD CONTENT
// ==========================================

describe('Lead Pipeline — card content', () => {
  const cardProps = (lead: Lead, overrides = {}) => ({
    lead,
    assigneeName: 'Priya Nair',
    followUpDueAt: null,
    onDragStart: vi.fn(),
    onDragEnd: vi.fn(),
    onCreateFollowUp: vi.fn(),
    onAddNote: vi.fn(),
    onMoveTo: vi.fn(),
    ...overrides,
  });

  it('shows every field the brief asked a card to carry', () => {
    const lead = makeLead({
      business_name: 'Sunrise Studio',
      phone: '9876543210',
      source: 'GOOGLE_MAPS',
      status: 'REPLIED',
      last_contacted_at: dayjs().subtract(3, 'day').toISOString(),
    });

    renderWithProviders(
      <PipelineCard
        {...cardProps(lead, { followUpDueAt: dayjs().add(2, 'day').toISOString() })}
      />
    );

    expect(screen.getByText('Sunrise Studio')).toBeInTheDocument();
    expect(screen.getByText('9876543210')).toBeInTheDocument();
    expect(screen.getByTestId('pipeline-card-source')).toHaveTextContent('Google Maps');
    expect(screen.getByTestId('pipeline-card-assignee')).toHaveTextContent('Priya Nair');
    expect(screen.getByTestId('pipeline-card-last-contacted')).toHaveTextContent('3d ago');
    expect(screen.getByTestId('pipeline-card-followup-due')).toBeInTheDocument();
    expect(screen.getByTestId('lead-status-badge')).toHaveTextContent('Replied');
  });

  it('marks a lead with a WhatsApp number as WhatsApp-ready', () => {
    const lead = makeLead({ whatsapp: '9876543210' });
    renderWithProviders(<PipelineCard {...cardProps(lead)} />);

    expect(screen.getByTestId('pipeline-card-whatsapp-ready')).toBeInTheDocument();
  });

  it('does not mark a lead WhatsApp-ready on the strength of a plain phone number', () => {
    // Only the `whatsapp` column proves the number is reachable on WhatsApp. Badging every
    // lead with a phone would overstate how many a campaign can actually reach.
    const lead = makeLead({ whatsapp: null, phone: '9876543210' });
    renderWithProviders(<PipelineCard {...cardProps(lead)} />);

    expect(screen.queryByTestId('pipeline-card-whatsapp-ready')).not.toBeInTheDocument();
  });

  it('says Unassigned when no employee owns the lead', () => {
    renderWithProviders(
      <PipelineCard {...cardProps(makeLead(), { assigneeName: null })} />
    );
    expect(screen.getByTestId('pipeline-card-assignee')).toHaveTextContent('Unassigned');
  });

  it('shows an em dash rather than a fake date for a never-contacted lead', () => {
    renderWithProviders(
      <PipelineCard {...cardProps(makeLead({ last_contacted_at: null }))} />
    );
    expect(screen.getByTestId('pipeline-card-last-contacted')).toHaveTextContent('—');
  });

  it('omits the follow-up row when the lead has no open task', () => {
    renderWithProviders(<PipelineCard {...cardProps(makeLead())} />);
    expect(screen.queryByTestId('pipeline-card-followup-due')).not.toBeInTheDocument();
  });

  it('raises Create Follow-up without navigating', () => {
    const onCreateFollowUp = vi.fn();
    renderWithProviders(
      <PipelineCard {...cardProps(makeLead(), { onCreateFollowUp })} />
    );

    fireEvent.click(screen.getByTestId('pipeline-action-followup'));
    expect(onCreateFollowUp).toHaveBeenCalledWith(expect.objectContaining({ id: 'lead-1' }));
  });

  it('raises Add Note without navigating', () => {
    const onAddNote = vi.fn();
    renderWithProviders(<PipelineCard {...cardProps(makeLead(), { onAddNote })} />);

    fireEvent.click(screen.getByTestId('pipeline-action-note'));
    expect(onAddNote).toHaveBeenCalledWith(expect.objectContaining({ id: 'lead-1' }));
  });

  it('opens WhatsApp in a new tab', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    renderWithProviders(
      <PipelineCard {...cardProps(makeLead({ whatsapp: '9876543210' }))} />
    );

    fireEvent.click(screen.getByTestId('pipeline-action-whatsapp'));
    expect(open).toHaveBeenCalledWith(
      'https://wa.me/9876543210',
      '_blank',
      'noopener,noreferrer'
    );
  });

  it('offers every status except the one the lead is already in', () => {
    renderWithProviders(<PipelineCard {...cardProps(makeLead({ status: 'NEW' }))} />);

    const select = screen.getByTestId('pipeline-action-move');
    const values = Array.from(select.querySelectorAll('option')).map((o) => o.getAttribute('value'));
    expect(values).not.toContain('NEW');
    expect(values).toContain('CONVERTED');
    expect(values).toContain('LOST');
  });

  it('moves via the keyboard-accessible select', () => {
    const onMoveTo = vi.fn();
    renderWithProviders(<PipelineCard {...cardProps(makeLead(), { onMoveTo })} />);

    fireEvent.change(screen.getByTestId('pipeline-action-move'), {
      target: { value: 'INTERESTED' },
    });
    expect(onMoveTo).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'lead-1' }),
      'INTERESTED'
    );
  });
});

// ==========================================
// 8. DRAG AND DROP
// ==========================================

describe('Lead Pipeline — drag and drop', () => {
  const cardProps = (lead: Lead, overrides = {}) => ({
    lead,
    assigneeName: null,
    followUpDueAt: null,
    onDragStart: vi.fn(),
    onDragEnd: vi.fn(),
    onCreateFollowUp: vi.fn(),
    onAddNote: vi.fn(),
    onMoveTo: vi.fn(),
    ...overrides,
  });

  const columnProps = (column: PipelineColumnState, overrides = {}) => ({
    column,
    resolveAssignee: () => null,
    resolveFollowUpDue: () => null,
    isDragActive: false,
    isDragOver: false,
    draggingLeadId: null,
    movingLeadId: null,
    onDragStart: vi.fn(),
    onDragEnd: vi.fn(),
    onDragEnterColumn: vi.fn(),
    onDrop: vi.fn(),
    onCreateFollowUp: vi.fn(),
    onAddNote: vi.fn(),
    onMoveTo: vi.fn(),
    ...overrides,
  });

  it('marks a card draggable', () => {
    renderWithProviders(<PipelineCard {...cardProps(makeLead())} />);
    expect(screen.getByTestId('pipeline-card-lead-1')).toHaveAttribute('draggable', 'true');
  });

  it('reports the dragged lead and writes its id to the dataTransfer', () => {
    const onDragStart = vi.fn();
    renderWithProviders(<PipelineCard {...cardProps(makeLead(), { onDragStart })} />);

    const dataTransfer = makeDataTransfer();
    fireEvent.dragStart(screen.getByTestId('pipeline-card-lead-1'), { dataTransfer });

    expect(onDragStart).toHaveBeenCalledWith(expect.objectContaining({ id: 'lead-1' }));
    expect(dataTransfer.getData(PIPELINE_DND_MIME)).toBe('lead-1');
    expect(dataTransfer.effectAllowed).toBe('move');
  });

  it('does not let a card be dragged while its own move is in flight', () => {
    renderWithProviders(
      <PipelineCard {...cardProps(makeLead(), { isMoving: true })} />
    );
    expect(screen.getByTestId('pipeline-card-lead-1')).toHaveAttribute('draggable', 'false');
  });

  it('reports drag-enter so the column can highlight', () => {
    const onDragEnterColumn = vi.fn();
    renderWithProviders(
      <PipelineColumn
        {...columnProps(makeColumn({ status: 'REPLIED' }), { onDragEnterColumn })}
      />
    );

    fireEvent.dragEnter(screen.getByTestId('pipeline-column-REPLIED'), {
      dataTransfer: makeDataTransfer(),
    });
    expect(onDragEnterColumn).toHaveBeenCalledWith('REPLIED');
  });

  it('keeps the highlight while the cursor crosses child cards', () => {
    // The flicker bug this guards: dragleave fires when entering a *child*, so a naive
    // enter/leave toggle would clear the highlight as the cursor passes over each card.
    const onDragEnterColumn = vi.fn();
    renderWithProviders(
      <PipelineColumn
        {...columnProps(makeColumn({ status: 'REPLIED' }), { onDragEnterColumn })}
      />
    );

    const column = screen.getByTestId('pipeline-column-REPLIED');
    fireEvent.dragEnter(column, { dataTransfer: makeDataTransfer() });
    fireEvent.dragEnter(column, { dataTransfer: makeDataTransfer() }); // onto a child
    fireEvent.dragLeave(column); // leaving that child, still inside the column

    // Still highlighted: the last call is the enter, never a null clear.
    expect(onDragEnterColumn).toHaveBeenLastCalledWith('REPLIED');

    fireEvent.dragLeave(column); // now genuinely out
    expect(onDragEnterColumn).toHaveBeenLastCalledWith(null);
  });

  it('marks the column as a drop target on dragOver', () => {
    renderWithProviders(<PipelineColumn {...columnProps(makeColumn())} />);

    const dataTransfer = makeDataTransfer();
    // Without preventDefault on dragOver the browser never fires drop at all.
    const notCancelled = fireEvent.dragOver(screen.getByTestId('pipeline-column-NEW'), {
      dataTransfer,
    });
    expect(notCancelled).toBe(false);
    expect(dataTransfer.dropEffect).toBe('move');
  });

  it('reports the target status on drop', () => {
    const onDrop = vi.fn();
    renderWithProviders(
      <PipelineColumn
        {...columnProps(makeColumn({ status: 'INTERESTED' }), { onDrop })}
      />
    );

    fireEvent.drop(screen.getByTestId('pipeline-column-INTERESTED'), {
      dataTransfer: makeDataTransfer(),
    });
    expect(onDrop).toHaveBeenCalledWith('INTERESTED');
  });

  it('shows the drop-target styling while a card is over it', () => {
    renderWithProviders(
      <PipelineColumn {...columnProps(makeColumn(), { isDragOver: true })} />
    );
    expect(screen.getByTestId('pipeline-column-NEW')).toHaveAttribute('data-drag-over', 'true');
  });

  it('dims the card being dragged', () => {
    renderWithProviders(
      <PipelineCard {...cardProps(makeLead(), { isDragging: true })} />
    );
    expect(screen.getByTestId('pipeline-card-lead-1').className).toContain('opacity-40');
  });
});

// ==========================================
// 9. FILTERS & SORTING (UI)
// ==========================================

describe('Lead Pipeline — filters and sorting', () => {
  const filtersProps = (overrides = {}) => ({
    filters: EMPTY_PIPELINE_FILTERS,
    sort: 'NEWEST' as const,
    employees: [{ id: 'emp-1', full_name: 'Priya Nair' }],
    onChange: vi.fn(),
    onSortChange: vi.fn(),
    onClear: vi.fn(),
    ...overrides,
  });

  it('renders every filter control the brief asked for', () => {
    renderWithProviders(<PipelineFiltersBar {...filtersProps()} />);

    expect(screen.getByTestId('pipeline-search')).toBeInTheDocument();
    expect(screen.getByTestId('pipeline-filter-source')).toBeInTheDocument();
    expect(screen.getByTestId('pipeline-filter-assignee')).toBeInTheDocument();
    expect(screen.getByTestId('pipeline-filter-city')).toBeInTheDocument();
    expect(screen.getByTestId('pipeline-filter-district')).toBeInTheDocument();
  });

  it('reports a source filter change', () => {
    const onChange = vi.fn();
    renderWithProviders(<PipelineFiltersBar {...filtersProps({ onChange })} />);

    fireEvent.change(screen.getByTestId('pipeline-filter-source'), {
      target: { value: 'REFERRAL' },
    });
    expect(onChange).toHaveBeenCalledWith({ source: 'REFERRAL' });
  });

  it('reports an assignee filter change', () => {
    const onChange = vi.fn();
    renderWithProviders(<PipelineFiltersBar {...filtersProps({ onChange })} />);

    fireEvent.change(screen.getByTestId('pipeline-filter-assignee'), {
      target: { value: 'emp-1' },
    });
    expect(onChange).toHaveBeenCalledWith({ assigned_employee_id: 'emp-1' });
  });

  it('reports city and district changes', () => {
    const onChange = vi.fn();
    renderWithProviders(<PipelineFiltersBar {...filtersProps({ onChange })} />);

    fireEvent.change(screen.getByTestId('pipeline-filter-city'), {
      target: { value: 'Kochi' },
    });
    expect(onChange).toHaveBeenCalledWith({ city: 'Kochi' });

    fireEvent.change(screen.getByTestId('pipeline-filter-district'), {
      target: { value: 'Ernakulam' },
    });
    expect(onChange).toHaveBeenCalledWith({ district: 'Ernakulam' });
  });

  it('debounces the search box before reporting', async () => {
    const onChange = vi.fn();
    renderWithProviders(<PipelineFiltersBar {...filtersProps({ onChange })} />);

    // `data-testid` is forwarded onto SearchBox's own <input>, so this *is* the input.
    fireEvent.change(screen.getByTestId('pipeline-search'), {
      target: { value: 'sunrise' },
    });

    await waitFor(() => expect(onChange).toHaveBeenCalledWith({ search: 'sunrise' }), {
      timeout: 2000,
    });
  });

  it('offers all four sort options and reports a change', () => {
    const onSortChange = vi.fn();
    renderWithProviders(<PipelineFiltersBar {...filtersProps({ onSortChange })} />);

    const select = screen.getByTestId('pipeline-sort');
    const values = Array.from(select.querySelectorAll('option')).map((o) => o.getAttribute('value'));
    expect(values).toEqual(['NEWEST', 'OLDEST', 'LAST_CONTACTED', 'NAME']);

    fireEvent.change(select, { target: { value: 'NAME' } });
    expect(onSortChange).toHaveBeenCalledWith('NAME');
  });

  it('hides Clear until a filter is set, then clears', () => {
    const onClear = vi.fn();
    const { rerender } = renderWithProviders(
      <PipelineFiltersBar {...filtersProps({ onClear })} />
    );
    expect(screen.queryByTestId('pipeline-clear-filters')).not.toBeInTheDocument();

    rerender(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter>
          <PipelineFiltersBar
            {...filtersProps({
              onClear,
              filters: { ...EMPTY_PIPELINE_FILTERS, city: 'Kochi' },
            })}
          />
        </MemoryRouter>
      </QueryClientProvider>
    );

    fireEvent.click(screen.getByTestId('pipeline-clear-filters'));
    expect(onClear).toHaveBeenCalled();
  });
});

// ==========================================
// 10. RBAC
// ==========================================

describe('Lead Pipeline — RBAC', () => {
  const cardProps = (lead: Lead, overrides = {}) => ({
    lead,
    assigneeName: null,
    followUpDueAt: null,
    onDragStart: vi.fn(),
    onDragEnd: vi.fn(),
    onCreateFollowUp: vi.fn(),
    onAddNote: vi.fn(),
    onMoveTo: vi.fn(),
    ...overrides,
  });

  it('hides the move control without leads:update', () => {
    grantPermissions(['leads:view']);
    renderWithProviders(<PipelineCard {...cardProps(makeLead())} />);

    // Dragging writes a status change; a viewer must not be offered the control that
    // mirrors it either.
    expect(screen.queryByTestId('pipeline-action-move')).not.toBeInTheDocument();
  });

  it('hides Add Note without leads:update', () => {
    grantPermissions(['leads:view']);
    renderWithProviders(<PipelineCard {...cardProps(makeLead())} />);
    expect(screen.queryByTestId('pipeline-action-note')).not.toBeInTheDocument();
  });

  it('hides Create Follow-up without followups:create', () => {
    grantPermissions(['leads:view', 'leads:update']);
    renderWithProviders(<PipelineCard {...cardProps(makeLead())} />);
    expect(screen.queryByTestId('pipeline-action-followup')).not.toBeInTheDocument();
  });

  it('hides Send WhatsApp without whatsapp:create', () => {
    grantPermissions(['leads:view', 'leads:update']);
    renderWithProviders(<PipelineCard {...cardProps(makeLead())} />);
    expect(screen.queryByTestId('pipeline-action-whatsapp')).not.toBeInTheDocument();
  });

  it('always allows opening the lead, which needs no extra permission', () => {
    grantPermissions(['leads:view']);
    renderWithProviders(<PipelineCard {...cardProps(makeLead())} />);
    expect(screen.getByTestId('pipeline-action-open')).toBeInTheDocument();
  });

  it('shows every action to an Administrator', () => {
    useAuthStore.setState({
      permissions: [],
      user: { id: 'emp-1', role: { name: 'Administrator' } } as never,
    });
    renderWithProviders(<PipelineCard {...cardProps(makeLead())} />);

    expect(screen.getByTestId('pipeline-action-move')).toBeInTheDocument();
    expect(screen.getByTestId('pipeline-action-note')).toBeInTheDocument();
    expect(screen.getByTestId('pipeline-action-followup')).toBeInTheDocument();
    expect(screen.getByTestId('pipeline-action-whatsapp')).toBeInTheDocument();
  });

  it('grants access through a module wildcard', () => {
    grantPermissions(['leads:*']);
    renderWithProviders(<PipelineCard {...cardProps(makeLead())} />);
    expect(screen.getByTestId('pipeline-action-move')).toBeInTheDocument();
    expect(screen.queryByTestId('pipeline-action-followup')).not.toBeInTheDocument();
  });
});
