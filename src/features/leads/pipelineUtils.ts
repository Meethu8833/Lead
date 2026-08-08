/**
 * src/features/leads/pipelineUtils.ts
 *
 * Pure helpers for the Lead Pipeline board: the column definitions, the sort comparators
 * and the small predicates the drag-and-drop layer needs.
 *
 * Everything here is a total function of its arguments — no hooks, no network, no React —
 * which is what lets the board's trickiest logic (ordering, and whether a drop is legal)
 * be unit tested without rendering anything.
 */

import { Lead, LeadStatus, PipelineFilters, PipelineSort } from './types';

/**
 * The board's columns, left to right.
 *
 * This is the full `LeadStatus` enum, in lifecycle order. The brief listed eight columns
 * and omitted CONTACTED, but CONTACTED is a real, reachable status — a lead sitting in it
 * would be invisible on a board that skipped it, and unreachable by drag since there
 * would be no column to drop it into. It is therefore rendered in its pipeline position
 * between NEW and MESSAGE_SENT.
 *
 * CONVERTED is the enum's terminal-success status. It was called CUSTOMER until this
 * board was built; see the note on `LeadStatus` in types.ts.
 */
export const PIPELINE_COLUMNS: LeadStatus[] = [
  'NEW',
  'CONTACTED',
  'MESSAGE_SENT',
  'REPLIED',
  'INTERESTED',
  'NEGOTIATION',
  'FOLLOW_UP',
  'CONVERTED',
  'LOST',
];

/** How many cards a column loads per page, including its first. */
export const PIPELINE_PAGE_SIZE = 20;

/** The sort options offered by the toolbar, in menu order. */
export const PIPELINE_SORT_OPTIONS: { value: PipelineSort; label: string }[] = [
  { value: 'NEWEST', label: 'Newest first' },
  { value: 'OLDEST', label: 'Oldest first' },
  { value: 'LAST_CONTACTED', label: 'Last contacted' },
  { value: 'NAME', label: 'Name (A–Z)' },
];

/** The filter bar's cleared state. Also the board's initial state. */
export const EMPTY_PIPELINE_FILTERS: PipelineFilters = {
  search: '',
  source: '',
  assigned_employee_id: '',
  city: '',
  district: '',
};

/** True when at least one filter is set, which drives the "Clear" button's visibility. */
export const hasActiveFilters = (filters: PipelineFilters): boolean =>
  Object.values(filters).some((value) => value !== '');

/**
 * Milliseconds since the epoch for an API timestamp, or null when absent/unparseable.
 *
 * Guards the comparators below: `new Date(null).getTime()` is 0 rather than NaN, which
 * would sort a never-contacted lead as though it were contacted in 1970.
 */
const timestamp = (value: string | null | undefined): number | null => {
  if (!value) return null;
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? null : parsed;
};

/**
 * Orders one column's cards.
 *
 * Sorting is client-side because `GET /leads` exposes no ordering parameter. That is
 * exact for a column whose rows are all loaded, and approximate for one that is not: the
 * server decides which 20 rows page 1 contains, and only those get ordered. The board
 * surfaces the loaded/total counts in every column header so a partially-loaded column
 * never silently claims to be a full ranking.
 *
 * Returns a new array; the input (a TanStack Query cache value) is never mutated.
 */
export const sortLeads = (leads: Lead[], sort: PipelineSort): Lead[] => {
  const sorted = [...leads];

  switch (sort) {
    case 'OLDEST':
      return sorted.sort(
        (a, b) => (timestamp(a.created_at) ?? 0) - (timestamp(b.created_at) ?? 0)
      );

    case 'NAME':
      // localeCompare so accented and non-Latin business names order sensibly rather
      // than by UTF-16 code unit, and case-insensitively so "abc" is not exiled below "Z".
      return sorted.sort((a, b) =>
        (a.business_name ?? '').localeCompare(b.business_name ?? '', undefined, {
          sensitivity: 'base',
        })
      );

    case 'LAST_CONTACTED':
      // Most recently contacted first. Never-contacted leads (null `last_contacted_at`)
      // sink to the bottom rather than floating to the top as epoch-0 — "no contact yet"
      // is not "contacted a very long time ago", and the whole point of this sort is to
      // surface the leads that were just touched.
      return sorted.sort((a, b) => {
        const left = timestamp(a.last_contacted_at);
        const right = timestamp(b.last_contacted_at);
        if (left === null && right === null) return 0;
        if (left === null) return 1;
        if (right === null) return -1;
        return right - left;
      });

    case 'NEWEST':
    default:
      return sorted.sort(
        (a, b) => (timestamp(b.created_at) ?? 0) - (timestamp(a.created_at) ?? 0)
      );
  }
};

/**
 * Whether dropping `lead` onto `target` should do anything.
 *
 * A drop onto the column a card already sits in is a no-op, not an error: it is what
 * happens when a drag is started and abandoned in place, and firing a PUT for it would
 * write a pointless STATUS_CHANGED entry onto the lead's immutable timeline.
 */
export const isMoveAllowed = (lead: Pick<Lead, 'status'>, target: LeadStatus): boolean =>
  lead.status !== target;

/**
 * The MIME type the card writes its id into on drag start.
 *
 * A custom type rather than `text/plain` so that text dragged in from outside the app
 * (or from another part of it) is not mistaken for a card by a column's drop handler.
 */
export const PIPELINE_DND_MIME = 'application/x-lead-id';
