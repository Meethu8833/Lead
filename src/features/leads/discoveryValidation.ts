/**
 * src/features/leads/discoveryValidation.ts
 *
 * Zod schema for the City Discovery form, following the same convention as
 * `importValidation.ts`: the schema lives beside the feature, not inside the component.
 *
 * Unlike the import schema this is a constant rather than a factory — discovery has no
 * per-provider conditional rules, because the pipeline owns its own source. Every bound
 * mirrors `DiscoveryRunRequest` in `app/schemas/import_job.py` so the field reports the
 * problem instead of the server returning a 422 about it.
 *
 * One rule is deliberately looser than it looks: `radius_km` is optional and `null` means
 * "let the adapter decide", which is why the payload omits the key entirely rather than
 * sending null. See `DiscoveryRunPayload` in `types.ts`.
 */

import { z } from 'zod';
import {
  MAX_CATEGORY_LENGTH,
  MAX_CITY_LENGTH,
  MAX_DISCOVERY_LIMIT,
  MAX_RADIUS_KM,
  MIN_DISCOVERY_LIMIT,
  MIN_RADIUS_KM,
} from './discoveryUtils';

export const discoverySchema = z.object({
  city: z
    .string()
    .trim()
    .min(1, 'Choose a city to search in.')
    .max(MAX_CITY_LENGTH, `Keep the city under ${MAX_CITY_LENGTH} characters.`),

  category: z
    .string()
    .trim()
    .max(MAX_CATEGORY_LENGTH, `Keep the category under ${MAX_CATEGORY_LENGTH} characters.`),

  /**
   * Null is valid and meaningful: it defers to the provider's own default radius. The
   * bound is the API's `le=100`, not the adapter's 50 km clamp — a value between the two is
   * accepted and then clamped, so rejecting it here would refuse a workable request.
   * `radiusClampNotice` warns about that range instead.
   */
  radius_km: z
    .number({ invalid_type_error: 'Enter a radius in kilometres, or leave it blank.' })
    .min(MIN_RADIUS_KM, `Search at least ${MIN_RADIUS_KM} km around the city.`)
    .max(MAX_RADIUS_KM, `Search at most ${MAX_RADIUS_KM} km around the city.`)
    .nullable(),

  limit: z
    .number({ invalid_type_error: 'Enter how many records to collect.' })
    .int('Maximum records must be a whole number.')
    .min(MIN_DISCOVERY_LIMIT, `Collect at least ${MIN_DISCOVERY_LIMIT} record.`)
    .max(MAX_DISCOVERY_LIMIT, `Collect at most ${MAX_DISCOVERY_LIMIT} records in one run.`),

  discover_websites: z.boolean(),
  extract_contacts: z.boolean(),
});

export type DiscoveryFormSchema = z.infer<typeof discoverySchema>;
