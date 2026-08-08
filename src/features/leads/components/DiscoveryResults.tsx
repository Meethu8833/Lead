/**
 * src/features/leads/components/DiscoveryResults.tsx
 *
 * The per-record results of a finished run, split across four tabs: imported, enriched,
 * duplicates and failed.
 *
 * Presentational, and built on the shared `DataTable` rather than hand-rolled markup so
 * sorting, empty states and row styling match every other table in the product.
 *
 * **Duplicates have a tab but no rows, deliberately.** A duplicate matched an existing lead
 * and contributed nothing, so the backend records only the count — there is no record to
 * list. Dropping the tab would be worse than showing an explained number: an operator
 * asking "why did 40 records become 12 leads" needs to see where the other 28 went, and a
 * missing tab reads as a missing feature rather than an answered question.
 *
 * Rows link through to the real lead. The tables show only what discovery touched; anything
 * more belongs on the lead's own page.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertCircle, Copy, Sparkles, UserPlus } from 'lucide-react';

import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  ColumnDef,
  DataTable,
  EmptyState,
} from '../../../components/ui';
import { cn } from '../../../utils/cn';
import { DiscoveryFailure, DiscoveryRecord, DiscoveryRunResult } from '../types';
import { formatFieldName, recordDisplayName } from '../discoveryUtils';
import {
  contactQualityVariant,
  externalHref,
  instagramHref,
  mailtoHref,
  telHref,
  whatsAppHref,
} from '../utils';

type ResultTab = 'imported' | 'merged' | 'duplicates' | 'failed';

export interface DiscoveryResultsProps {
  result: DiscoveryRunResult;
}

/** Shared leading column: the business name, linking to the lead it became. */
const nameColumn = (): ColumnDef<DiscoveryRecord> => ({
  header: 'Business',
  accessorKey: 'business_name',
  sortable: true,
  cell: (_value, row) => (
    <Link
      to={`/leads/${row.id}`}
      className="font-medium text-primary underline-offset-2 hover:underline"
    >
      {recordDisplayName(row)}
    </Link>
  ),
});

/** The dash every column shows for a field this run did not collect. */
const Blank = () => <span className="text-muted-foreground">—</span>;

/**
 * An external link that opens in a new tab without leaking the opener or the referrer.
 *
 * `noopener` stops the opened page reaching back through `window.opener`; `noreferrer` is
 * added because these URLs come from an external source and there is no reason to hand
 * them our referrer. Both matter here specifically because the hrefs are attacker-supplied
 * in the sense that we did not author them — they came off a scraped page.
 *
 * The label is truncated but the full value stays in `title`, so a long URL keeps the row
 * height honest while remaining readable on hover.
 */
const ExternalLink = ({
  href,
  label,
  testId,
}: {
  href: string;
  label: string;
  testId?: string;
}) => (
  <a
    href={href}
    target="_blank"
    rel="noopener noreferrer"
    title={label}
    data-testid={testId}
    className="block max-w-[14rem] truncate text-primary underline-offset-2 hover:underline"
  >
    {label}
  </a>
);

const contactColumns = (): ColumnDef<DiscoveryRecord>[] => [
  {
    header: 'Phone',
    accessorKey: 'phone',
    cell: (_value, row) => {
      const href = telHref(row.phone);
      return href ? (
        <a
          href={href}
          title={row.phone ?? undefined}
          data-testid="discovery-phone-link"
          className="tabular-nums text-primary underline-offset-2 hover:underline"
        >
          {row.phone}
        </a>
      ) : (
        <Blank />
      );
    },
  },
  {
    header: 'WhatsApp',
    accessorKey: 'whatsapp',
    cell: (_value, row) => {
      // Built only when the backend flagged the number as a WhatsApp number. A plain phone
      // is never linked to wa.me — see `isWhatsAppReady`.
      const href = row.is_whatsapp_ready ? whatsAppHref({ whatsapp: row.whatsapp }) : null;
      return href ? (
        <ExternalLink
          href={href}
          label={row.whatsapp ?? ''}
          testId="discovery-whatsapp-link"
        />
      ) : (
        <Blank />
      );
    },
  },
  {
    header: 'Email',
    accessorKey: 'email',
    cell: (_value, row) =>
      row.email ? (
        <a
          href={mailtoHref(row.email) ?? undefined}
          title={row.email}
          className="block max-w-[14rem] truncate text-primary underline-offset-2 hover:underline"
        >
          {row.email}
        </a>
      ) : (
        <Blank />
      ),
  },
  {
    header: 'Website',
    accessorKey: 'website',
    cell: (_value, row) => {
      const href = externalHref(row.website);
      return href ? (
        <ExternalLink
          href={href}
          label={row.website!.replace(/^https?:\/\//, '')}
          testId="discovery-website-link"
        />
      ) : (
        <Blank />
      );
    },
  },
  {
    header: 'Instagram',
    accessorKey: 'instagram',
    cell: (_value, row) => {
      const href = instagramHref(row.instagram);
      return href ? (
        <ExternalLink
          href={href}
          label={row.instagram!}
          testId="discovery-instagram-link"
        />
      ) : (
        <Blank />
      );
    },
  },
  {
    header: 'Facebook',
    accessorKey: 'facebook',
    cell: (_value, row) => {
      const href = externalHref(row.facebook);
      return href ? (
        <ExternalLink
          href={href}
          label={row.facebook!.replace(/^https?:\/\//, '')}
          testId="discovery-facebook-link"
        />
      ) : (
        <Blank />
      );
    },
  },
  {
    header: 'Quality',
    accessorKey: 'contact_quality',
    sortable: true,
    cell: (_value, row) => (
      <Badge variant={contactQualityVariant(row.contact_quality)}>
        {row.contact_quality}
      </Badge>
    ),
  },
];

const IMPORTED_COLUMNS: ColumnDef<DiscoveryRecord>[] = [
  nameColumn(),
  ...contactColumns(),
  {
    header: 'City',
    accessorKey: 'city',
    cell: (value) => String(value ?? '—'),
  },
  {
    header: 'Source',
    accessorKey: 'source',
    cell: (value) =>
      value ? <Badge variant="secondary">{String(value)}</Badge> : <Blank />,
  },
];

const MERGED_COLUMNS: ColumnDef<DiscoveryRecord>[] = [
  nameColumn(),
  ...contactColumns(),
  {
    header: 'Fields added',
    accessorKey: 'enriched_fields',
    cell: (_value, row) =>
      row.enriched_fields.length === 0 ? (
        <span className="text-muted-foreground">—</span>
      ) : (
        <span className="flex flex-wrap gap-1">
          {row.enriched_fields.map((field) => (
            <Badge key={field} variant="secondary">
              {formatFieldName(field)}
            </Badge>
          ))}
        </span>
      ),
  },
];

const FAILED_COLUMNS: ColumnDef<DiscoveryFailure>[] = [
  {
    header: 'Business',
    accessorKey: 'business_name',
    sortable: true,
    cell: (value) => (
      <span className="font-medium">{String(value ?? 'Unnamed record')}</span>
    ),
  },
  {
    header: 'Reason',
    accessorKey: 'reason',
    cell: (value) => <span className="text-muted-foreground">{String(value)}</span>,
  },
];

export const DiscoveryResults = ({ result }: DiscoveryResultsProps) => {
  const [tab, setTab] = useState<ResultTab>('imported');

  const tabs: {
    key: ResultTab;
    label: string;
    count: number;
    icon: typeof UserPlus;
  }[] = [
    { key: 'imported', label: 'Imported', count: result.imported, icon: UserPlus },
    { key: 'merged', label: 'Enriched', count: result.merged, icon: Sparkles },
    { key: 'duplicates', label: 'Duplicates', count: result.duplicates, icon: Copy },
    { key: 'failed', label: 'Failed', count: result.failed, icon: AlertCircle },
  ];

  return (
    <Card data-testid="discovery-results">
      <CardHeader>
        <CardTitle>Results</CardTitle>
        <CardDescription>
          Every record this run touched, grouped by what happened to it.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div
          className="flex flex-wrap gap-2 border-b pb-3 dark:border-zinc-800"
          role="tablist"
          aria-label="Discovery results"
        >
          {tabs.map(({ key, label, count, icon: Icon }) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              data-testid={`discovery-tab-${key}`}
              className={cn(
                'flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
                tab === key
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              )}
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
              {label}
              <span className="tabular-nums opacity-80">({count})</span>
            </button>
          ))}
        </div>

        <div role="tabpanel">
          {tab === 'imported' && (
            <DataTable
              columns={IMPORTED_COLUMNS}
              data={result.imported_records}
              getRowId={(row) => row.id}
              emptyComponent={
                <EmptyState
                  icon={<UserPlus className="h-6 w-6" aria-hidden="true" />}
                  title="No new leads"
                  description="Every record this run found was already in the CRM."
                />
              }
            />
          )}

          {tab === 'merged' && (
            <DataTable
              columns={MERGED_COLUMNS}
              data={result.merged_records}
              getRowId={(row) => row.id}
              emptyComponent={
                <EmptyState
                  icon={<Sparkles className="h-6 w-6" aria-hidden="true" />}
                  title="No leads enriched"
                  description="No existing lead had an empty field this run could fill in."
                />
              }
            />
          )}

          {/*
            The count without rows — see the note at the top of this file on why the tab
            exists anyway.
          */}
          {tab === 'duplicates' && (
            <EmptyState
              icon={<Copy className="h-6 w-6" aria-hidden="true" />}
              title={`${result.duplicates} duplicate${
                result.duplicates === 1 ? '' : 's'
              } skipped`}
              description={
                result.duplicates === 0
                  ? 'No record matched a lead already in the CRM.'
                  : 'These records matched leads already in the CRM and added nothing new, so they were skipped rather than stored a second time. Individual records are not listed — the run records only how many there were.'
              }
            />
          )}

          {tab === 'failed' && (
            <DataTable
              columns={FAILED_COLUMNS}
              data={result.failed_records}
              getRowId={(row) => `${row.business_name ?? 'record'}-${row.reason}`}
              emptyComponent={
                <EmptyState
                  icon={<AlertCircle className="h-6 w-6" aria-hidden="true" />}
                  title="Nothing failed"
                  description="Every record this run found could be stored."
                />
              }
            />
          )}
        </div>
      </CardContent>
    </Card>
  );
};
