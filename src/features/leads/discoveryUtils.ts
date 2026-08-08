/**
 * src/features/leads/discoveryUtils.ts
 *
 * Pure rules for the City Discovery mode of the Lead Import screen. Nothing here touches
 * React, the network or a store — every function is a value in, value out, which is what
 * makes this the layer the unit tests lean on hardest.
 *
 * Discovery is not provider import. An import names a *source* and hands it a keyword;
 * discovery names a *place* and runs a fixed six-stage pipeline over it. The two share a
 * screen and a permission, but they share none of the rules below — which is why these live
 * apart from `importUtils.ts` rather than growing it.
 *
 * The bounds here mirror the backend's, deliberately duplicated so a bad value is caught at
 * the field rather than as a 422. The server stays the authority: the Overpass adapter
 * clamps the radius to its own configured ceiling regardless of what this file says.
 */

import { DiscoveryRecord, DiscoveryRunResult } from './types';

// ==========================================
// BOUNDS — mirrors of backend settings
// ==========================================

/**
 * Radius bounds, in kilometres.
 *
 * `MAX` is `DiscoveryRunRequest.radius_km`'s `le=100` validation bound, not the Overpass
 * adapter's `OVERPASS_MAX_RADIUS_KM` (50 by default). The distinction matters: a value
 * between the two is *accepted* by the API and then silently clamped by the adapter, so
 * rejecting it here would refuse a request the backend would have honoured. `SOFT_MAX` is
 * that clamp point, used only to warn — see `radiusClampNotice`.
 */
export const MIN_RADIUS_KM = 1;
export const MAX_RADIUS_KM = 100;
export const SOFT_MAX_RADIUS_KM = 50;

/** `settings.OVERPASS_DEFAULT_RADIUS_KM`. Applied by the adapter when we send nothing. */
export const DEFAULT_RADIUS_KM = 10;

/** Mirrors `DiscoveryRunRequest.limit` (`ge=1, le=1000`). */
export const MIN_DISCOVERY_LIMIT = 1;
export const MAX_DISCOVERY_LIMIT = 1000;
export const DEFAULT_DISCOVERY_LIMIT = 100;

/** `DEFAULT_QUERY` in app/services/lead_discovery.py. */
export const DEFAULT_CATEGORY = 'photography';

/** `DiscoveryRunRequest.city` / `.category` / `.state` max_length. */
export const MAX_CITY_LENGTH = 100;
export const MAX_CATEGORY_LENGTH = 100;

// ==========================================
// SELECTOR OPTIONS
// ==========================================

export interface DiscoveryOption {
  value: string;
  label: string;
}

/**
 * Cities offered in the selector.
 *
 * A curated list rather than a fetched one: there is no cities endpoint, and the backend
 * geocodes free text anyway, so this is a convenience over an input rather than a
 * constraint on it. `state` travels alongside because several Indian city names are
 * ambiguous without it (Hyderabad, Aurangabad), and the geocoder resolves the wrong one
 * often enough to matter.
 *
 * The selector allows a custom value, so an operator is never blocked by an absent city —
 * this list is the common path, not the whole space.
 */
export interface DiscoveryCity extends DiscoveryOption {
  state: string;
}

export const DISCOVERY_CITIES: DiscoveryCity[] = [
  { value: 'Kozhikode', label: 'Kozhikode (Calicut)', state: 'Kerala' },
  { value: 'Kochi', label: 'Kochi (Ernakulam)', state: 'Kerala' },
  { value: 'Thiruvananthapuram', label: 'Thiruvananthapuram', state: 'Kerala' },
  { value: 'Thrissur', label: 'Thrissur', state: 'Kerala' },
  { value: 'Kannur', label: 'Kannur', state: 'Kerala' },
  { value: 'Kollam', label: 'Kollam', state: 'Kerala' },
  { value: 'Alappuzha', label: 'Alappuzha', state: 'Kerala' },
  { value: 'Palakkad', label: 'Palakkad', state: 'Kerala' },
  { value: 'Malappuram', label: 'Malappuram', state: 'Kerala' },
  { value: 'Kottayam', label: 'Kottayam', state: 'Kerala' },
  { value: 'Bengaluru', label: 'Bengaluru', state: 'Karnataka' },
  { value: 'Mangaluru', label: 'Mangaluru', state: 'Karnataka' },
  { value: 'Chennai', label: 'Chennai', state: 'Tamil Nadu' },
  { value: 'Coimbatore', label: 'Coimbatore', state: 'Tamil Nadu' },
  { value: 'Madurai', label: 'Madurai', state: 'Tamil Nadu' },
  { value: 'Hyderabad', label: 'Hyderabad', state: 'Telangana' },
  { value: 'Mumbai', label: 'Mumbai', state: 'Maharashtra' },
  { value: 'Pune', label: 'Pune', state: 'Maharashtra' },
  { value: 'Delhi', label: 'Delhi', state: 'Delhi' },
  { value: 'Goa', label: 'Goa (Panaji)', state: 'Goa' },
];

/**
 * Categories offered in the selector.
 *
 * The values are the free-text search term the pipeline passes through as its query, and
 * are also recorded on every collected record as a lead category tag. Only `photography`
 * corresponds to a dedicated OSM tag filter in the Overpass adapter; the rest lean on the
 * adapter's general matching, so they yield less. That is worth knowing but not worth
 * hiding — an operator looking for videographers should be able to ask.
 */
export const DISCOVERY_CATEGORIES: DiscoveryOption[] = [
  { value: 'photography', label: 'Photography studios' },
  { value: 'wedding photography', label: 'Wedding photography' },
  { value: 'photographer', label: 'Photographers' },
  { value: 'videography', label: 'Videography' },
  { value: 'event photography', label: 'Event photography' },
  { value: 'portrait studio', label: 'Portrait studios' },
  { value: 'photo lab', label: 'Photo labs & printing' },
];

/** Looks up a curated city's state, so the form can send it without a second field. */
export function stateForCity(city: string): string | null {
  const match = DISCOVERY_CITIES.find(
    (entry) => entry.value.toLowerCase() === city.trim().toLowerCase()
  );
  return match?.state ?? null;
}

/**
 * Warns when a radius exceeds the adapter's clamp point.
 *
 * Returns a message rather than an error: the request is valid and will succeed, it just
 * will not search as far as the number suggests. Telling the operator beats letting them
 * believe they searched 80 km.
 */
export function radiusClampNotice(radiusKm: number | null | undefined): string | null {
  if (typeof radiusKm !== 'number' || Number.isNaN(radiusKm)) return null;
  if (radiusKm <= SOFT_MAX_RADIUS_KM) return null;
  return `The source caps searches at ${SOFT_MAX_RADIUS_KM} km, so this run will search ${SOFT_MAX_RADIUS_KM} km rather than ${formatRadius(radiusKm)}.`;
}

/** Renders a radius without a trailing `.0` on whole numbers. */
export function formatRadius(radiusKm: number): string {
  const rounded = Math.round(radiusKm * 10) / 10;
  return Number.isInteger(rounded) ? `${rounded} km` : `${rounded.toFixed(1)} km`;
}

// ==========================================
// RESULT INTERPRETATION
// ==========================================

/**
 * Whether a finished run's counters add up.
 *
 * The backend promises `imported + merged + duplicates + failed === found`. Checking it
 * client-side is cheap and catches the one bug this screen cannot otherwise notice: a
 * results table silently missing rows. `discoveryOutcome` downgrades a mismatched run to a
 * warning rather than hiding it.
 */
export function reconciles(result: DiscoveryRunResult): boolean {
  return (
    result.imported + result.merged + result.duplicates + result.failed === result.found
  );
}

export type DiscoveryOutcome = 'success' | 'partial' | 'empty' | 'failed';

/**
 * Classifies a finished run for the summary banner.
 *
 * The distinction that matters is `empty` versus `failed`. A run that found nothing is not
 * an error — the city genuinely has no mapped studios in that radius, and the fix is a
 * bigger radius or a different category, not a retry. A run where everything found was
 * unstorable *is* a problem worth flagging.
 */
export function discoveryOutcome(result: DiscoveryRunResult): DiscoveryOutcome {
  if (result.found === 0) return 'empty';
  if (result.imported === 0 && result.merged === 0) {
    // Nothing landed. Failure-dominated means something is wrong; otherwise every record
    // was simply a duplicate of a lead already held, which is a normal re-run.
    return result.failed > result.duplicates ? 'failed' : 'partial';
  }
  if (result.failed > 0 || !reconciles(result)) return 'partial';
  return 'success';
}

/** Maps an outcome onto the Badge/StatCard variants the design system already ships. */
export function discoveryOutcomeVariant(
  outcome: DiscoveryOutcome
): 'success' | 'warning' | 'danger' | 'secondary' {
  switch (outcome) {
    case 'success':
      return 'success';
    case 'partial':
      return 'warning';
    case 'failed':
      return 'danger';
    default:
      return 'secondary';
  }
}

/** One-line human summary of a finished run, for the banner and the toast. */
export function summarizeDiscovery(result: DiscoveryRunResult): string {
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

  if (result.found === 0) {
    return 'No businesses were found. Try a wider radius or a different category.';
  }

  const parts = [`${plural(result.imported, 'new lead')} imported`];
  if (result.merged > 0) parts.push(`${plural(result.merged, 'lead')} enriched`);
  if (result.duplicates > 0) parts.push(`${plural(result.duplicates, 'duplicate')} skipped`);
  if (result.failed > 0) parts.push(`${plural(result.failed, 'record')} failed`);

  return `${parts.join(', ')} — from ${plural(result.found, 'record')} found.`;
}

/**
 * Best available display name for a discovered record.
 *
 * A lead with no business name should not render as an empty table cell; the backend only
 * stores one when it has one, so falling through to contact details keeps the row
 * identifiable.
 */
export function recordDisplayName(record: DiscoveryRecord): string {
  return record.business_name?.trim() || record.phone?.trim() || record.email?.trim() || 'Unnamed record';
}

/** Turns a snake_case field name from `enriched_fields` into table-ready text. */
export function formatFieldName(field: string): string {
  return field
    .split('_')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

// ==========================================
// PROGRESS ESTIMATION
// ==========================================

/**
 * The pipeline's stages, in the order the service runs them.
 *
 * Named here so the progress panel can show *what* is happening during a run. The backend
 * reports stage effect only after the fact (in `result.stages`), so during the run these
 * are advanced by elapsed-time estimate, not by observation — `estimateStageIndex` is
 * explicit about that being a guess.
 */
export const DISCOVERY_STAGES = [
  { key: 'collect', label: 'Finding businesses', detail: 'Searching the map around the city' },
  { key: 'website', label: 'Discovering websites', detail: 'Locating official sites' },
  { key: 'contacts', label: 'Reading contacts', detail: 'Extracting phones and emails' },
  { key: 'normalize', label: 'Normalising', detail: 'Canonicalising phone numbers' },
  { key: 'dedupe', label: 'Checking duplicates', detail: 'Matching against existing leads' },
  { key: 'save', label: 'Saving leads', detail: 'Writing new and enriched leads' },
] as const;

/**
 * Rough seconds each stage takes, used only to animate the progress panel.
 *
 * The two network-bound enrichment stages dominate: they fetch one page per discovered
 * website, so they are an order of magnitude slower than the local ones. These weights are
 * an honest guess at shape, not a measurement — see `estimateStageIndex`.
 */
const STAGE_WEIGHTS = [3, 10, 12, 1, 2, 3];

/**
 * Guesses which stage a run is in from how long it has been going.
 *
 * This is an estimate and the UI must present it as one. The endpoint is synchronous and
 * writes no job row, so there is genuinely nothing to observe mid-run — the alternative is
 * a bare spinner for up to several minutes, which tells the operator less. When the backend
 * grows a job row to poll, this function is what gets deleted; the panel reads real stages
 * instead.
 *
 * Skipped stages are excluded so the estimate does not stall on work that is not running.
 */
export function estimateStageIndex(
  elapsedSeconds: number,
  options: { discoverWebsites: boolean; extractContacts: boolean } = {
    discoverWebsites: true,
    extractContacts: true,
  }
): number {
  const active = DISCOVERY_STAGES.map((_stage, index) => ({ index, weight: STAGE_WEIGHTS[index] }))
    .filter(({ index }) => {
      if (index === 1) return options.discoverWebsites;
      if (index === 2) return options.extractContacts;
      return true;
    });

  let consumed = 0;
  for (const stage of active) {
    consumed += stage.weight;
    if (elapsedSeconds < consumed) return stage.index;
  }

  // Past the estimate: hold on the final stage rather than running off the end. A slow run
  // is still running, and claiming it finished would be worse than claiming it is saving.
  return DISCOVERY_STAGES.length - 1;
}

/** Whether a stage is skipped by the current toggles, for rendering it as struck through. */
export function isStageSkipped(
  stageIndex: number,
  options: { discoverWebsites: boolean; extractContacts: boolean }
): boolean {
  if (stageIndex === 1) return !options.discoverWebsites;
  if (stageIndex === 2) return !options.extractContacts;
  return false;
}

/** `mm:ss` elapsed-time display for the progress panel. */
export function formatElapsed(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safe / 60);
  const remainder = safe % 60;
  return `${minutes}:${remainder.toString().padStart(2, '0')}`;
}
