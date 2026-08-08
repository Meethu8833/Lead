/**
 * src/features/leads/components/RecentReplies.tsx
 *
 * Section 2 — the latest WhatsApp replies across recent campaigns.
 *
 * The rows arrive pre-assembled and pre-sorted from `useRecentReplies`; this component
 * only lays them out. Times are shown as a relative age ("2h ago") with the absolute
 * timestamp on hover, because the useful question here is "how stale is this reply",
 * not what o'clock it arrived.
 */

import { Link } from 'react-router-dom';
import dayjs from 'dayjs';
import { Button } from '../../../components/ui/Button';
import { DashboardSection } from './DashboardSection';
import { LeadStatusBadge } from './LeadStatusBadge';
import { RecentReply } from '../types';
import { formatDateTime, formatPhone, truncate } from '../../../utils/helpers';
import { MessageSquare, ArrowRight, Inbox } from 'lucide-react';

export interface RecentRepliesProps {
  replies: RecentReply[];
  isLoading?: boolean;
  isError?: boolean;
  isEmpty?: boolean;
  onRetry?: () => void;
}

/** "5m ago" / "3h ago" / "2d ago", falling back to a date once past a week. */
const formatRelativeTime = (timestamp: string | null): string => {
  if (!timestamp) return 'Unknown time';

  const then = dayjs(timestamp);
  if (!then.isValid()) return 'Unknown time';

  const now = dayjs();
  const minutes = now.diff(then, 'minute');

  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;

  const hours = now.diff(then, 'hour');
  if (hours < 24) return `${hours}h ago`;

  const days = now.diff(then, 'day');
  if (days < 7) return `${days}d ago`;

  return then.format('DD MMM YYYY');
};

export const RecentReplies = ({
  replies,
  isLoading = false,
  isError = false,
  isEmpty = false,
  onRetry,
}: RecentRepliesProps) => {
  return (
    <DashboardSection
      title="Recent Replies"
      description="Latest responses received on WhatsApp"
      icon={<MessageSquare className="h-4 w-4" />}
      isLoading={isLoading}
      isError={isError}
      isEmpty={isEmpty}
      emptyIcon={<Inbox className="h-6 w-6" />}
      emptyTitle="No replies yet"
      emptyDescription="Replies from your WhatsApp campaigns will appear here as leads respond."
      errorDescription="We could not load recent replies. Please try again."
      onRetry={onRetry}
      skeletonRows={4}
      data-testid="recent-replies"
    >
      <ul className="divide-y divide-border" data-testid="recent-replies-list">
        {replies.map((reply) => (
          <li
            key={reply.recipientId}
            className="py-3 first:pt-0 last:pb-0"
            data-testid="recent-reply-item"
          >
            <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
              <div className="min-w-0 flex-1 space-y-1.5">
                {/* Name, status and time share a wrapping row so the layout survives
                    long studio names on narrow screens. */}
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span
                    className="font-medium text-sm text-foreground truncate"
                    data-testid="recent-reply-name"
                  >
                    {reply.leadName}
                  </span>
                  <LeadStatusBadge status={reply.leadStatus} />
                  <span
                    className="text-xs text-muted-foreground"
                    title={formatDateTime(reply.repliedAt)}
                    data-testid="recent-reply-time"
                  >
                    {formatRelativeTime(reply.repliedAt)}
                  </span>
                </div>

                <div className="text-xs text-muted-foreground" data-testid="recent-reply-phone">
                  {formatPhone(reply.phone)}
                </div>

                <p
                  className="text-sm text-foreground/80 break-words"
                  data-testid="recent-reply-preview"
                >
                  {reply.replyText ? truncate(reply.replyText, 140) : 'No message content'}
                </p>
              </div>

              <Link to={`/leads/${reply.leadId}`} className="shrink-0">
                <Button
                  variant="outline"
                  size="sm"
                  rightIcon={<ArrowRight className="h-3.5 w-3.5" />}
                  data-testid="recent-reply-open"
                >
                  Open Lead
                </Button>
              </Link>
            </div>
          </li>
        ))}
      </ul>
    </DashboardSection>
  );
};
