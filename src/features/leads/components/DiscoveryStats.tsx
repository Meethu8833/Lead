/**
 * src/features/leads/components/DiscoveryStats.tsx
 *
 * The five counters a finished discovery run reports, as design-system `StatCard`s, with a
 * banner classifying the outcome and the per-stage diagnostics beneath.
 *
 * Presentational: `discoveryOutcome`, `summarizeDiscovery` and `reconciles` are pure
 * functions in `discoveryUtils.ts`, and this file only chooses icons and layout for what
 * they return.
 *
 * Two details worth keeping:
 *
 *  - **`found` is the denominator, so it is rendered apart from the four outcomes.** The
 *    other four sum to it; showing all five in one undifferentiated row invites reading
 *    them as five parallel figures that add up to more than the run collected.
 *
 *  - **A failed reconciliation is shown, not swallowed.** The backend promises the four
 *    outcomes sum to `found`. If they ever do not, the results tables are missing rows, and
 *    a quiet UI would be the only thing standing between that bug and an operator trusting
 *    a wrong number.
 */

import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  Search,
  Sparkles,
  XCircle,
} from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle, StatCard } from '../../../components/ui';
import { DiscoveryEnrichment, DiscoveryRunResult } from '../types';
import { discoveryOutcome, reconciles, summarizeDiscovery } from '../discoveryUtils';

export interface DiscoveryStatsProps {
  result: DiscoveryRunResult;
}

/** Banner styling per outcome. Kept beside the component because it is pure presentation. */
const BANNER_STYLES: Record<
  ReturnType<typeof discoveryOutcome>,
  { className: string; icon: typeof CheckCircle2; title: string }
> = {
  success: {
    className:
      'border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900/50 dark:bg-emerald-950/40 dark:text-emerald-200',
    icon: CheckCircle2,
    title: 'Import complete',
  },
  partial: {
    className:
      'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-200',
    icon: AlertTriangle,
    title: 'Import finished with problems',
  },
  failed: {
    className:
      'border-red-200 bg-red-50 text-red-900 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-200',
    icon: XCircle,
    title: 'No leads could be saved',
  },
  empty: {
    className:
      'border-zinc-200 bg-zinc-50 text-zinc-900 dark:border-zinc-800 dark:bg-zinc-900/50 dark:text-zinc-200',
    icon: Search,
    title: 'Nothing found',
  },
};

/**
 * The enrichment figures, in the order an operator reads them: what the pipeline went and
 * found first, then what contact channels came back.
 *
 * Keyed off `DiscoveryEnrichment` so a field added to the backend response fails to compile
 * here until it is either shown or deliberately left out.
 */
const ENRICHMENT_FIELDS: { key: keyof DiscoveryEnrichment; label: string }[] = [
  { key: 'websites_discovered', label: 'Websites' },
  { key: 'contacts_extracted', label: 'Contacts' },
  { key: 'phones_found', label: 'Phones' },
  { key: 'whatsapp_found', label: 'WhatsApp' },
  { key: 'emails_found', label: 'Emails' },
  { key: 'instagram_found', label: 'Instagram' },
  { key: 'facebook_found', label: 'Facebook' },
  { key: 'youtube_found', label: 'YouTube' },
];

export const DiscoveryStats = ({ result }: DiscoveryStatsProps) => {
  const outcome = discoveryOutcome(result);
  const banner = BANNER_STYLES[outcome];
  const BannerIcon = banner.icon;
  const balanced = reconciles(result);

  return (
    <div className="space-y-4" data-testid="discovery-stats">
      <div
        className={`flex items-start gap-3 rounded-lg border p-4 ${banner.className}`}
        role="status"
        data-testid="discovery-outcome-banner"
      >
        <BannerIcon className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
        <div className="min-w-0">
          <p className="font-semibold">{banner.title}</p>
          <p className="mt-0.5 text-sm opacity-90">{summarizeDiscovery(result)}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard
          title="Found"
          value={result.found}
          icon={<Search className="h-4 w-4" aria-hidden="true" />}
          footer="Records the source returned"
        />
        <StatCard
          title="Imported"
          value={result.imported}
          icon={<CheckCircle2 className="h-4 w-4" aria-hidden="true" />}
          footer="New leads created"
        />
        <StatCard
          title="Enriched"
          value={result.merged}
          icon={<Sparkles className="h-4 w-4" aria-hidden="true" />}
          footer="Existing leads improved"
        />
        <StatCard
          title="Duplicates"
          value={result.duplicates}
          icon={<Copy className="h-4 w-4" aria-hidden="true" />}
          footer="Already held, nothing added"
        />
        <StatCard
          title="Failed"
          value={result.failed}
          icon={<XCircle className="h-4 w-4" aria-hidden="true" />}
          footer="Could not be stored"
        />
      </div>

      {!balanced && (
        <p
          className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-200"
          data-testid="discovery-reconcile-warning"
        >
          These counters do not add up to the {result.found} records found, so the tables
          below may be incomplete. This is a server-side inconsistency worth reporting.
        </p>
      )}

      {result.enrichment && (
        <Card data-testid="discovery-enrichment-stats">
          <CardHeader>
            <CardTitle>Contact Information Collected</CardTitle>
          </CardHeader>
          <CardContent>
            {/*
              Every figure here is reported by the backend, counted over the leads the run
              actually wrote. Nothing on this panel is derived or estimated client-side —
              a number the server does not send is a number this panel does not show.
            */}
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
              {ENRICHMENT_FIELDS.map(({ key, label }) => (
                <div key={key} className="flex items-center justify-between gap-2">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd
                    className="font-medium tabular-nums"
                    data-testid={`discovery-enrichment-${key}`}
                  >
                    {result.enrichment[key]}
                  </dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>
      )}

      {result.stages.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Pipeline Stages</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2" data-testid="discovery-stage-stats">
              {result.stages.map((stage) => (
                <li
                  key={stage.stage}
                  className="flex items-center justify-between gap-3 text-sm"
                >
                  <span className="font-medium capitalize">
                    {stage.stage.replace(/_/g, ' ')}
                  </span>
                  <span className="tabular-nums text-muted-foreground">
                    {stage.records_enriched} of {stage.records_in} enriched
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
};
