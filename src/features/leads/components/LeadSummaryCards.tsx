/**
 * src/features/leads/components/LeadSummaryCards.tsx
 *
 * Section 1 — the eight headline lead counters.
 *
 * Rendering delegates to the shared `StatCard`, which already owns the loading skeleton,
 * so this component only decides which counters exist, what they are called, and how the
 * error and empty cases are presented.
 */

import * as React from 'react';
import { Link } from 'react-router-dom';
import { StatCard } from '../../../components/ui/StatCard';
import { ErrorState } from '../../../components/ui/ErrorState';
import { EmptyState } from '../../../components/ui/EmptyState';
import { LeadSummaryCounts } from '../types';
import {
  Users,
  Sparkles,
  Send,
  MessageSquare,
  ThumbsUp,
  Handshake,
  CalendarClock,
  XCircle,
} from 'lucide-react';

export interface LeadSummaryCardsProps {
  counts: LeadSummaryCounts;
  isLoading?: boolean;
  isError?: boolean;
  isEmpty?: boolean;
  onRetry?: () => void;
}

interface CardSpec {
  key: keyof LeadSummaryCounts;
  title: string;
  icon: React.ReactNode;
  /** Where the card drills through to, as a pre-filtered lead list. */
  to: string;
  footer?: string;
}

const CARD_SPECS: CardSpec[] = [
  { key: 'total', title: 'Total Leads', icon: <Users className="h-5 w-5" />, to: '/leads' },
  {
    key: 'new',
    title: 'New Leads',
    icon: <Sparkles className="h-5 w-5" />,
    to: '/leads?status=NEW',
  },
  {
    key: 'messageSent',
    title: 'Message Sent',
    icon: <Send className="h-5 w-5" />,
    to: '/leads?status=MESSAGE_SENT',
  },
  {
    key: 'replied',
    title: 'Replied',
    icon: <MessageSquare className="h-5 w-5" />,
    to: '/leads?status=REPLIED',
  },
  {
    key: 'interested',
    title: 'Interested',
    icon: <ThumbsUp className="h-5 w-5" />,
    to: '/leads?status=INTERESTED',
  },
  {
    key: 'negotiation',
    title: 'Negotiation',
    icon: <Handshake className="h-5 w-5" />,
    to: '/leads?status=NEGOTIATION',
  },
  {
    key: 'followUpToday',
    title: 'Follow-up Today',
    icon: <CalendarClock className="h-5 w-5" />,
    to: '/followups',
    // Named explicitly because this counts tasks due today, not leads in FOLLOW_UP status.
    footer: 'Tasks due today',
  },
  { key: 'lost', title: 'Lost', icon: <XCircle className="h-5 w-5" />, to: '/leads?status=LOST' },
];

export const LeadSummaryCards = ({
  counts,
  isLoading = false,
  isError = false,
  isEmpty = false,
  onRetry,
}: LeadSummaryCardsProps) => {
  // An error is shown instead of the grid, never alongside it: eight cards all reading
  // "0" would otherwise look like a CRM with no leads rather than a failed request.
  if (isError) {
    return (
      <ErrorState
        title="Could not load lead summary"
        description="The lead counters could not be retrieved. Check your connection and try again."
        onRetry={onRetry}
        className="max-w-full"
        data-testid="lead-summary-error"
      />
    );
  }

  if (isEmpty) {
    return (
      <EmptyState
        icon={<Users className="h-6 w-6" />}
        title="No leads yet"
        description="Import your first batch of photographer leads to start tracking your pipeline."
        action={
          <Link
            to="/leads/import"
            className="text-sm font-medium text-primary hover:underline"
            data-testid="lead-summary-empty-action"
          >
            Import leads
          </Link>
        }
        className="max-w-full"
        data-testid="lead-summary-empty"
      />
    );
  }

  return (
    <div
      className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"
      data-testid="lead-summary-cards"
    >
      {CARD_SPECS.map((spec) => (
        <Link
          key={spec.key}
          to={spec.to}
          className="rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          data-testid={`lead-summary-link-${spec.key}`}
        >
          <StatCard
            title={spec.title}
            value={counts[spec.key].toLocaleString()}
            icon={spec.icon}
            footer={spec.footer}
            loading={isLoading}
            className="h-full"
          />
        </Link>
      ))}
    </div>
  );
};
