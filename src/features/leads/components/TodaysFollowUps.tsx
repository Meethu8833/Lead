/**
 * src/features/leads/components/TodaysFollowUps.tsx
 *
 * Section 3 — the follow-up tasks due today, with Complete and Reschedule actions.
 *
 * This is the only section with write actions. It stays presentational: the mutations
 * are passed in from the page, so this component is testable by handing it plain
 * callbacks, and the busy state is tracked per row so completing one task does not
 * disable the buttons on every other row.
 */

import * as React from 'react';
import { Link } from 'react-router-dom';
import dayjs from 'dayjs';
import { Button } from '../../../components/ui/Button';
import { Badge } from '../../../components/ui/Badge';
import { DashboardSection } from './DashboardSection';
import { LeadStatusBadge } from './LeadStatusBadge';
import { RescheduleDialog } from './RescheduleDialog';
import { TodayFollowUp } from '../types';
import { formatPhone } from '../../../utils/helpers';
import { CalendarClock, Check, Clock, CalendarCheck, User } from 'lucide-react';

export interface TodaysFollowUpsProps {
  followUps: TodayFollowUp[];
  isLoading?: boolean;
  isError?: boolean;
  isEmpty?: boolean;
  onRetry?: () => void;
  onComplete?: (taskId: string) => void;
  onReschedule?: (taskId: string, scheduledAt: string, remarks: string) => void;
  /** Id of the task currently being mutated, so only its row shows a spinner. */
  pendingTaskId?: string | null;
  canUpdate?: boolean;
}

export const TodaysFollowUps = ({
  followUps,
  isLoading = false,
  isError = false,
  isEmpty = false,
  onRetry,
  onComplete,
  onReschedule,
  pendingTaskId = null,
  canUpdate = true,
}: TodaysFollowUpsProps) => {
  const [reschedulingTask, setReschedulingTask] = React.useState<TodayFollowUp | null>(null);

  const handleRescheduleConfirm = (scheduledAt: string, remarks: string) => {
    if (reschedulingTask) {
      onReschedule?.(reschedulingTask.task.id, scheduledAt, remarks);
      setReschedulingTask(null);
    }
  };

  return (
    <>
      <DashboardSection
        title="Today's Follow-ups"
        description="Tasks scheduled for today"
        icon={<CalendarClock className="h-4 w-4" />}
        isLoading={isLoading}
        isError={isError}
        isEmpty={isEmpty}
        emptyIcon={<CalendarCheck className="h-6 w-6" />}
        emptyTitle="Nothing due today"
        emptyDescription="You have no follow-ups scheduled for today. Enjoy the clear runway."
        errorDescription="We could not load today's follow-ups. Please try again."
        onRetry={onRetry}
        skeletonRows={4}
        data-testid="todays-followups"
      >
        <ul className="divide-y divide-border" data-testid="todays-followups-list">
          {followUps.map(({ task, leadName, leadPhone, assigneeName }) => {
            const isPending = pendingTaskId === task.id;

            return (
              <li
                key={task.id}
                className="py-3 first:pt-0 last:pb-0"
                data-testid="followup-item"
              >
                <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-3">
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      {/* The lead name links through; when the lead falls outside the
                          cached sample the task title is shown as plain text instead. */}
                      {leadName ? (
                        <Link
                          to={`/leads/${task.lead_id}`}
                          className="font-medium text-sm text-foreground hover:text-primary hover:underline truncate"
                          data-testid="followup-lead-name"
                        >
                          {leadName}
                        </Link>
                      ) : (
                        <span
                          className="font-medium text-sm text-foreground truncate"
                          data-testid="followup-lead-name"
                        >
                          {task.title}
                        </span>
                      )}

                      <LeadStatusBadge status={task.follow_up_type} />

                      {task.is_overdue && (
                        <Badge variant="danger" size="sm" data-testid="followup-overdue">
                          Overdue
                        </Badge>
                      )}
                    </div>

                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                      <span data-testid="followup-phone">{formatPhone(leadPhone)}</span>

                      <span className="inline-flex items-center gap-1" data-testid="followup-time">
                        <Clock className="h-3 w-3" />
                        {dayjs(task.scheduled_at).isValid()
                          ? dayjs(task.scheduled_at).format('HH:mm')
                          : '-'}
                      </span>

                      <span
                        className="inline-flex items-center gap-1"
                        data-testid="followup-assignee"
                      >
                        <User className="h-3 w-3" />
                        {assigneeName ?? 'Unassigned'}
                      </span>
                    </div>

                    {task.title && leadName && (
                      <p className="text-xs text-foreground/70 break-words">{task.title}</p>
                    )}
                  </div>

                  {canUpdate && (
                    <div className="flex items-center gap-2 shrink-0">
                      <Button
                        variant="success"
                        size="sm"
                        leftIcon={<Check className="h-3.5 w-3.5" />}
                        onClick={() => onComplete?.(task.id)}
                        isLoading={isPending}
                        disabled={isPending}
                        data-testid="followup-complete"
                      >
                        Complete
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setReschedulingTask({ task, leadName, leadPhone, assigneeName })}
                        disabled={isPending}
                        data-testid="followup-reschedule"
                      >
                        Reschedule
                      </Button>
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </DashboardSection>

      <RescheduleDialog
        isOpen={!!reschedulingTask}
        taskTitle={reschedulingTask?.task.title}
        currentScheduledAt={reschedulingTask?.task.scheduled_at}
        isSubmitting={!!reschedulingTask && pendingTaskId === reschedulingTask.task.id}
        onClose={() => setReschedulingTask(null)}
        onConfirm={handleRescheduleConfirm}
      />
    </>
  );
};
