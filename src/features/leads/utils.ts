/**
 * src/features/leads/utils.ts
 *
 * Pure presentation helpers shared across the Lead Details workspace. Everything here is
 * a total function of its arguments — no hooks, no network — so the components stay
 * dumb and these stay trivially unit-testable.
 */

import { ContactQuality, Lead } from './types';

/**
 * A Google Maps link for the lead, or null when one cannot be built.
 *
 * `Lead` has no `google_maps_url` column: the Google Maps import provider computes a
 * `source_url` but `LeadImportService` folds it into the lead's free-text `remarks`
 * rather than storing it as a field. The link is therefore derived from the
 * `latitude`/`longitude` columns, which is exactly the case that matters — leads sourced
 * from Maps are the ones that carry coordinates. Manually-entered leads without
 * coordinates get null, and the profile hides the row instead of showing a dead link.
 */
export const mapsUrlFor = (lead: Pick<Lead, 'latitude' | 'longitude'>): string | null => {
  const { latitude, longitude } = lead;
  if (latitude == null || longitude == null) return null;
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  return `https://www.google.com/maps/search/?api=1&query=${latitude},${longitude}`;
};

/**
 * Strips a phone number down to the digits (and a leading +) that a `tel:`/`wa.me` URL
 * accepts. The backend permits spaces, hyphens and parentheses in `phone`, none of which
 * belong in a link.
 */
export const normalizePhone = (phone: string | null | undefined): string => {
  if (!phone) return '';
  const trimmed = phone.trim();
  const hasPlus = trimmed.startsWith('+');
  const digits = trimmed.replace(/\D/g, '');
  return hasPlus ? `+${digits}` : digits;
};

/** A `tel:` link for the lead's phone, or null when there is no usable number. */
export const telHref = (phone: string | null | undefined): string | null => {
  const normalized = normalizePhone(phone);
  return normalized ? `tel:${normalized}` : null;
};

/**
 * Whether a lead can actually be reached on WhatsApp.
 *
 * True only when the dedicated `whatsapp` column holds a number. An ordinary `phone` is
 * deliberately not accepted: the pipeline promotes a number into `whatsapp` only when a
 * source identified it as one (a `wa.me` link on the site, a labelled WhatsApp number), so
 * treating every phone as WhatsApp-capable would send the operator into dead conversations
 * and inflate the campaign-ready count.
 */
export const isWhatsAppReady = (lead: Pick<Lead, 'whatsapp'>): boolean =>
  Boolean(normalizePhone(lead.whatsapp));

/**
 * A wa.me link for the lead, or null when no *WhatsApp* number is known.
 *
 * Only ever built from the `whatsapp` column — see `isWhatsAppReady` for why the `phone`
 * fallback this once had was removed. wa.me rejects the leading `+`, so it is stripped
 * here even though `tel:` keeps it.
 */
export const whatsAppHref = (lead: Pick<Lead, 'whatsapp'>): string | null => {
  const digits = normalizePhone(lead.whatsapp).replace(/^\+/, '');
  return digits ? `https://wa.me/${digits}` : null;
};

/**
 * Outreach priority for a lead, from what is actually stored.
 *
 * Mirrors `DiscoveredLeadRecord.contact_quality` on the backend so a lead shows the same
 * band on the pipeline as it did in the import results. Computed, never persisted.
 */
export const contactQualityOf = (
  lead: Partial<Pick<Lead, 'phone' | 'whatsapp' | 'email' | 'website' | 'instagram' | 'facebook' | 'youtube'>>
): ContactQuality => {
  const filled = (value: string | null | undefined) => Boolean(value && value.trim());
  const hasNumber = filled(lead.phone) || filled(lead.whatsapp);
  const hasWeb = filled(lead.website) || filled(lead.email);
  const hasSocial = filled(lead.instagram) || filled(lead.facebook) || filled(lead.youtube);

  if (hasNumber && (hasWeb || hasSocial)) return 'HIGH';
  if (hasNumber) return 'MEDIUM';
  if (hasWeb || hasSocial) return 'LOW';
  return 'NONE';
};

/** Maps a contact-quality band onto the Badge variants the design system already ships. */
export const contactQualityVariant = (
  quality: ContactQuality
): 'success' | 'warning' | 'secondary' | 'danger' => {
  switch (quality) {
    case 'HIGH':
      return 'success';
    case 'MEDIUM':
      return 'warning';
    case 'LOW':
      return 'secondary';
    default:
      return 'danger';
  }
};

/**
 * Turns a possibly-schemeless URL into something an anchor can navigate to.
 *
 * The backend validates URL shape but stores what was given, so `example.com` and
 * `https://example.com` both occur. Returns null for blank input.
 */
export const externalHref = (url: string | null | undefined): string | null => {
  const trimmed = url?.trim();
  if (!trimmed) return null;
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
};

/**
 * An instagram.com profile link from a stored handle.
 *
 * The backend normalizes handles by stripping a leading `@`, but full URLs also reach
 * this field, so both are handled.
 */
export const instagramHref = (handle: string | null | undefined): string | null => {
  const trimmed = handle?.trim();
  if (!trimmed) return null;
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return `https://instagram.com/${trimmed.replace(/^@/, '')}`;
};

/** A `mailto:` link, or null when there is no email. */
export const mailtoHref = (email: string | null | undefined): string | null => {
  const trimmed = email?.trim();
  return trimmed ? `mailto:${trimmed}` : null;
};

/**
 * Joins the address parts into one display line, skipping the blanks.
 *
 * Every component of a lead's location is independently nullable, so naive template
 * interpolation produces strings like ", , Kerala".
 */
export const formatAddress = (
  lead: Pick<Lead, 'address' | 'city' | 'district' | 'state' | 'country'>
): string | null => {
  const parts = [lead.address, lead.city, lead.district, lead.state, lead.country]
    .map((part) => part?.trim())
    .filter((part): part is string => !!part);
  return parts.length ? parts.join(', ') : null;
};
