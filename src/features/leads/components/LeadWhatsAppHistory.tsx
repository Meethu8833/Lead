/**
 * src/features/leads/components/LeadWhatsAppHistory.tsx
 *
 * Every WhatsApp campaign this lead was messaged in, and how far each message got.
 *
 * The four delivery milestones (sent → delivered → read → replied) each carry their own
 * timestamp on the recipient row, so they render as a compact tick strip rather than a
 * single status word: knowing a message was delivered but never read is the point of
 * this section.
 *
 * `isSampled` is surfaced explicitly because the history is assembled client-side over
 * only the most recent campaigns — see `useLeadWhatsAppHistory`. Silently showing a
 * partial history would read as "this lead was never messaged before that".
 */

import * as React from 'react';
import dayjs from 'dayjs';
import { Check, CheckCheck, Eye, MessageCircle, MessageSquareReply, Send, XCircle } from 'lucide-react';
import { Badge } from '../../../components/ui/Badge';
import { cn } from '../../../utils/cn';
import { DashboardSection } from './DashboardSection';
import { LeadStatusBadge } from './LeadStatusBadge';
import { LeadWhatsAppHistoryEntry } from '../types';

/** One delivery milestone: reached or not, and when. */
interface MilestoneProps {
  icon: React.ReactNode;
  label: string;
  at: string | null;
}

const Milestone = ({ icon, label, at }: MilestoneProps) => (
  <span
    className={cn(
      'inline-flex items-center gap-1 text-xs',
      at ? 'text-emerald-600 dark:text-emerald-500' : 'text-muted-foreground/50'
    )}
    title={at ? `${label}: ${dayjs(at).format('DD MMM YYYY, h:mm A')}` : `Not ${label.toLowerCase()}`}
    data-testid={`milestone-${label.toLowerCase()}`}
    data-reached={at ? 'true' : 'false'}
  >
    {icon}
    {label}
  </span>
);

export interface LeadWhatsAppHistoryProps {
  history: LeadWhatsAppHistoryEntry[];
  isLoading: boolean;
  isError: boolean;
  isEmpty: boolean;
  isSampled?: boolean;
  onRetry?: () => void;
}

export const LeadWhatsAppHistory = ({
  history,
  isLoading,
  isError,
  isEmpty,
  isSampled = false,
  onRetry,
}: LeadWhatsAppHistoryProps) => (
  <DashboardSection
    title="WhatsApp History"
    description={
      isSampled ? 'Covers this lead’s most recent campaigns only.' : undefined
    }
    icon={<MessageCircle className="h-4 w-4" />}
    isLoading={isLoading}
    isError={isError}
    isEmpty={isEmpty}
    emptyTitle="No messages yet"
    emptyDescription="This lead has not been included in a recent WhatsApp campaign."
    emptyIcon={<MessageCircle className="h-6 w-6" />}
    errorDescription="We could not load this lead's WhatsApp history. Please try again."
    onRetry={onRetry}
    skeletonRows={3}
    data-testid="lead-whatsapp-history"
  >
    <ul className="space-y-3" data-testid="whatsapp-history-list">
      {history.map((entry) => (
        <li
          key={entry.recipientId}
          className="rounded-lg border border-border bg-muted/30 dark:bg-muted/10 p-3 space-y-2"
          data-testid={`whatsapp-entry-${entry.recipientId}`}
        >
          <div className="flex flex-wrap items-start justify-between gap-2">
            <p
              className="text-sm font-medium text-foreground break-words min-w-0"
              data-testid="whatsapp-campaign-name"
            >
              {entry.campaignName}
            </p>
            <LeadStatusBadge status={entry.messageStatus} />
          </div>

          {/* Message time — the dispatch timestamp, which is what "when was this sent"
              means to a caller looking at the row. */}
          <p className="text-xs text-muted-foreground" data-testid="whatsapp-message-time">
            {entry.sentAt
              ? dayjs(entry.sentAt).format('DD MMM YYYY, h:mm A')
              : 'Not yet sent'}
          </p>

          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Milestone icon={<Send className="h-3 w-3" />} label="Sent" at={entry.sentAt} />
            <Milestone
              icon={<Check className="h-3 w-3" />}
              label="Delivered"
              at={entry.deliveredAt}
            />
            <Milestone icon={<CheckCheck className="h-3 w-3" />} label="Read" at={entry.readAt} />
            <Milestone
              icon={<MessageSquareReply className="h-3 w-3" />}
              label="Replied"
              at={entry.repliedAt}
            />
          </div>

          {entry.replyText && (
            <blockquote
              className="border-l-2 border-emerald-500 pl-3 py-1 text-xs text-foreground/90 italic break-words"
              data-testid="whatsapp-reply-preview"
            >
              <span className="inline-flex items-center gap-1 not-italic text-emerald-600 dark:text-emerald-500 font-medium mr-1">
                <Eye className="h-3 w-3" />
                Reply:
              </span>
              {entry.replyText}
              {entry.repliedAt && (
                <span className="block not-italic text-muted-foreground mt-0.5">
                  {dayjs(entry.repliedAt).format('DD MMM YYYY, h:mm A')}
                </span>
              )}
            </blockquote>
          )}

          {entry.errorMessage && (
            <p
              className="inline-flex items-start gap-1.5 text-xs text-destructive break-words"
              data-testid="whatsapp-error"
            >
              <XCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              {entry.errorMessage}
            </p>
          )}
        </li>
      ))}
    </ul>

    {isSampled && (
      <p className="text-xs text-muted-foreground pt-3" data-testid="whatsapp-sampled-note">
        Older campaigns are not shown.{' '}
        <Badge variant="secondary" size="sm">
          Recent campaigns only
        </Badge>
      </p>
    )}
  </DashboardSection>
);
