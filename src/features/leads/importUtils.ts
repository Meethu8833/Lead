/**
 * src/features/leads/importUtils.ts
 *
 * Pure helpers for the Lead Import screen: the provider catalogue, file validation, error
 * translation and display formatting. Nothing here touches React, the network or a store,
 * which is what lets the whole set be unit tested directly.
 *
 * The provider catalogue is the one piece worth explaining. The backend already returns a
 * registry (`GET /leads/import/providers`) and that response is the authority on which
 * providers exist and whether each is runnable — availability is a deployment fact (an API
 * key present or absent), so the UI must never hardcode it. What the registry does not
 * carry is marketing copy: the capability bullets shown in the information panel. Those
 * live here, keyed by provider key, and are merged onto whatever the registry returns.
 * A provider with no entry still renders correctly with an empty bullet list.
 */

import { ImportJobStatus, ImportProvider } from './types';

/** Ceiling the CSV endpoint enforces (MAX_CSV_BYTES in lead_imports.py). */
export const MAX_CSV_BYTES = 10 * 1024 * 1024;

/** Extensions the CSV endpoint accepts. Mirrors its own `endswith` check. */
export const ACCEPTED_CSV_EXTENSIONS = ['.csv', '.txt'] as const;

/**
 * Bounds on the "Maximum Results" input.
 *
 * The backend's `ImportRunRequest` allows up to 1000, but this screen caps at 500 by
 * product decision: a single synchronous run of a thousand upstream lookups is slow enough
 * to look broken. The floor and default match the specification.
 */
export const MIN_IMPORT_LIMIT = 1;
export const MAX_IMPORT_LIMIT = 500;
export const DEFAULT_IMPORT_LIMIT = 50;

/** Keys of the providers this screen is built around. */
export const PROVIDER_GOOGLE_MAPS = 'google_maps';
export const PROVIDER_INSTAGRAM = 'instagram';
export const PROVIDER_CSV = 'csv';

/** Presentation-only copy describing what a provider yields. */
export interface ProviderCapability {
  /** Short blurb under the provider name. */
  summary: string;
  /** The ✔ bullets in the information panel. */
  features: string[];
  /** Example queries offered as one-click fills. Empty for file providers. */
  examples: string[];
}

/**
 * Capability copy per provider key. Keyed rather than listed so that a provider the
 * registry returns but this map does not know still renders — see `describeProvider`.
 */
export const PROVIDER_CAPABILITIES: Record<string, ProviderCapability> = {
  [PROVIDER_GOOGLE_MAPS]: {
    summary: 'Business listings collected through the official Google Places API.',
    features: [
      'Official Google Places API',
      'Phone Numbers',
      'Website',
      'Address',
      'Ratings',
      'Business Categories',
    ],
    examples: [
      'Wedding Photographer Kozhikode',
      'Wedding Photographer Kerala',
      'Studio Calicut',
    ],
  },
  [PROVIDER_INSTAGRAM]: {
    summary: 'Public business accounts discovered through the Instagram Graph API.',
    features: [
      'Business Accounts',
      'Bio Parsing',
      'Website',
      'Username',
      'Contact extraction where available',
    ],
    examples: [
      'Wedding Photographer Kozhikode',
      'Wedding Photographer Kerala',
      'Studio Calicut',
    ],
  },
  [PROVIDER_CSV]: {
    summary: 'Upload a spreadsheet exported from any source and import it in bulk.',
    features: ['Bulk Import', 'Duplicate Detection'],
    examples: [],
  },
};

/** The three providers this screen offers, in display order. */
export const SUPPORTED_PROVIDER_KEYS = [
  PROVIDER_GOOGLE_MAPS,
  PROVIDER_INSTAGRAM,
  PROVIDER_CSV,
] as const;

/** A registry entry merged with its local presentation copy. */
export interface DescribedProvider extends ImportProvider {
  capability: ProviderCapability;
}

/** Fallback copy for a provider the registry exposes but this module has no entry for. */
const EMPTY_CAPABILITY: ProviderCapability = { summary: '', features: [], examples: [] };

/**
 * Merges registry entries with local copy and orders them for display.
 *
 * Providers named in `SUPPORTED_PROVIDER_KEYS` come first in that order; anything else the
 * registry reports follows alphabetically, so a newly registered backend provider appears
 * in this UI without a frontend change.
 */
export function describeProviders(providers: ImportProvider[]): DescribedProvider[] {
  const described = providers.map((provider) => ({
    ...provider,
    capability: PROVIDER_CAPABILITIES[provider.key] ?? EMPTY_CAPABILITY,
  }));

  const rank = (key: string) => {
    const index = SUPPORTED_PROVIDER_KEYS.indexOf(key as (typeof SUPPORTED_PROVIDER_KEYS)[number]);
    return index === -1 ? SUPPORTED_PROVIDER_KEYS.length : index;
  };

  return described.sort((a, b) => {
    const delta = rank(a.key) - rank(b.key);
    return delta !== 0 ? delta : a.key.localeCompare(b.key);
  });
}

/** Turns "google_maps" into "Google Maps" for display. */
export function formatProviderName(provider: string): string {
  return provider
    .split(/[_\-\s]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');
}

/** Human-readable byte size, e.g. "1.4 MB". */
export function formatBytes(bytes: number): string {
  if (bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const exponent = Math.min(
    units.length - 1,
    Math.floor(Math.log(bytes) / Math.log(1024))
  );
  const value = bytes / Math.pow(1024, exponent);
  return `${parseFloat(value.toFixed(1))} ${units[exponent]}`;
}

/**
 * Formats a run's duration from its start/end timestamps.
 *
 * Returns null rather than a placeholder when either end is missing, so callers decide how
 * an unfinished run should read instead of having "0 seconds" forced on them.
 */
export function formatDuration(
  startedAt: string | null,
  completedAt: string | null
): string | null {
  if (!startedAt || !completedAt) return null;

  const start = new Date(startedAt).getTime();
  const end = new Date(completedAt).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return null;

  const seconds = (end - start) / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)} seconds`;

  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  return `${minutes}m ${remainder}s`;
}

/** Maps a job status onto the Badge variants the design system already ships. */
export function importStatusVariant(
  status: ImportJobStatus
): 'success' | 'warning' | 'danger' | 'info' | 'secondary' {
  switch (status) {
    case 'COMPLETED':
      return 'success';
    case 'PARTIAL':
      return 'warning';
    case 'FAILED':
      return 'danger';
    case 'RUNNING':
      return 'info';
    default:
      return 'secondary';
  }
}

/** Outcome of validating a file the user picked or dropped. */
export interface FileValidationResult {
  valid: boolean;
  error?: string;
}

/**
 * Validates a CSV before it is ever uploaded.
 *
 * Both rules mirror checks the endpoint performs, deliberately duplicated client-side so a
 * 10 MB mistake is caught before it crosses the network. The server remains the authority;
 * this is a courtesy, not the enforcement point.
 */
export function validateCsvFile(file: File): FileValidationResult {
  const name = file.name.toLowerCase();
  const hasValidExtension = ACCEPTED_CSV_EXTENSIONS.some((ext) => name.endsWith(ext));

  if (!hasValidExtension) {
    return {
      valid: false,
      error: `"${file.name}" is not a CSV file. Please choose a .csv file.`,
    };
  }
  if (file.size === 0) {
    return { valid: false, error: `"${file.name}" is empty. Please choose a file with rows in it.` };
  }
  if (file.size > MAX_CSV_BYTES) {
    return {
      valid: false,
      error: `"${file.name}" is ${formatBytes(file.size)}, which is over the ${formatBytes(
        MAX_CSV_BYTES
      )} limit.`,
    };
  }
  return { valid: true };
}

/** Shape of the API's error envelope (see app/core/exceptions.py). */
interface ApiErrorBody {
  detail?: unknown;
  error_code?: string;
}

interface AxiosLikeError {
  code?: string;
  message?: string;
  response?: { status?: number; data?: ApiErrorBody };
}

/** Pulls a readable string out of the `detail` field, which may be a FastAPI error array. */
function readDetail(detail: unknown): string | null {
  if (typeof detail === 'string' && detail.trim()) return detail.trim();

  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => {
        if (typeof entry === 'string') return entry;
        if (entry && typeof entry === 'object' && 'msg' in entry) {
          return String((entry as { msg: unknown }).msg);
        }
        return null;
      })
      .filter((value): value is string => Boolean(value));
    if (messages.length) return messages.join('. ');
  }
  return null;
}

/**
 * Translates any thrown value into a message safe to show a user.
 *
 * The rule this encodes: a raw backend string is surfaced only for statuses whose bodies
 * are written for humans (400/404/409/422 come from our own `AppException`s and say things
 * like "not a CSV file"). A 500 body may carry a stack trace or driver text, so it is
 * replaced wholesale — the requirement never to expose raw backend errors is about exactly
 * that class of response.
 */
export function toFriendlyErrorMessage(error: unknown): string {
  const fallback = 'Something went wrong while importing. Please try again.';
  if (!error || typeof error !== 'object') return fallback;

  const err = error as AxiosLikeError;

  if (err.code === 'ECONNABORTED' || /timeout/i.test(err.message ?? '')) {
    return 'The import took too long to finish. It may still be running — check the import history in a moment before retrying.';
  }
  if (err.code === 'ERR_NETWORK' || err.message === 'Network Error') {
    return 'Could not reach the server. Check your connection and try again.';
  }

  const status = err.response?.status;
  if (status === undefined) return fallback;

  const detail = readDetail(err.response?.data?.detail);

  switch (status) {
    case 400:
    case 404:
    case 409:
    case 422:
      return detail ?? 'That import request was not valid. Please review the form and try again.';
    case 401:
      return 'Your session has expired. Please sign in again.';
    case 403:
      return 'You do not have permission to import leads. Ask an administrator for the "leads:import" permission.';
    case 413:
      return 'That file is too large to upload. Please split it into smaller files.';
    case 429:
      return 'The provider is rate-limiting requests right now. Please wait a minute and try again.';
    case 502:
    case 503:
    case 504:
      return 'The lead provider is temporarily unavailable. Please try again shortly.';
    default:
      return status >= 500
        ? 'The server hit an unexpected problem running this import. The team has been notified — please try again shortly.'
        : detail ?? fallback;
  }
}

/**
 * Explains why a provider cannot be run, or null when it can.
 *
 * `is_available: false` from the registry means the adapter has no credentials configured
 * (or is a declared-but-unimplemented source), which is the "missing API key" case the UI
 * must handle without letting the user fire a request that is certain to fail.
 */
export function providerUnavailableReason(
  provider: DescribedProvider | undefined
): string | null {
  if (!provider) return null;
  if (provider.is_available) return null;
  return `${provider.display_name} is not configured on this server yet. An administrator needs to add its API credentials before it can be used.`;
}
