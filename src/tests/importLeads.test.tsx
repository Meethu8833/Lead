/**
 * src/tests/importLeads.test.tsx
 *
 * Unit tests for the Lead Import screen.
 *
 * Organised by layer, mirroring the architecture:
 *   - utils     — validation, error translation and formatting, which are pure
 *   - services  — that the right URLs, bodies and multipart fields are sent
 *   - hooks     — cache invalidation and the derived provider breakdown
 *   - page      — provider switching, loading/success/failure states, navigation
 *   - history   — table rendering, refresh
 *   - stats     — the summary cards
 *
 * `axios` is stubbed at the `api` module boundary, the same approach the other suites in
 * this repo take, so the service layer under test is real code rather than a mock of it.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as React from 'react';
import { render, screen, waitFor, fireEvent, act, within } from '@testing-library/react';
import { renderHook } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { api } from '../services/api';
import { leadImportsService } from '../services/leads';
import ImportLeadsPage from '../features/leads/pages/ImportLeadsPage';
import { DiscoveryResults } from '../features/leads/components/DiscoveryResults';
import { DiscoveryStats } from '../features/leads/components/DiscoveryStats';
import { ImportHistoryTable } from '../features/leads/components/ImportHistoryTable';
import { ImportStatsCards } from '../features/leads/components/ImportStatsCards';
import { useProviderBreakdown, useLeadImport } from '../features/leads/importHooks';
import { leadKeys } from '../features/leads/hooks';
import {
  describeProviders,
  formatDuration,
  formatProviderName,
  toFriendlyErrorMessage,
  validateCsvFile,
  MAX_CSV_BYTES,
} from '../features/leads/importUtils';
import { useAuthStore, useNotificationStore } from '../app/store';
import {
  DiscoveryRecord,
  DiscoveryRunResult,
  ImportJob,
  ImportProvider,
  ImportStatistics,
} from '../features/leads/types';
import { leadDiscoveryService } from '../services/leads';
import {
  DEFAULT_CATEGORY,
  DISCOVERY_STAGES,
  discoveryOutcome,
  estimateStageIndex,
  formatElapsed,
  formatFieldName,
  formatRadius,
  isStageSkipped,
  radiusClampNotice,
  recordDisplayName,
  reconciles,
  stateForCity,
  summarizeDiscovery,
} from '../features/leads/discoveryUtils';
import { buildDiscoveryPayload } from '../features/leads/discoveryHooks';
import { discoverySchema } from '../features/leads/discoveryValidation';

// ==========================================
// FIXTURES & HELPERS
// ==========================================

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

const makeProvider = (overrides: Partial<ImportProvider> = {}): ImportProvider => ({
  key: 'google_maps',
  display_name: 'Google Maps',
  lead_source: 'GOOGLE_MAPS',
  requires_query: true,
  requires_file: false,
  is_available: true,
  ...overrides,
});

const PROVIDERS: ImportProvider[] = [
  makeProvider(),
  makeProvider({
    key: 'instagram',
    display_name: 'Instagram',
    lead_source: 'INSTAGRAM',
  }),
  makeProvider({
    key: 'csv',
    display_name: 'Manual CSV Import',
    lead_source: 'CSV_IMPORT',
    requires_query: false,
    requires_file: true,
  }),
];

const makeJob = (overrides: Partial<ImportJob> = {}): ImportJob => ({
  id: 'job-1',
  provider: 'google_maps',
  query: 'Wedding Photographer Kozhikode',
  status: 'COMPLETED',
  started_at: '2026-01-01T10:00:00Z',
  completed_at: '2026-01-01T10:00:04.300Z',
  total_found: 57,
  new_leads: 42,
  updated_leads: 5,
  duplicate_leads: 8,
  failed_records: 2,
  error_message: null,
  source_filename: null,
  retry_of_job_id: null,
  created_by: 'emp-1',
  version: 1,
  created_at: '2026-01-01T10:00:00Z',
  updated_at: '2026-01-01T10:00:04Z',
  ...overrides,
});

const STATS: ImportStatistics = {
  total_jobs: 12,
  total_found: 500,
  new_leads: 380,
  updated_leads: 40,
  duplicate_leads: 70,
  failed_records: 10,
  jobs_by_status: { COMPLETED: 10, PARTIAL: 1, FAILED: 1 },
};

/**
 * Routes a GET by URL so one spy can serve the three queries the page issues on mount.
 * Overrides let a single test change just the endpoint it cares about.
 */
const mockGets = (overrides: Partial<Record<'providers' | 'stats' | 'history', unknown>> = {}) =>
  vi.spyOn(api, 'get').mockImplementation((url: string) => {
    if (url.includes('/leads/import/providers')) {
      return Promise.resolve(
        overrides.providers ?? { data: { items: PROVIDERS, total: PROVIDERS.length } }
      ) as never;
    }
    if (url.includes('/leads/imports/statistics')) {
      return Promise.resolve(overrides.stats ?? { data: STATS }) as never;
    }
    return Promise.resolve(
      overrides.history ?? { data: { items: [makeJob()], total: 1, skip: 0, limit: 10 } }
    ) as never;
  });

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

const renderWithProviders = (ui: React.ReactElement, client = makeQueryClient()) =>
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  );

const grantPermissions = (permissions: string[]) => {
  useAuthStore.setState({
    permissions,
    user: { id: 'emp-1', role: { name: 'Staff' } } as never,
  });
};

/**
 * Switches to Provider Import mode and waits for the registry to land.
 *
 * The page opens in City Discovery mode, so every provider-mode test goes through here
 * first. Routing that through the existing helper rather than adding a click to each test
 * keeps the mode switch in one place — if the default mode changes again, this is the only
 * line that moves.
 */
const awaitFormReady = async () => {
  fireEvent.click(screen.getByTestId('import-mode-provider'));
  await screen.findByTestId('provider-option-google_maps');
};

/** Switches to City Discovery mode and waits for its form. */
const awaitDiscoveryReady = async () => {
  await screen.findByTestId('discovery-submit');
};

const makeDiscoveryRecord = (
  overrides: Partial<DiscoveryRecord> = {}
): DiscoveryRecord => ({
  id: 'lead-1',
  business_name: 'Sunrise Studio',
  phone: '+919876543210',
  email: 'hello@sunrise.example',
  city: 'Kozhikode',
  website: 'https://sunrise.example',
  whatsapp: null,
  instagram: null,
  facebook: null,
  youtube: null,
  source: 'OTHER',
  is_whatsapp_ready: false,
  contact_quality: 'MEDIUM',
  enriched_fields: [],
  ...overrides,
});

const makeDiscoveryResult = (
  overrides: Partial<DiscoveryRunResult> = {}
): DiscoveryRunResult => ({
  found: 10,
  imported: 6,
  merged: 2,
  duplicates: 1,
  failed: 1,
  imported_records: [makeDiscoveryRecord()],
  merged_records: [
    makeDiscoveryRecord({
      id: 'lead-2',
      business_name: 'Moonlight Photos',
      enriched_fields: ['email', 'website'],
    }),
  ],
  failed_records: [{ business_name: 'No Phone Studio', reason: 'missing phone number' }],
  stages: [{ stage: 'website_discovery', records_in: 10, records_enriched: 4 }],
  city: 'Kozhikode',
  provider: 'overpass',
  enrichment: {
    websites_discovered: 4,
    contacts_extracted: 3,
    emails_found: 2,
    phones_found: 8,
    whatsapp_found: 1,
    instagram_found: 1,
    facebook_found: 0,
    youtube_found: 0,
  },
  ...overrides,
});

const makeCsv = (name = 'leads.csv', size = 2048) => {
  const file = new File(['business_name,phone\nSunrise,999'], name, { type: 'text/csv' });
  Object.defineProperty(file, 'size', { value: size });
  return file;
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
// UTILS
// ==========================================

describe('importUtils', () => {
  it('accepts a well-formed CSV', () => {
    expect(validateCsvFile(makeCsv())).toEqual({ valid: true });
  });

  it('rejects a non-CSV extension', () => {
    const result = validateCsvFile(makeCsv('contacts.pdf'));
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/not a CSV file/i);
  });

  it('rejects a file over the size ceiling', () => {
    const result = validateCsvFile(makeCsv('huge.csv', MAX_CSV_BYTES + 1));
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/limit/i);
  });

  it('rejects an empty file', () => {
    const result = validateCsvFile(makeCsv('empty.csv', 0));
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/empty/i);
  });

  it('orders providers with the supported three first', () => {
    const shuffled = [PROVIDERS[2], PROVIDERS[1], PROVIDERS[0]];
    expect(describeProviders(shuffled).map((p) => p.key)).toEqual([
      'google_maps',
      'instagram',
      'csv',
    ]);
  });

  it('attaches capability copy to each provider', () => {
    const [maps] = describeProviders([PROVIDERS[0]]);
    expect(maps.capability.features).toContain('Official Google Places API');
    expect(maps.capability.examples).toContain('Wedding Photographer Kozhikode');
  });

  it('renders a provider with no local copy without throwing', () => {
    const [unknown] = describeProviders([makeProvider({ key: 'justdial' })]);
    expect(unknown.capability.features).toEqual([]);
  });

  it('formats a sub-minute duration in seconds', () => {
    expect(formatDuration('2026-01-01T10:00:00Z', '2026-01-01T10:00:04.300Z')).toBe(
      '4.3 seconds'
    );
  });

  it('returns null when a run has not finished', () => {
    expect(formatDuration('2026-01-01T10:00:00Z', null)).toBeNull();
  });

  it('humanises a provider key', () => {
    expect(formatProviderName('google_maps')).toBe('Google Maps');
  });
});

describe('toFriendlyErrorMessage', () => {
  it('explains a timeout without exposing the axios code', () => {
    const message = toFriendlyErrorMessage({ code: 'ECONNABORTED', message: 'timeout of 5000ms' });
    expect(message).toMatch(/took too long/i);
    expect(message).not.toMatch(/ECONNABORTED/);
  });

  it('explains a network failure', () => {
    expect(toFriendlyErrorMessage({ code: 'ERR_NETWORK', message: 'Network Error' })).toMatch(
      /could not reach the server/i
    );
  });

  it('surfaces a human-written 400 detail', () => {
    const message = toFriendlyErrorMessage({
      response: { status: 400, data: { detail: "'notes.pdf' is not a CSV file." } },
    });
    expect(message).toBe("'notes.pdf' is not a CSV file.");
  });

  it('explains a missing permission on 403', () => {
    expect(toFriendlyErrorMessage({ response: { status: 403, data: {} } })).toMatch(
      /leads:import/
    );
  });

  it('never leaks a raw 500 body', () => {
    const message = toFriendlyErrorMessage({
      response: {
        status: 500,
        data: { detail: 'psycopg2.ProgrammingError: relation "leads" does not exist' },
      },
    });
    expect(message).not.toMatch(/psycopg2/);
    expect(message).toMatch(/unexpected problem/i);
  });

  it('explains an unavailable provider on 503', () => {
    expect(toFriendlyErrorMessage({ response: { status: 503, data: {} } })).toMatch(
      /temporarily unavailable/i
    );
  });

  it('flattens a FastAPI validation array', () => {
    const message = toFriendlyErrorMessage({
      response: { status: 422, data: { detail: [{ msg: 'limit must be <= 1000' }] } },
    });
    expect(message).toMatch(/limit must be <= 1000/);
  });
});

// ==========================================
// SERVICES
// ==========================================

describe('leadImportsService', () => {
  it('POSTs a query-driven import with the provider payload', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: makeJob() } as never);

    await leadImportsService.runImport({
      provider: 'google_maps',
      query: 'Studio Calicut',
      limit: 50,
    });

    expect(post).toHaveBeenCalledWith(
      '/leads/import',
      { provider: 'google_maps', query: 'Studio Calicut', limit: 50 },
      expect.objectContaining({ timeout: expect.any(Number) })
    );
  });

  it('POSTs a CSV as multipart with the file and limit fields', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: makeJob() } as never);

    await leadImportsService.importCsv(makeCsv(), 100);

    const [url, body] = post.mock.calls[0];
    expect(url).toBe('/leads/import/csv');
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get('limit')).toBe('100');
    expect((body as FormData).get('file')).toBeInstanceOf(File);
  });

  it('reports upload progress as a percentage', async () => {
    const onProgress = vi.fn();
    vi.spyOn(api, 'post').mockImplementation(((
      _url: string,
      _body: unknown,
      config?: { onUploadProgress?: (event: { loaded: number; total: number }) => void }
    ) => {
      config?.onUploadProgress?.({ loaded: 512, total: 2048 });
      return Promise.resolve({ data: makeJob() });
    }) as never);

    await leadImportsService.importCsv(makeCsv(), 50, onProgress);
    expect(onProgress).toHaveBeenCalledWith(25);
  });

  it('GETs the provider registry', async () => {
    const get = vi
      .spyOn(api, 'get')
      .mockResolvedValue({ data: { items: PROVIDERS, total: 3 } } as never);

    await leadImportsService.listProviders();
    expect(get).toHaveBeenCalledWith('/leads/import/providers');
  });

  it('GETs statistics from its own endpoint', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: STATS } as never);
    await leadImportsService.getStatistics();
    expect(get).toHaveBeenCalledWith('/leads/imports/statistics');
  });

  it('GETs history with pagination and filters', async () => {
    const get = vi
      .spyOn(api, 'get')
      .mockResolvedValue({ data: { items: [], total: 0, skip: 0, limit: 10 } } as never);

    await leadImportsService.listJobsFiltered({ limit: 25, provider: 'instagram' });

    expect(get).toHaveBeenCalledWith('/leads/imports', {
      params: { skip: 0, limit: 25, provider: 'instagram' },
    });
  });

  it('POSTs a retry to the job-scoped endpoint', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: makeJob() } as never);
    await leadImportsService.retryJob('job-9');
    expect(post.mock.calls[0][0]).toBe('/leads/imports/job-9/retry');
  });
});

// ==========================================
// HOOKS
// ==========================================

describe('useLeadImport', () => {
  it('invalidates the lead cache root so the pipeline refreshes', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({ data: makeJob() } as never);
    const client = makeQueryClient();
    const invalidate = vi.spyOn(client, 'invalidateQueries');

    const { result } = renderHook(() => useLeadImport(), { wrapper: wrapperWith(client) });

    act(() => {
      result.current.run({
        provider: 'google_maps',
        query: 'Studio Calicut',
        limit: 50,
        file: null,
      });
    });

    await waitFor(() => expect(result.current.result).not.toBeNull());
    expect(invalidate).toHaveBeenCalledWith({ queryKey: leadKeys.all });
  });

  it('raises a success toast naming the imported count', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({ data: makeJob() } as never);
    const client = makeQueryClient();

    const { result } = renderHook(() => useLeadImport(), { wrapper: wrapperWith(client) });

    act(() => {
      result.current.run({ provider: 'google_maps', query: 'x', limit: 50, file: null });
    });

    await waitFor(() => {
      const toasts = useNotificationStore.getState().toasts;
      expect(toasts.some((t) => t.type === 'success' && /42/.test(t.message))).toBe(true);
    });
  });

  it('raises a warning toast for a PARTIAL run rather than calling it a success', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({
      data: makeJob({ status: 'PARTIAL', failed_records: 3 }),
    } as never);

    const { result } = renderHook(() => useLeadImport(), {
      wrapper: wrapperWith(makeQueryClient()),
    });

    act(() => {
      result.current.run({ provider: 'google_maps', query: 'x', limit: 50, file: null });
    });

    await waitFor(() => {
      expect(useNotificationStore.getState().toasts.some((t) => t.type === 'warning')).toBe(
        true
      );
    });
  });

  it('surfaces a friendly message when the request fails', async () => {
    vi.spyOn(api, 'post').mockRejectedValue({
      response: { status: 500, data: { detail: 'Traceback: KeyError' } },
    });

    const { result } = renderHook(() => useLeadImport(), {
      wrapper: wrapperWith(makeQueryClient()),
    });

    act(() => {
      result.current.run({ provider: 'google_maps', query: 'x', limit: 50, file: null });
    });

    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.error).not.toMatch(/Traceback/);
    expect(useNotificationStore.getState().toasts.some((t) => t.type === 'error')).toBe(true);
  });

  it('routes a file import to the CSV endpoint', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      data: makeJob({ provider: 'csv', source_filename: 'leads.csv' }),
    } as never);

    const { result } = renderHook(() => useLeadImport(), {
      wrapper: wrapperWith(makeQueryClient()),
    });

    act(() => {
      result.current.run({ provider: 'csv', query: '', limit: 50, file: makeCsv() });
    });

    await waitFor(() => expect(result.current.result).not.toBeNull());
    expect(post.mock.calls[0][0]).toBe('/leads/import/csv');
  });
});

describe('useProviderBreakdown', () => {
  it('aggregates runs per provider, highest imported first', () => {
    const jobs = [
      { provider: 'google_maps', new_leads: 10 },
      { provider: 'instagram', new_leads: 30 },
      { provider: 'google_maps', new_leads: 5 },
    ];
    const { result } = renderHook(() => useProviderBreakdown(jobs, 3));

    expect(result.current.rows).toEqual([
      { provider: 'instagram', jobs: 1, imported: 30 },
      { provider: 'google_maps', jobs: 2, imported: 15 },
    ]);
    expect(result.current.isSampled).toBe(false);
  });

  it('flags the breakdown as sampled when history is truncated', () => {
    const { result } = renderHook(() =>
      useProviderBreakdown([{ provider: 'csv', new_leads: 1 }], 40)
    );
    expect(result.current.isSampled).toBe(true);
  });
});

// ==========================================
// PAGE — PROVIDER SWITCHING & VALIDATION
// ==========================================

describe('ImportLeadsPage — providers', () => {
  it('renders the three providers and defaults to Google Maps', async () => {
    mockGets();
    renderWithProviders(<ImportLeadsPage />);
    await awaitFormReady();

    expect(screen.getByTestId('provider-option-instagram')).toBeInTheDocument();
    expect(screen.getByTestId('provider-option-csv')).toBeInTheDocument();
    expect(screen.getByLabelText(/search keyword/i)).toBeInTheDocument();
  });

  it('shows the Google Maps capability panel', async () => {
    mockGets();
    renderWithProviders(<ImportLeadsPage />);
    await awaitFormReady();

    const panel = screen.getByTestId('provider-info-panel');
    expect(panel).toHaveTextContent('Official Google Places API');
    expect(panel).toHaveTextContent('Ratings');
  });

  it('swaps the panel when Instagram is selected', async () => {
    mockGets();
    renderWithProviders(<ImportLeadsPage />);
    await awaitFormReady();

    fireEvent.click(screen.getByTestId('provider-option-instagram'));

    await waitFor(() => {
      expect(screen.getByTestId('provider-info-panel')).toHaveTextContent('Bio Parsing');
    });
  });

  it('hides the keyword input and shows the drop zone for CSV', async () => {
    mockGets();
    renderWithProviders(<ImportLeadsPage />);
    await awaitFormReady();

    fireEvent.click(screen.getByTestId('provider-option-csv'));

    await waitFor(() => {
      expect(screen.getByTestId('csv-dropzone')).toBeInTheDocument();
    });
    expect(screen.queryByLabelText(/search keyword/i)).not.toBeInTheDocument();
  });

  it('warns instead of allowing a run when a provider has no credentials', async () => {
    mockGets({
      providers: {
        data: {
          items: [makeProvider({ is_available: false })],
          total: 1,
        },
      },
    });
    renderWithProviders(<ImportLeadsPage />);
    await awaitFormReady();

    expect(await screen.findByText(/not configured on this server/i)).toBeInTheDocument();
    expect(screen.getByTestId('import-submit')).toBeDisabled();
  });

  it('blocks submission with an empty keyword', async () => {
    mockGets();
    const post = vi.spyOn(api, 'post');
    renderWithProviders(<ImportLeadsPage />);
    await awaitFormReady();

    fireEvent.submit(screen.getByTestId('import-submit').closest('form')!);

    expect(await screen.findByText(/enter a search keyword/i)).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it('blocks a CSV run with no file chosen', async () => {
    mockGets();
    const post = vi.spyOn(api, 'post');
    renderWithProviders(<ImportLeadsPage />);
    await awaitFormReady();

    fireEvent.click(screen.getByTestId('provider-option-csv'));
    await screen.findByTestId('csv-dropzone');
    fireEvent.submit(screen.getByTestId('import-submit').closest('form')!);

    expect(await screen.findByText(/choose a csv file/i)).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it('rejects a non-CSV file at the drop zone', async () => {
    mockGets();
    renderWithProviders(<ImportLeadsPage />);
    await awaitFormReady();

    fireEvent.click(screen.getByTestId('provider-option-csv'));
    await screen.findByTestId('csv-dropzone');

    fireEvent.change(screen.getByTestId('csv-file-input'), {
      target: { files: [makeCsv('notes.pdf')] },
    });
    fireEvent.submit(screen.getByTestId('import-submit').closest('form')!);

    expect(await screen.findByText(/is not a CSV file/i)).toBeInTheDocument();
  });
});

// ==========================================
// PAGE — IMPORT LIFECYCLE
// ==========================================

describe('ImportLeadsPage — running an import', () => {
  it('runs a Google Maps import and shows the result summary', async () => {
    mockGets();
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: makeJob() } as never);

    renderWithProviders(<ImportLeadsPage />);
    await awaitFormReady();

    fireEvent.change(screen.getByLabelText(/search keyword/i), {
      target: { value: 'Wedding Photographer Kozhikode' },
    });
    fireEvent.click(screen.getByTestId('import-submit'));

    const summary = await screen.findByTestId('import-result-summary');
    expect(summary).toHaveTextContent('Import Complete');
    expect(summary).toHaveTextContent('42');
    expect(summary).toHaveTextContent('4.3 seconds');

    expect(post).toHaveBeenCalledWith(
      '/leads/import',
      expect.objectContaining({
        provider: 'google_maps',
        query: 'Wedding Photographer Kozhikode',
      }),
      expect.anything()
    );
  });

  it('runs an Instagram import through the same endpoint', async () => {
    mockGets();
    const post = vi
      .spyOn(api, 'post')
      .mockResolvedValue({ data: makeJob({ provider: 'instagram' }) } as never);

    renderWithProviders(<ImportLeadsPage />);
    await awaitFormReady();

    fireEvent.click(screen.getByTestId('provider-option-instagram'));
    fireEvent.change(screen.getByLabelText(/search keyword/i), {
      target: { value: 'Studio Calicut' },
    });
    fireEvent.click(screen.getByTestId('import-submit'));

    await screen.findByTestId('import-result-summary');
    expect(post.mock.calls[0][1]).toMatchObject({ provider: 'instagram' });
  });

  it('uploads a CSV and reports its outcome', async () => {
    mockGets();
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      data: makeJob({ provider: 'csv', source_filename: 'leads.csv', query: null }),
    } as never);

    renderWithProviders(<ImportLeadsPage />);
    await awaitFormReady();

    fireEvent.click(screen.getByTestId('provider-option-csv'));
    await screen.findByTestId('csv-dropzone');

    fireEvent.change(screen.getByTestId('csv-file-input'), {
      target: { files: [makeCsv()] },
    });
    expect(await screen.findByText('leads.csv')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('import-submit'));

    const summary = await screen.findByTestId('import-result-summary');
    expect(summary).toHaveTextContent('leads.csv');
    expect(post.mock.calls[0][0]).toBe('/leads/import/csv');
  });

  it('disables the button and shows progress while importing', async () => {
    mockGets();
    let resolvePost: (value: unknown) => void = () => {};
    vi.spyOn(api, 'post').mockReturnValue(
      new Promise((resolve) => {
        resolvePost = resolve;
      }) as never
    );

    renderWithProviders(<ImportLeadsPage />);
    await awaitFormReady();

    fireEvent.change(screen.getByLabelText(/search keyword/i), {
      target: { value: 'Studio Calicut' },
    });
    fireEvent.click(screen.getByTestId('import-submit'));

    await waitFor(() => expect(screen.getByTestId('import-submit')).toBeDisabled());
    expect(screen.getByText(/import running/i)).toBeInTheDocument();

    await act(async () => {
      resolvePost({ data: makeJob() });
    });
    await screen.findByTestId('import-result-summary');
  });

  it('does not fire a second request while one is in flight', async () => {
    mockGets();
    const post = vi.spyOn(api, 'post').mockReturnValue(new Promise(() => {}) as never);

    renderWithProviders(<ImportLeadsPage />);
    await awaitFormReady();

    fireEvent.change(screen.getByLabelText(/search keyword/i), {
      target: { value: 'Studio Calicut' },
    });
    const button = screen.getByTestId('import-submit');
    fireEvent.click(button);
    await waitFor(() => expect(button).toBeDisabled());
    fireEvent.click(button);
    fireEvent.click(button);

    expect(post).toHaveBeenCalledTimes(1);
  });

  it('keeps the form and toasts an error when the import fails', async () => {
    mockGets();
    vi.spyOn(api, 'post').mockRejectedValue({
      response: { status: 503, data: { detail: 'upstream boom' } },
    });

    renderWithProviders(<ImportLeadsPage />);
    await awaitFormReady();

    fireEvent.change(screen.getByLabelText(/search keyword/i), {
      target: { value: 'Studio Calicut' },
    });
    fireEvent.click(screen.getByTestId('import-submit'));

    await waitFor(() => {
      expect(
        useNotificationStore.getState().toasts.some((t) => t.type === 'error')
      ).toBe(true);
    });
    expect(screen.queryByTestId('import-result-summary')).not.toBeInTheDocument();
    expect(screen.getByTestId('import-submit')).not.toBeDisabled();
  });

  it('shows a failed run as failed rather than complete', async () => {
    mockGets();
    vi.spyOn(api, 'post').mockResolvedValue({
      data: makeJob({
        status: 'FAILED',
        new_leads: 0,
        error_message: 'Provider returned no results.',
      }),
    } as never);

    renderWithProviders(<ImportLeadsPage />);
    await awaitFormReady();

    fireEvent.change(screen.getByLabelText(/search keyword/i), {
      target: { value: 'Studio Calicut' },
    });
    fireEvent.click(screen.getByTestId('import-submit'));

    const summary = await screen.findByTestId('import-result-summary');
    expect(summary).toHaveTextContent('Import Failed');
    expect(summary).toHaveTextContent('Provider returned no results.');
  });

  it('returns to an empty form on Import Again', async () => {
    mockGets();
    vi.spyOn(api, 'post').mockResolvedValue({ data: makeJob() } as never);

    renderWithProviders(<ImportLeadsPage />);
    await awaitFormReady();

    fireEvent.change(screen.getByLabelText(/search keyword/i), {
      target: { value: 'Studio Calicut' },
    });
    fireEvent.click(screen.getByTestId('import-submit'));

    fireEvent.click(await screen.findByTestId('import-again-button'));

    await waitFor(() => {
      expect(screen.queryByTestId('import-result-summary')).not.toBeInTheDocument();
    });
    expect(screen.getByLabelText(/search keyword/i)).toHaveValue('');
  });
});

// ==========================================
// NAVIGATION & CACHE
// ==========================================

describe('ImportLeadsPage — navigation and cache', () => {
  it('navigates to the lead pipeline from View Leads', async () => {
    mockGets();
    vi.spyOn(api, 'post').mockResolvedValue({ data: makeJob() } as never);

    renderWithProviders(<ImportLeadsPage />);
    await awaitFormReady();

    fireEvent.change(screen.getByLabelText(/search keyword/i), {
      target: { value: 'Studio Calicut' },
    });
    fireEvent.click(screen.getByTestId('import-submit'));

    fireEvent.click(await screen.findByTestId('view-leads-button'));
    expect(mockNavigate).toHaveBeenCalledWith('/leads');
  });

  it('invalidates the lead queries after a successful import', async () => {
    mockGets();
    vi.spyOn(api, 'post').mockResolvedValue({ data: makeJob() } as never);

    const client = makeQueryClient();
    const invalidate = vi.spyOn(client, 'invalidateQueries');

    renderWithProviders(<ImportLeadsPage />, client);
    await awaitFormReady();

    fireEvent.change(screen.getByLabelText(/search keyword/i), {
      target: { value: 'Studio Calicut' },
    });
    fireEvent.click(screen.getByTestId('import-submit'));

    await screen.findByTestId('import-result-summary');
    expect(invalidate).toHaveBeenCalledWith({ queryKey: leadKeys.all });
  });

  it('refuses the screen without the leads:import permission', async () => {
    grantPermissions(['leads:view']);
    mockGets();

    renderWithProviders(<ImportLeadsPage />);
    await awaitFormReady();

    expect(screen.getByText(/you cannot run imports/i)).toBeInTheDocument();
    expect(screen.getByTestId('import-submit')).toBeDisabled();
  });
});

// ==========================================
// HISTORY
// ==========================================

describe('ImportHistoryTable', () => {
  it('renders a run with all its columns', () => {
    renderWithProviders(
      <ImportHistoryTable jobs={[makeJob()]} onRefresh={vi.fn()} />
    );

    const row = screen.getByTestId('history-row-job-1');
    expect(row).toHaveTextContent('Google Maps');
    expect(row).toHaveTextContent('Wedding Photographer Kozhikode');
    expect(row).toHaveTextContent('42');
    expect(row).toHaveTextContent('8');
    expect(row).toHaveTextContent('COMPLETED');
    expect(row).toHaveTextContent('4.3 seconds');
  });

  it('renders an empty state with no runs', () => {
    renderWithProviders(<ImportHistoryTable jobs={[]} onRefresh={vi.fn()} />);
    expect(screen.getByText(/no imports yet/i)).toBeInTheDocument();
  });

  it('renders an error state and offers a retry', () => {
    const onRefresh = vi.fn();
    renderWithProviders(<ImportHistoryTable jobs={[]} isError onRefresh={onRefresh} />);
    expect(screen.getByText(/could not load the import history/i)).toBeInTheDocument();
  });

  it('refreshes on demand', () => {
    const onRefresh = vi.fn();
    renderWithProviders(<ImportHistoryTable jobs={[makeJob()]} onRefresh={onRefresh} />);

    fireEvent.click(screen.getByTestId('refresh-history'));
    expect(onRefresh).toHaveBeenCalled();
  });

  it('offers retry only for a retryable, non-file run', () => {
    const onRetry = vi.fn();
    renderWithProviders(
      <ImportHistoryTable
        jobs={[makeJob({ status: 'FAILED' })]}
        onRefresh={vi.fn()}
        onRetry={onRetry}
        canRetry
      />
    );

    fireEvent.click(screen.getAllByLabelText(/retry the google maps import/i)[0]);
    expect(onRetry).toHaveBeenCalledWith('job-1');
  });

  it('does not offer retry for a CSV upload, whose bytes are not retained', () => {
    renderWithProviders(
      <ImportHistoryTable
        jobs={[makeJob({ status: 'FAILED', provider: 'csv', source_filename: 'a.csv' })]}
        onRefresh={vi.fn()}
        onRetry={vi.fn()}
        canRetry
      />
    );
    expect(screen.queryByLabelText(/retry the/i)).not.toBeInTheDocument();
  });

  it('renders the history the page fetched', async () => {
    mockGets({
      history: {
        data: {
          items: [makeJob({ id: 'job-7', query: 'Studio Calicut' })],
          total: 1,
          skip: 0,
          limit: 10,
        },
      },
    });

    renderWithProviders(<ImportLeadsPage />);
    expect(await screen.findByTestId('history-row-job-7')).toHaveTextContent(
      'Studio Calicut'
    );
  });
});

// ==========================================
// STATISTICS
// ==========================================

describe('ImportStatsCards', () => {
  it('renders the four headline figures', () => {
    renderWithProviders(
      <ImportStatsCards statistics={STATS} lastImportAt={null} breakdown={[]} />
    );

    expect(screen.getByText('Total Imports')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('380')).toBeInTheDocument();
    expect(screen.getByText('70')).toBeInTheDocument();
    expect(screen.getByText('Never')).toBeInTheDocument();
  });

  it('renders the provider breakdown', () => {
    renderWithProviders(
      <ImportStatsCards
        statistics={STATS}
        lastImportAt={null}
        breakdown={[{ provider: 'google_maps', jobs: 2, imported: 15 }]}
      />
    );

    const breakdown = screen.getByTestId('provider-breakdown');
    expect(breakdown).toHaveTextContent('Google Maps');
    expect(breakdown).toHaveTextContent('15 leads');
  });

  it('says so when the breakdown is only a sample', () => {
    renderWithProviders(
      <ImportStatsCards
        statistics={STATS}
        lastImportAt={null}
        breakdown={[{ provider: 'csv', jobs: 1, imported: 3 }]}
        breakdownIsSampled
      />
    );
    expect(screen.getByText(/not the full history/i)).toBeInTheDocument();
  });

  it('renders statistics on the page from the endpoint', async () => {
    mockGets();
    renderWithProviders(<ImportLeadsPage />);
    await awaitFormReady();

    await waitFor(() => {
      expect(screen.getByText('Total Leads Imported')).toBeInTheDocument();
    });
    expect(screen.getByText('380')).toBeInTheDocument();
  });
});

// ==========================================
// DISCOVERY — UTILS
// ==========================================

describe('discoveryUtils', () => {
  it('resolves the state of a curated city, case-insensitively', () => {
    expect(stateForCity('Kozhikode')).toBe('Kerala');
    expect(stateForCity('  bengaluru  ')).toBe('Karnataka');
  });

  it('returns no state for a city outside the curated list', () => {
    expect(stateForCity('Springfield')).toBeNull();
  });

  it('warns only when the radius exceeds the provider clamp', () => {
    expect(radiusClampNotice(10)).toBeNull();
    expect(radiusClampNotice(50)).toBeNull();
    expect(radiusClampNotice(80)).toMatch(/caps searches at 50 km/i);
    expect(radiusClampNotice(null)).toBeNull();
  });

  it('formats a radius without a trailing zero', () => {
    expect(formatRadius(10)).toBe('10 km');
    expect(formatRadius(12.5)).toBe('12.5 km');
  });

  it('reconciles counters that add up, and rejects ones that do not', () => {
    expect(reconciles(makeDiscoveryResult())).toBe(true);
    expect(reconciles(makeDiscoveryResult({ found: 99 }))).toBe(false);
  });

  it('classifies an empty run as empty rather than failed', () => {
    const empty = makeDiscoveryResult({
      found: 0,
      imported: 0,
      merged: 0,
      duplicates: 0,
      failed: 0,
    });
    expect(discoveryOutcome(empty)).toBe('empty');
    expect(summarizeDiscovery(empty)).toMatch(/no businesses were found/i);
  });

  it('classifies a run where nothing saved and failures dominate as failed', () => {
    const result = makeDiscoveryResult({
      found: 5,
      imported: 0,
      merged: 0,
      duplicates: 1,
      failed: 4,
    });
    expect(discoveryOutcome(result)).toBe('failed');
  });

  it('classifies an all-duplicates re-run as partial, not failed', () => {
    const result = makeDiscoveryResult({
      found: 5,
      imported: 0,
      merged: 0,
      duplicates: 5,
      failed: 0,
    });
    expect(discoveryOutcome(result)).toBe('partial');
  });

  it('classifies a clean run as success and a run with failures as partial', () => {
    const clean = makeDiscoveryResult({
      found: 5,
      imported: 5,
      merged: 0,
      duplicates: 0,
      failed: 0,
    });
    expect(discoveryOutcome(clean)).toBe('success');
    expect(discoveryOutcome(makeDiscoveryResult())).toBe('partial');
  });

  it('summarises a run in one line', () => {
    expect(summarizeDiscovery(makeDiscoveryResult())).toBe(
      '6 new leads imported, 2 leads enriched, 1 duplicate skipped, 1 record failed — from 10 records found.'
    );
  });

  it('falls back through contact details for an unnamed record', () => {
    expect(recordDisplayName(makeDiscoveryRecord())).toBe('Sunrise Studio');
    expect(
      recordDisplayName(makeDiscoveryRecord({ business_name: null }))
    ).toBe('+919876543210');
    expect(
      recordDisplayName(
        makeDiscoveryRecord({ business_name: null, phone: null, email: null })
      )
    ).toBe('Unnamed record');
  });

  it('humanises a snake_case field name', () => {
    expect(formatFieldName('business_name')).toBe('Business Name');
    expect(formatFieldName('email')).toBe('Email');
  });

  it('formats elapsed time as mm:ss', () => {
    expect(formatElapsed(0)).toBe('0:00');
    expect(formatElapsed(65)).toBe('1:05');
    expect(formatElapsed(-5)).toBe('0:00');
  });

  it('advances the estimated stage as time passes', () => {
    const first = estimateStageIndex(0);
    const later = estimateStageIndex(20);
    expect(first).toBe(0);
    expect(later).toBeGreaterThan(first);
  });

  it('never runs the estimate past the final stage', () => {
    expect(estimateStageIndex(100000)).toBe(DISCOVERY_STAGES.length - 1);
  });

  it('skips disabled enrichment stages when estimating', () => {
    // With both network stages off, the same elapsed time reaches a later stage.
    const withEnrichment = estimateStageIndex(5, {
      discoverWebsites: true,
      extractContacts: true,
    });
    const withoutEnrichment = estimateStageIndex(5, {
      discoverWebsites: false,
      extractContacts: false,
    });
    expect(withoutEnrichment).toBeGreaterThan(withEnrichment);
  });

  it('reports which stages the toggles skip', () => {
    const off = { discoverWebsites: false, extractContacts: false };
    expect(isStageSkipped(1, off)).toBe(true);
    expect(isStageSkipped(2, off)).toBe(true);
    expect(isStageSkipped(0, off)).toBe(false);
    expect(
      isStageSkipped(1, { discoverWebsites: true, extractContacts: false })
    ).toBe(false);
  });
});

// ==========================================
// DISCOVERY — VALIDATION
// ==========================================

describe('discoverySchema', () => {
  const valid = {
    city: 'Kozhikode',
    category: DEFAULT_CATEGORY,
    radius_km: 10,
    limit: 100,
    discover_websites: true,
    extract_contacts: true,
  };

  it('accepts a well-formed form', () => {
    expect(discoverySchema.safeParse(valid).success).toBe(true);
  });

  it('accepts a null radius, which defers to the provider default', () => {
    expect(discoverySchema.safeParse({ ...valid, radius_km: null }).success).toBe(true);
  });

  it('requires a city', () => {
    const result = discoverySchema.safeParse({ ...valid, city: '   ' });
    expect(result.success).toBe(false);
  });

  it('rejects a radius outside the API bounds', () => {
    expect(discoverySchema.safeParse({ ...valid, radius_km: 0 }).success).toBe(false);
    expect(discoverySchema.safeParse({ ...valid, radius_km: 101 }).success).toBe(false);
  });

  it('accepts a radius between the clamp point and the API bound', () => {
    // 80 km is valid and merely clamped server-side — rejecting it would refuse a
    // request the backend honours.
    expect(discoverySchema.safeParse({ ...valid, radius_km: 80 }).success).toBe(true);
  });

  it('rejects a limit outside 1..1000 and a fractional one', () => {
    expect(discoverySchema.safeParse({ ...valid, limit: 0 }).success).toBe(false);
    expect(discoverySchema.safeParse({ ...valid, limit: 1001 }).success).toBe(false);
    expect(discoverySchema.safeParse({ ...valid, limit: 10.5 }).success).toBe(false);
  });
});

// ==========================================
// DISCOVERY — PAYLOAD MAPPING
// ==========================================

describe('buildDiscoveryPayload', () => {
  const base = {
    city: 'Kozhikode',
    category: 'wedding photography',
    radius_km: 25,
    limit: 50,
    discover_websites: true,
    extract_contacts: false,
  };

  it('maps the form onto the request body', () => {
    expect(buildDiscoveryPayload(base)).toEqual({
      city: 'Kozhikode',
      category: 'wedding photography',
      state: 'Kerala',
      radius_km: 25,
      limit: 50,
      discover_websites: true,
      extract_contacts: false,
    });
  });

  it('omits radius_km entirely when blank, so the adapter defaults it', () => {
    const payload = buildDiscoveryPayload({ ...base, radius_km: null });
    expect('radius_km' in payload).toBe(false);
  });

  it('omits state for a city outside the curated list', () => {
    const payload = buildDiscoveryPayload({ ...base, city: 'Springfield' });
    expect('state' in payload).toBe(false);
    expect(payload.city).toBe('Springfield');
  });

  it('falls back to the default category when blank', () => {
    expect(buildDiscoveryPayload({ ...base, category: '   ' }).category).toBe(
      DEFAULT_CATEGORY
    );
  });

  it('trims the city', () => {
    expect(buildDiscoveryPayload({ ...base, city: '  Kochi  ' }).city).toBe('Kochi');
  });
});

// ==========================================
// DISCOVERY — SERVICE
// ==========================================

describe('leadDiscoveryService', () => {
  it('POSTs to /leads/discover with a long timeout', async () => {
    const post = vi
      .spyOn(api, 'post')
      .mockResolvedValue({ data: makeDiscoveryResult() } as never);

    await leadDiscoveryService.discover({
      city: 'Kozhikode',
      category: 'photography',
      radius_km: 20,
      limit: 100,
      discover_websites: true,
      extract_contacts: true,
    });

    const [url, body, config] = post.mock.calls[0];
    expect(url).toBe('/leads/discover');
    expect(body).toMatchObject({ city: 'Kozhikode', radius_km: 20 });
    expect((config as { timeout: number }).timeout).toBeGreaterThan(60_000);
  });

  it('drops radius_km from the body when it is not a number', async () => {
    const post = vi
      .spyOn(api, 'post')
      .mockResolvedValue({ data: makeDiscoveryResult() } as never);

    await leadDiscoveryService.discover({
      city: 'Kochi',
      category: 'photography',
      limit: 100,
      discover_websites: true,
      extract_contacts: true,
    });

    expect(post.mock.calls[0][1]).not.toHaveProperty('radius_km');
  });
});

// ==========================================
// DISCOVERY — PAGE
// ==========================================

describe('ImportLeadsPage — city discovery', () => {
  it('opens in discovery mode with the city, category and radius controls', async () => {
    mockGets();
    renderWithProviders(<ImportLeadsPage />);
    await awaitDiscoveryReady();

    expect(screen.getByTestId('discovery-city')).toBeInTheDocument();
    expect(screen.getByTestId('discovery-category')).toBeInTheDocument();
    expect(screen.getByTestId('discovery-radius')).toBeInTheDocument();
    expect(screen.getByTestId('discovery-submit')).toHaveTextContent(/start import/i);
  });

  it('switches to provider import and back', async () => {
    mockGets();
    renderWithProviders(<ImportLeadsPage />);
    await awaitDiscoveryReady();

    fireEvent.click(screen.getByTestId('import-mode-provider'));
    expect(await screen.findByTestId('provider-option-google_maps')).toBeInTheDocument();
    expect(screen.queryByTestId('discovery-submit')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('import-mode-discovery'));
    expect(await screen.findByTestId('discovery-submit')).toBeInTheDocument();
  });

  it('blocks submission until a city is chosen', async () => {
    mockGets();
    const post = vi.spyOn(api, 'post');
    renderWithProviders(<ImportLeadsPage />);
    await awaitDiscoveryReady();

    fireEvent.click(screen.getByTestId('discovery-submit'));

    expect(await screen.findByText(/choose a city to search in/i)).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it('runs a discovery and renders its statistics and results', async () => {
    mockGets();
    const post = vi
      .spyOn(api, 'post')
      .mockResolvedValue({ data: makeDiscoveryResult() } as never);

    renderWithProviders(<ImportLeadsPage />);
    await awaitDiscoveryReady();

    fireEvent.change(screen.getByTestId('discovery-city'), {
      target: { value: 'Kozhikode' },
    });
    fireEvent.click(screen.getByTestId('discovery-submit'));

    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][0]).toBe('/leads/discover');
    expect(post.mock.calls[0][1]).toMatchObject({ city: 'Kozhikode', state: 'Kerala' });

    // The five counters land, and the results tabs render alongside them.
    expect(await screen.findByTestId('discovery-stats')).toBeInTheDocument();
    expect(screen.getByTestId('discovery-results')).toBeInTheDocument();
    expect(screen.getByTestId('discovery-tab-imported')).toHaveTextContent('(6)');
    expect(screen.getByTestId('discovery-tab-merged')).toHaveTextContent('(2)');
    expect(screen.getByTestId('discovery-tab-duplicates')).toHaveTextContent('(1)');
    expect(screen.getByTestId('discovery-tab-failed')).toHaveTextContent('(1)');
  });

  it('shows live progress with named stages while the run is open', async () => {
    mockGets();
    let resolvePost: (value: unknown) => void = () => {};
    vi.spyOn(api, 'post').mockImplementation(
      () => new Promise((resolve) => { resolvePost = resolve; }) as never
    );

    renderWithProviders(<ImportLeadsPage />);
    await awaitDiscoveryReady();

    fireEvent.change(screen.getByTestId('discovery-city'), {
      target: { value: 'Kochi' },
    });
    fireEvent.click(screen.getByTestId('discovery-submit'));

    const progress = await screen.findByTestId('discovery-progress');
    expect(progress).toHaveTextContent(/importing leads from kochi/i);
    expect(screen.getByTestId('discovery-stages')).toBeInTheDocument();
    expect(screen.getByTestId('discovery-stage-collect')).toBeInTheDocument();
    // The estimate is labelled as an estimate rather than presented as observed truth.
    expect(progress).toHaveTextContent(/estimated from elapsed time/i);

    await act(async () => {
      resolvePost({ data: makeDiscoveryResult() });
    });

    await waitFor(() =>
      expect(screen.queryByTestId('discovery-progress')).not.toBeInTheDocument()
    );
  });

  it('marks skipped enrichment stages when the toggles are off', async () => {
    mockGets();
    vi.spyOn(api, 'post').mockImplementation(() => new Promise(() => {}) as never);

    renderWithProviders(<ImportLeadsPage />);
    await awaitDiscoveryReady();

    fireEvent.change(screen.getByTestId('discovery-city'), {
      target: { value: 'Kochi' },
    });
    fireEvent.click(screen.getByTestId('discovery-websites'));
    fireEvent.click(screen.getByTestId('discovery-submit'));

    await screen.findByTestId('discovery-progress');
    expect(screen.getByTestId('discovery-stage-website')).toHaveTextContent(/skipped/i);
  });

  it('warns when the radius exceeds the provider clamp but still allows the run', async () => {
    mockGets();
    renderWithProviders(<ImportLeadsPage />);
    await awaitDiscoveryReady();

    fireEvent.change(screen.getByTestId('discovery-radius'), {
      target: { value: '80' },
    });

    expect(await screen.findByText(/caps searches at 50 km/i)).toBeInTheDocument();
    expect(screen.getByTestId('discovery-submit')).not.toBeDisabled();
  });

  it('offers a free-text city input for a city outside the list', async () => {
    mockGets();
    renderWithProviders(<ImportLeadsPage />);
    await awaitDiscoveryReady();

    fireEvent.change(screen.getByTestId('discovery-city'), {
      target: { value: '__custom__' },
    });

    expect(await screen.findByTestId('discovery-city-input')).toBeInTheDocument();
  });

  it('invalidates the lead cache so every list and chart refetches', async () => {
    mockGets();
    vi.spyOn(api, 'post').mockResolvedValue({ data: makeDiscoveryResult() } as never);

    const client = makeQueryClient();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    renderWithProviders(<ImportLeadsPage />, client);
    await awaitDiscoveryReady();

    fireEvent.change(screen.getByTestId('discovery-city'), {
      target: { value: 'Kozhikode' },
    });
    fireEvent.click(screen.getByTestId('discovery-submit'));

    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({ queryKey: leadKeys.all })
    );
  });

  it('reports a failed run through a toast rather than a blank screen', async () => {
    mockGets();
    vi.spyOn(api, 'post').mockRejectedValue({
      response: { data: { detail: 'Lead discovery source unavailable: Overpass timed out' } },
    });

    renderWithProviders(<ImportLeadsPage />);
    await awaitDiscoveryReady();

    fireEvent.change(screen.getByTestId('discovery-city'), {
      target: { value: 'Kozhikode' },
    });
    fireEvent.click(screen.getByTestId('discovery-submit'));

    await waitFor(() => {
      const toasts = useNotificationStore.getState().toasts;
      expect(toasts.some((t) => t.type === 'error')).toBe(true);
    });
    // The form stays put so the operator can adjust and retry.
    expect(screen.getByTestId('discovery-submit')).toBeInTheDocument();
  });

  it('locks the form to a viewer without the import permission', async () => {
    mockGets();
    grantPermissions(['leads:view']);
    renderWithProviders(<ImportLeadsPage />);
    await awaitDiscoveryReady();

    expect(screen.getByTestId('discovery-submit')).toBeDisabled();
    expect(screen.getByText(/you cannot run imports/i)).toBeInTheDocument();
  });

  it('returns to the form when Import Again is pressed', async () => {
    mockGets();
    vi.spyOn(api, 'post').mockResolvedValue({ data: makeDiscoveryResult() } as never);

    renderWithProviders(<ImportLeadsPage />);
    await awaitDiscoveryReady();

    fireEvent.change(screen.getByTestId('discovery-city'), {
      target: { value: 'Kozhikode' },
    });
    fireEvent.click(screen.getByTestId('discovery-submit'));

    await screen.findByTestId('discovery-stats');
    fireEvent.click(screen.getByRole('button', { name: /import again/i }));

    expect(await screen.findByTestId('discovery-submit')).toBeInTheDocument();
    expect(screen.queryByTestId('discovery-stats')).not.toBeInTheDocument();
  });
});

// ==========================================
// DISCOVERY — RESULTS TABLES
// ==========================================

describe('DiscoveryResults', () => {
  const renderResults = (result = makeDiscoveryResult()) =>
    renderWithProviders(<DiscoveryResults result={result} />);

  it('lists imported records with their contact details', () => {
    renderResults();
    expect(screen.getByText('Sunrise Studio')).toBeInTheDocument();
    expect(screen.getByText('+919876543210')).toBeInTheDocument();
  });

  it('shows the enriched fields on the merged tab', () => {
    renderResults();
    fireEvent.click(screen.getByTestId('discovery-tab-merged'));

    expect(screen.getByText('Moonlight Photos')).toBeInTheDocument();
    // Scoped to the row: "Email" and "Website" are also column headers, so an unscoped
    // query matches both the header and the badge.
    const row = screen.getByText('Moonlight Photos').closest('tr') as HTMLElement;
    expect(within(row).getByText('Email')).toBeInTheDocument();
    expect(within(row).getByText('Website')).toBeInTheDocument();
  });

  it('makes the phone number callable with a tel: link', () => {
    renderResults();
    expect(screen.getByTestId('discovery-phone-link')).toHaveAttribute(
      'href',
      'tel:+919876543210'
    );
  });

  it('links a known WhatsApp number to wa.me without the leading +', () => {
    renderResults(
      makeDiscoveryResult({
        imported_records: [
          makeDiscoveryRecord({ whatsapp: '+919876500000', is_whatsapp_ready: true }),
        ],
      })
    );

    expect(screen.getByTestId('discovery-whatsapp-link')).toHaveAttribute(
      'href',
      'https://wa.me/919876500000'
    );
  });

  it('never builds a wa.me link from an ordinary phone number', () => {
    // The record has a phone but no confirmed WhatsApp number. Offering a wa.me link here
    // would invite the operator to message a number nothing has said is on WhatsApp.
    renderResults(
      makeDiscoveryResult({
        imported_records: [
          makeDiscoveryRecord({ whatsapp: null, is_whatsapp_ready: false }),
        ],
      })
    );

    expect(screen.queryByTestId('discovery-whatsapp-link')).not.toBeInTheDocument();
  });

  it('opens website and social links in a new tab with safe rel attributes', () => {
    renderResults(
      makeDiscoveryResult({
        imported_records: [
          makeDiscoveryRecord({
            website: 'https://sunrise.example',
            instagram: 'sunrisestudio',
            facebook: 'https://facebook.com/sunrisestudio',
          }),
        ],
      })
    );

    for (const testId of [
      'discovery-website-link',
      'discovery-instagram-link',
      'discovery-facebook-link',
    ]) {
      const link = screen.getByTestId(testId);
      expect(link).toHaveAttribute('target', '_blank');
      // noopener blocks window.opener access; noreferrer withholds the referrer from a
      // page whose URL we did not author.
      expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    }

    expect(screen.getByTestId('discovery-instagram-link')).toHaveAttribute(
      'href',
      'https://instagram.com/sunrisestudio'
    );
  });

  it('shows a dash rather than a dead link for contact fields that were not collected', () => {
    renderResults(
      makeDiscoveryResult({
        imported_records: [
          makeDiscoveryRecord({ website: null, instagram: null, facebook: null }),
        ],
      })
    );

    expect(screen.queryByTestId('discovery-website-link')).not.toBeInTheDocument();
    expect(screen.queryByTestId('discovery-instagram-link')).not.toBeInTheDocument();
    expect(screen.queryByTestId('discovery-facebook-link')).not.toBeInTheDocument();
  });

  it('shows the contact-quality band so the operator can prioritise', () => {
    renderResults(
      makeDiscoveryResult({
        imported_records: [makeDiscoveryRecord({ contact_quality: 'HIGH' })],
      })
    );

    const row = screen.getByText('Sunrise Studio').closest('tr') as HTMLElement;
    expect(within(row).getByText('HIGH')).toBeInTheDocument();
  });

  it('truncates long URLs but keeps the full value available on hover', () => {
    const longUrl = `https://example.com/${'a'.repeat(120)}`;
    renderResults(
      makeDiscoveryResult({
        imported_records: [makeDiscoveryRecord({ website: longUrl })],
      })
    );

    const link = screen.getByTestId('discovery-website-link');
    expect(link.className).toContain('truncate');
    expect(link).toHaveAttribute('title', longUrl.replace(/^https?:\/\//, ''));
  });

  it('shows failed records with their reason', () => {
    renderResults();
    fireEvent.click(screen.getByTestId('discovery-tab-failed'));

    expect(screen.getByText('No Phone Studio')).toBeInTheDocument();
    expect(screen.getByText(/missing phone number/i)).toBeInTheDocument();
  });

  it('explains the duplicates count, which has no per-record rows', () => {
    renderResults();
    fireEvent.click(screen.getByTestId('discovery-tab-duplicates'));

    expect(screen.getByText(/1 duplicate skipped/i)).toBeInTheDocument();
    expect(screen.getByText(/added nothing new/i)).toBeInTheDocument();
  });

  it('shows an empty state per tab rather than a blank table', () => {
    renderResults(
      makeDiscoveryResult({
        found: 0,
        imported: 0,
        merged: 0,
        duplicates: 0,
        failed: 0,
        imported_records: [],
        merged_records: [],
        failed_records: [],
      })
    );

    expect(screen.getByText(/no new leads/i)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('discovery-tab-failed'));
    expect(screen.getByText(/nothing failed/i)).toBeInTheDocument();
  });
});

// ==========================================
// DISCOVERY — STATS
// ==========================================

describe('DiscoveryStats', () => {
  it('renders the five counters with found as the denominator', () => {
    renderWithProviders(<DiscoveryStats result={makeDiscoveryResult()} />);

    expect(screen.getByText('Found')).toBeInTheDocument();
    expect(screen.getByText('Imported')).toBeInTheDocument();
    expect(screen.getByText('Enriched')).toBeInTheDocument();
    expect(screen.getByText('Duplicates')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
  });

  it('flags counters that do not reconcile instead of hiding the discrepancy', () => {
    renderWithProviders(<DiscoveryStats result={makeDiscoveryResult({ found: 99 })} />);
    expect(screen.getByTestId('discovery-reconcile-warning')).toBeInTheDocument();
  });

  it('stays silent when the counters add up', () => {
    renderWithProviders(<DiscoveryStats result={makeDiscoveryResult()} />);
    expect(screen.queryByTestId('discovery-reconcile-warning')).not.toBeInTheDocument();
  });

  it('renders an empty run as a neutral outcome, not an error', () => {
    renderWithProviders(
      <DiscoveryStats
        result={makeDiscoveryResult({
          found: 0,
          imported: 0,
          merged: 0,
          duplicates: 0,
          failed: 0,
        })}
      />
    );
    expect(screen.getByTestId('discovery-outcome-banner')).toHaveTextContent(
      /nothing found/i
    );
  });

  it('lists the per-stage diagnostics', () => {
    renderWithProviders(<DiscoveryStats result={makeDiscoveryResult()} />);
    expect(screen.getByTestId('discovery-stage-stats')).toHaveTextContent(
      /4 of 10 enriched/i
    );
  });

  it('reports the enrichment statistics the backend sent, verbatim', () => {
    renderWithProviders(<DiscoveryStats result={makeDiscoveryResult()} />);

    // Each figure is rendered exactly as received. Nothing on this panel is computed on
    // the client, so a wrong number here can only be a wrong number from the server.
    expect(screen.getByTestId('discovery-enrichment-websites_discovered')).toHaveTextContent('4');
    expect(screen.getByTestId('discovery-enrichment-contacts_extracted')).toHaveTextContent('3');
    expect(screen.getByTestId('discovery-enrichment-phones_found')).toHaveTextContent('8');
    expect(screen.getByTestId('discovery-enrichment-whatsapp_found')).toHaveTextContent('1');
    expect(screen.getByTestId('discovery-enrichment-emails_found')).toHaveTextContent('2');
    expect(screen.getByTestId('discovery-enrichment-facebook_found')).toHaveTextContent('0');
  });
});
