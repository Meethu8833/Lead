/**
 * src/features/leads/components/LeadFollowUpsSection.tsx
 *
 * Every follow-up scheduled against this lead — open, completed and cancelled — with the
 * four lifecycle actions.
 *
 * Overdue rows are highlighted from the server-computed `is_overdue` flag rather than by
 * comparing `scheduled_at` to the clock here. This matters: the backend ships no
 * background sweeper, so a task's stored `status` can still read PENDING after its due
 * time has passed, and `is_overdue` is the only field that tells the truth.
 *
 * Cancel and Complete are distinct on purpose, mirroring the backend's own distinction:
 * cancelling records a deliberate decision not to do the work and writes a
 * TASK_CANCELLED entry to the timeline, whereas deleting (not offered here) means the
 * task should never have existed.
 */

import * as React from 'react';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import {
  AlertTriangle,
  Ban,
  CalendarClock,
  CheckCircle2,
  ListChecks,
  Plus,
  User,
} from 'lucide-react';
import { Badge } from '../../../components/ui/Badge';
import { Button } from '../../../components/ui/Button';
import { ConfirmationDialog } from '../../../components/ui/ConfirmationDialog';
import PermissionGuard from '../../../components/auth/PermissionGuard';
import { cn } from '../../../utils/cn';
import { DashboardSection } from './DashboardSection';
import { LeadStatusBadge } from './LeadStatusBadge';
import { FollowUpTask } from '../types';

dayjs.extend(relativeTime);

/** Colour weight per priority, so URGENT reads differently from LOW at a glance. */
const PRIORITY_VARIANTS: Record<string, 'danger' | 'warning' | 'info' | 'secondary'> = {
  URGENT: 'danger',
  HIGH: 'warning',
  MEDIUM: 'info',
  LOW: 'secondary',
};

/** True when a task is still actionable — the only state the actions apply to. */
export const isOpenTask = (task: FollowUpTask) =>
  task.status === 'PENDING' || task.status === 'OVERDUE';

export interface LeadFollowUpsSectionProps {
  followUps: FollowUpTask[];
  total: number;
  overdueCount: number;
  /** Employee id → display name, for showing who owns each task. */
  assigneeNames: Record<string, string>;
  isLoading: boolean;
  isError: boolean;
  isEmpty: boolean;
  onCreate: () => void;
  onComplete: (taskId: string) => Promise<unknown>;
  onCancel: (taskId: string) => Promise<unknown>;
  onReschedule: (task: FollowUpTask) => void;
  isMutating?: boolean;
  onRetry?: () => void;
}

export const LeadFollowUpsSection = ({
  followUps,
  total,
  overdueCount,
  assigneeNames,
  isLoading,
  isError,
  isEmpty,
  onCreate,
  onComplete,
  onCancel,
  onReschedule,
  isMutating = false,
  onRetry,
}: LeadFollowUpsSectionProps) => {
  const [confirming, setConfirming] = React.useState<
    { task: FollowUpTask; action: 'complete' | 'cancel' } | null
  >(null);

  const handleConfirm = async () => {
    if (!confirming) return;
    const { task, action } = confirming;
    if (action === 'complete') {
      await onComplete(task.id);
    } else {
      await onCancel(task.id);
    }
    setConfirming(null);
  };

  return (
    <>
      <DashboardSection
        title="Follow-ups"
        description={
          total > 0
            ? `${total} ${total === 1 ? 'task' : 'tasks'}${
                overdueCount > 0 ? ` · ${overdueCount} overdue` : ''
              }`
            : undefined
        }
        icon={<ListChecks className="h-4 w-4" />}
        actions={
          <PermissionGuard requiredPermission="followups:create">
            <Button variant="outline" size="sm" onClick={onCreate} data-testid="followups-create">
              <Plus className="h-3.5 w-3.5 mr-1.5" />
              New
            </Button>
          </PermissionGuard>
        }
        isLoading={isLoading}
        isError={isError}
        isEmpty={isEmpty}
        emptyTitle="No follow-ups yet"
        emptyDescription="Schedule the next touchpoint so this lead does not go cold."
        emptyIcon={<CalendarClock className="h-6 w-6" />}
        errorDescription="We could not load this lead's follow-ups. Please try again."
        onRetry={onRetry}
        skeletonRows={3}
        data-testid="lead-followups-section"
      >
        <ul className="space-y-3" data-testid="lead-followups-list">
          {followUps.map((task) => {
            const open = isOpenTask(task);
            const overdue = task.is_overdue && open;
            const assignee = task.assigned_employee_id
              ? assigneeNames[task.assigned_employee_id]
              : null;

            return (
              <li
                key={task.id}
                className={cn(
                  'rounded-lg border p-3 space-y-2 transition-colors',
                  overdue
                    ? 'border-destructive/40 bg-destructive/5 dark:bg-destructive/10'
                    : 'border-border bg-muted/30 dark:bg-muted/10',
                  // A closed task is history, not work — de-emphasised so the open ones
                  // above it stay visually dominant.
                  !open && 'opacity-70'
                )}
                data-testid={`followup-${task.id}`}
                data-overdue={overdue ? 'true' : 'false'}
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0 space-y-1">
                    <p className="text-sm font-medium text-foreground break-words">
                      {task.title}
                    </p>
                    {task.description && (
                      <p className="text-xs text-muted-foreground whitespace-pre-wrap break-words">
                        {task.description}
                      </p>
                    )}
                  </div>

                  <div className="flex flex-wrap items-center gap-1.5 shrink-0">
                    {overdue && (
                      <Badge variant="danger" size="sm" data-testid={`followup-overdue-${task.id}`}>
                        <AlertTriangle className="h-3 w-3 mr-1" />
                        Overdue
                      </Badge>
                    )}
                    <Badge variant={PRIORITY_VARIANTS[task.priority] ?? 'secondary'} size="sm">
                      {task.priority}
                    </Badge>
                    <LeadStatusBadge status={task.status} />
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1">
                    <CalendarClock className="h-3 w-3" />
                    <span title={dayjs(task.scheduled_at).format('DD MMM YYYY, h:mm A')}>
                      {dayjs(task.scheduled_at).format('DD MMM YYYY, h:mm A')}
                      {open && ` (${dayjs(task.scheduled_at).fromNow()})`}
                    </span>
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <User className="h-3 w-3" />
                    {assignee ?? 'Unassigned'}
                  </span>
                  <span className="uppercase tracking-wide">{task.follow_up_type}</span>
                </div>

                {/* Actions only on open tasks: the backend rejects completing, cancelling
                    or rescheduling an already-closed task with a 400. */}
                {open && (
                  <PermissionGuard requiredPermission="followups:update">
                    <div className="flex flex-wrap items-center gap-2 pt-1">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={isMutating}
                        onClick={() => setConfirming({ task, action: 'complete' })}
                        data-testid={`followup-complete-${task.id}`}
                      >
                        <CheckCircle2 className="h-3.5 w-3.5 mr-1.5" />
                        Complete
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={isMutating}
                        onClick={() => onReschedule(task)}
                        data-testid={`followup-reschedule-${task.id}`}
                      >
                        <CalendarClock className="h-3.5 w-3.5 mr-1.5" />
                        Reschedule
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={isMutating}
                        onClick={() => setConfirming({ task, action: 'cancel' })}
                        data-testid={`followup-cancel-${task.id}`}
                      >
                        <Ban className="h-3.5 w-3.5 mr-1.5" />
                        Cancel
                      </Button>
                    </div>
                  </PermissionGuard>
                )}

                {task.completed_at && (
                  <p className="text-xs text-emerald-600 dark:text-emerald-500">
                    Completed {dayjs(task.completed_at).format('DD MMM YYYY, h:mm A')}
                  </p>
                )}
                {task.remarks && (
                  <p className="text-xs text-muted-foreground italic break-words">
                    {task.remarks}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      </DashboardSection>

      <ConfirmationDialog
        isOpen={!!confirming}
        title={confirming?.action === 'cancel' ? 'Cancel this follow-up?' : 'Mark as complete?'}
        description={
          confirming?.action === 'cancel'
            ? `"${confirming.task.title}" will be cancelled and the decision recorded on this lead's timeline.`
            : `"${confirming?.task.title ?? ''}" will be marked complete and recorded on this lead's timeline.`
        }
        confirmText={confirming?.action === 'cancel' ? 'Cancel Follow-up' : 'Complete'}
        cancelText="Back"
        variant={confirming?.action === 'cancel' ? 'danger' : 'success'}
        isLoading={isMutating}
        onConfirm={handleConfirm}
        onCancel={() => setConfirming(null)}
      />
    </>
  );
};
