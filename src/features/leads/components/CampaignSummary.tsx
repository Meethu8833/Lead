/**
 * src/features/leads/components/CampaignSummary.tsx
 *
 * Section 5 — per-campaign delivery funnel and the interested leads it produced.
 *
 * Sent / Delivered / Read / Replies come straight off the campaign's own counters.
 * "Interested Leads" is derived in `useCampaignSummary` by intersecting the campaign's
 * recipients with leads currently in INTERESTED status — a present-tense figure, which
 * the column header footnote makes explicit.
 */

import { Link } from 'react-router-dom';
import { DashboardSection } from './DashboardSection';
import { LeadStatusBadge } from './LeadStatusBadge';
import { WhatsAppCampaign } from '../types';
import { MessageCircle, Megaphone } from 'lucide-react';

export interface CampaignSummaryRow {
  campaign: WhatsAppCampaign;
  interestedLeads: number;
}

export interface CampaignSummaryProps {
  rows: CampaignSummaryRow[];
  isLoading?: boolean;
  isError?: boolean;
  isEmpty?: boolean;
  onRetry?: () => void;
}

export const CampaignSummary = ({
  rows,
  isLoading = false,
  isError = false,
  isEmpty = false,
  onRetry,
}: CampaignSummaryProps) => {
  return (
    <DashboardSection
      title="WhatsApp Campaign Summary"
      description="Delivery funnel for your most recent campaigns"
      icon={<MessageCircle className="h-4 w-4" />}
      isLoading={isLoading}
      isError={isError}
      isEmpty={isEmpty}
      emptyIcon={<Megaphone className="h-6 w-6" />}
      emptyTitle="No campaigns yet"
      emptyDescription="Create a WhatsApp campaign to start reaching out to your leads."
      errorDescription="We could not load campaign statistics. Please try again."
      onRetry={onRetry}
      skeletonRows={3}
      data-testid="campaign-summary"
    >
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-sm" data-testid="campaign-summary-table">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="pb-2 pr-4 font-medium">Campaign</th>
              <th className="pb-2 pr-4 font-medium text-right">Sent</th>
              <th className="pb-2 pr-4 font-medium text-right">Delivered</th>
              <th className="pb-2 pr-4 font-medium text-right">Read</th>
              <th className="pb-2 pr-4 font-medium text-right">Replies</th>
              <th
                className="pb-2 font-medium text-right"
                title="Recipients of this campaign whose lead status is currently Interested"
              >
                Interested
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map(({ campaign, interestedLeads }) => (
              <tr key={campaign.id} data-testid="campaign-summary-row">
                <td className="py-2.5 pr-4">
                  <div className="flex items-center gap-2 min-w-0">
                    <Link
                      to={`/campaigns/${campaign.id}`}
                      className="font-medium text-foreground hover:text-primary hover:underline truncate"
                      data-testid="campaign-summary-name"
                    >
                      {campaign.name}
                    </Link>
                    <LeadStatusBadge status={campaign.status} />
                  </div>
                </td>
                <td className="py-2.5 pr-4 text-right tabular-nums">{campaign.total_sent}</td>
                <td className="py-2.5 pr-4 text-right tabular-nums">{campaign.total_delivered}</td>
                <td className="py-2.5 pr-4 text-right tabular-nums">{campaign.total_read}</td>
                <td className="py-2.5 pr-4 text-right tabular-nums text-sky-600 dark:text-sky-400">
                  {campaign.total_replied}
                </td>
                <td
                  className="py-2.5 text-right tabular-nums text-emerald-600 dark:text-emerald-400"
                  data-testid="campaign-summary-interested"
                >
                  {interestedLeads}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile: the same funnel as a stacked card per campaign. */}
      <ul className="md:hidden space-y-3" data-testid="campaign-summary-mobile">
        {rows.map(({ campaign, interestedLeads }) => (
          <li
            key={campaign.id}
            className="rounded-lg border border-border p-3 space-y-2"
            data-testid="campaign-summary-card"
          >
            <div className="flex items-center justify-between gap-2">
              <Link
                to={`/campaigns/${campaign.id}`}
                className="font-medium text-sm truncate hover:text-primary hover:underline"
              >
                {campaign.name}
              </Link>
              <LeadStatusBadge status={campaign.status} />
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>
                Sent: <span className="text-foreground tabular-nums">{campaign.total_sent}</span>
              </span>
              <span>
                Delivered:{' '}
                <span className="text-foreground tabular-nums">{campaign.total_delivered}</span>
              </span>
              <span>
                Read: <span className="text-foreground tabular-nums">{campaign.total_read}</span>
              </span>
              <span>
                Replies:{' '}
                <span className="text-sky-600 dark:text-sky-400 tabular-nums">
                  {campaign.total_replied}
                </span>
              </span>
              <span>
                Interested:{' '}
                <span className="text-emerald-600 dark:text-emerald-400 tabular-nums">
                  {interestedLeads}
                </span>
              </span>
            </div>
          </li>
        ))}
      </ul>
    </DashboardSection>
  );
};
