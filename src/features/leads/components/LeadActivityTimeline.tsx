/**
 * src/features/leads/components/LeadActivityTimeline.tsx
 *
 * The lead's append-only activity timeline, newest first, with Load More.
 *
 * The spec names ten events; the backend's `ActivityType` enum has seventeen members and
 * uses different names for several of them (a lead import arrives as CREATED, "Note
 * Added" as NOTE, "Follow-up Created/Completed" as TASK_CREATED/TASK_COMPLETED). The
 * mapping below is the single place that translation happens, and it covers every enum
 * member rather than only the ten — an unmapped type would otherwise render as an
 * unlabelled grey dot.
 */

import * as React from 'react';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import {
  Ban,
  CalendarClock,
  CalendarPlus,
  CheckCircle2,
  Check,
  CheckCheck,
  Eye,
  History,
  MessageCircle,
  MessageSquareReply,
  Pencil,
  Phone,
  Send,
  Sparkles,
  StickyNote,
  Trash2,
  UserPlus,
} from 'lucide-react';
import { Timeline, TimelineItem } from '../../../components/ui/Timeline';
import { Button } from '../../../components/ui/Button';
import { DashboardSection } from './DashboardSection';
import { ActivityType, LeadActivity } from '../types';

dayjs.extend(relativeTime);

type TimelineColor = NonNullable<TimelineItem['color']>;

/**
 * Icon, colour and display label per activity type.
 *
 * Colour semantics match the rest of the CRM: green for progress (delivered, read,
 * completed, converted), blue for outbound engagement, amber for things needing
 * attention, red for dead ends, grey for bookkeeping.
 */
const ACTIVITY_PRESENTATION: Record<
  ActivityType,
  { icon: React.ReactNode; color: TimelineColor; label: string }
> = {
  // The spec's "Lead Imported" — an imported lead is created, which is what the
  // backend records. The title on the row itself distinguishes an import from a
  // manual entry.
  CREATED: { icon: <UserPlus className="h-3 w-3" />, color: 'primary', label: 'Lead Imported' },
  UPDATED: { icon: <Pencil className="h-3 w-3" />, color: 'muted', label: 'Lead Updated' },
  WHATSAPP_SENT: { icon: <Send className="h-3 w-3" />, color: 'primary', label: 'WhatsApp Sent' },
  WHATSAPP_DELIVERED: {
    icon: <Check className="h-3 w-3" />,
    color: 'primary',
    label: 'WhatsApp Delivered',
  },
  WHATSAPP_READ: {
    icon: <CheckCheck className="h-3 w-3" />,
    color: 'success',
    label: 'WhatsApp Read',
  },
  WHATSAPP_REPLIED: {
    icon: <MessageSquareReply className="h-3 w-3" />,
    color: 'success',
    label: 'WhatsApp Replied',
  },
  PHONE_CALL: { icon: <Phone className="h-3 w-3" />, color: 'primary', label: 'Phone Call' },
  FOLLOW_UP: { icon: <MessageCircle className="h-3 w-3" />, color: 'warning', label: 'Follow-up' },
  TASK_CREATED: {
    icon: <CalendarPlus className="h-3 w-3" />,
    color: 'warning',
    label: 'Follow-up Created',
  },
  TASK_COMPLETED: {
    icon: <CheckCircle2 className="h-3 w-3" />,
    color: 'success',
    label: 'Follow-up Completed',
  },
  TASK_RESCHEDULED: {
    icon: <CalendarClock className="h-3 w-3" />,
    color: 'warning',
    label: 'Follow-up Rescheduled',
  },
  TASK_CANCELLED: { icon: <Ban className="h-3 w-3" />, color: 'danger', label: 'Follow-up Cancelled' },
  MEETING_SCHEDULED: {
    icon: <CalendarPlus className="h-3 w-3" />,
    color: 'primary',
    label: 'Meeting Scheduled',
  },
  NOTE: { icon: <StickyNote className="h-3 w-3" />, color: 'muted', label: 'Note Added' },
  STATUS_CHANGED: { icon: <History className="h-3 w-3" />, color: 'warning', label: 'Status Changed' },
  CONVERTED: { icon: <Sparkles className="h-3 w-3" />, color: 'success', label: 'Converted' },
  DELETED: { icon: <Trash2 className="h-3 w-3" />, color: 'danger', label: 'Deleted' },
};

/** Fallback for an activity type added to the backend but not yet mapped here. */
const FALLBACK_PRESENTATION = {
  icon: <Eye className="h-3 w-3" />,
  color: 'muted' as TimelineColor,
  label: 'Activity',
};

export const presentationFor = (type: ActivityType) =>
  ACTIVITY_PRESENTATION[type] ?? FALLBACK_PRESENTATION;

export interface LeadActivityTimelineProps {
  activities: LeadActivity[];
  total: number;
  isLoading: boolean;
  isError: boolean;
  isEmpty: boolean;
  hasMore: boolean;
  onLoadMore: () => void;
  onRetry?: () => void;
}

export const LeadActivityTimeline = ({
  activities,
  total,
  isLoading,
  isError,
  isEmpty,
  hasMore,
  onLoadMore,
  onRetry,
}: LeadActivityTimelineProps) => {
  const items = React.useMemo<TimelineItem[]>(
    () =>
      activities.map((activity) => {
        const { icon, color, label } = presentationFor(activity.activity_type);

        return {
          id: activity.id,
          icon,
          color,
          // Every entry is a thing that already happened, so all dots render as
          // 'completed'. The colour, not the status, carries the meaning here.
          status: 'completed' as const,
          title: (
            <span className="flex flex-wrap items-center gap-x-2">
              <span>{activity.title}</span>
              <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                {label}
              </span>
            </span>
          ),
          description: activity.description,
          timestamp: (
            <span title={dayjs(activity.created_at).format('DD MMM YYYY, h:mm A')}>
              {dayjs(activity.created_at).fromNow()}
            </span>
          ),
        };
      }),
    [activities]
  );

  return (
    <DashboardSection
      title="Activity Timeline"
      description={total > 0 ? `${total} ${total === 1 ? 'entry' : 'entries'}` : undefined}
      icon={<History className="h-4 w-4" />}
      isLoading={isLoading && activities.length === 0}
      isError={isError}
      isEmpty={isEmpty}
      emptyTitle="No activity yet"
      emptyDescription="Everything that happens to this lead will appear here."
      emptyIcon={<History className="h-6 w-6" />}
      errorDescription="We could not load this lead's timeline. Please try again."
      onRetry={onRetry}
      skeletonRows={4}
      data-testid="lead-activity-timeline"
    >
      <div className="space-y-4">
        <Timeline items={items} />

        {hasMore && (
          <div className="flex justify-center pt-2">
            <Button
              variant="outline"
              size="sm"
              onClick={onLoadMore}
              isLoading={isLoading}
              data-testid="timeline-load-more"
            >
              Load More
            </Button>
          </div>
        )}
      </div>
    </DashboardSection>
  );
};
