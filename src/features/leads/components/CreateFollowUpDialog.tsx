/**
 * src/features/leads/components/CreateFollowUpDialog.tsx
 *
 * The form behind "Create Follow-up" on the Lead Details workspace.
 *
 * The lead is fixed by context, so `lead_id` is supplied by the parent rather than
 * chosen here — this dialog only collects what varies. Assignee is optional and drawn
 * from the employee directory; leaving it blank creates an unassigned task, which the
 * backend permits.
 */

import * as React from 'react';
import dayjs from 'dayjs';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../../components/ui/Dialog';
import { Button } from '../../../components/ui/Button';
import { Input } from '../../../components/ui/Input';
import { Select } from '../../../components/ui/Select';
import { Textarea } from '../../../components/ui/Textarea';
import {
  EmployeeSummary,
  FollowUpCreatePayload,
  FollowUpPriority,
  FollowUpType,
} from '../types';

const FOLLOW_UP_TYPES: FollowUpType[] = ['CALL', 'WHATSAPP', 'EMAIL', 'MEETING', 'VISIT', 'OTHER'];
const PRIORITIES: FollowUpPriority[] = ['LOW', 'MEDIUM', 'HIGH', 'URGENT'];

/** Turns CALL into "Call", MEDIUM into "Medium". */
const titleCase = (value: string) =>
  value.charAt(0).toUpperCase() + value.slice(1).toLowerCase();

/** `datetime-local` needs a zone-less "YYYY-MM-DDTHH:mm", not an ISO string. */
const defaultScheduledAt = () => dayjs().add(1, 'day').startOf('hour').format('YYYY-MM-DDTHH:mm');

export interface CreateFollowUpDialogProps {
  isOpen: boolean;
  leadName?: string;
  employees: EmployeeSummary[];
  isSubmitting?: boolean;
  onClose: () => void;
  onConfirm: (payload: Omit<FollowUpCreatePayload, 'lead_id'>) => Promise<unknown>;
}

export const CreateFollowUpDialog = ({
  isOpen,
  leadName,
  employees,
  isSubmitting = false,
  onClose,
  onConfirm,
}: CreateFollowUpDialogProps) => {
  const [title, setTitle] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [followUpType, setFollowUpType] = React.useState<FollowUpType>('CALL');
  const [priority, setPriority] = React.useState<FollowUpPriority>('MEDIUM');
  const [scheduledAt, setScheduledAt] = React.useState(defaultScheduledAt);
  const [assigneeId, setAssigneeId] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);

  // Reset on every open so a previous draft never leaks into a new task.
  React.useEffect(() => {
    if (!isOpen) return;
    setTitle('');
    setDescription('');
    setFollowUpType('CALL');
    setPriority('MEDIUM');
    setScheduledAt(defaultScheduledAt());
    setAssigneeId('');
    setError(null);
  }, [isOpen]);

  const handleConfirm = async () => {
    // Mirrors the backend's own validation (title non-blank, scheduled_at required) so
    // the common mistakes never cost a round trip.
    if (!title.trim()) {
      setError('Please enter a title for this follow-up.');
      return;
    }

    const parsed = dayjs(scheduledAt);
    if (!scheduledAt || !parsed.isValid()) {
      setError('Please choose a valid date and time.');
      return;
    }

    setError(null);
    try {
      await onConfirm({
        title: title.trim(),
        description: description.trim() || null,
        follow_up_type: followUpType,
        priority,
        // toISOString() supplies the UTC offset the bare datetime-local input lacks.
        scheduled_at: parsed.toDate().toISOString(),
        assigned_employee_id: assigneeId || null,
      });
      onClose();
    } catch {
      setError('Could not create the follow-up. Please try again.');
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && !isSubmitting && onClose()}>
      <DialogContent size="lg" data-testid="create-followup-dialog">
        <DialogHeader>
          <DialogTitle>Create follow-up</DialogTitle>
          <DialogDescription>
            {leadName
              ? `Schedule the next touchpoint with "${leadName}".`
              : 'Schedule the next touchpoint with this lead.'}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <Input
            label="Title"
            required
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="e.g. Call to discuss the album package"
            maxLength={255}
            disabled={isSubmitting}
            fullWidth
            data-testid="followup-title-input"
          />

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Select
              label="Type"
              value={followUpType}
              onChange={(event) => setFollowUpType(event.target.value as FollowUpType)}
              options={FOLLOW_UP_TYPES.map((type) => ({ label: titleCase(type), value: type }))}
              disabled={isSubmitting}
              fullWidth
              data-testid="followup-type-select"
            />

            <Select
              label="Priority"
              value={priority}
              onChange={(event) => setPriority(event.target.value as FollowUpPriority)}
              options={PRIORITIES.map((level) => ({ label: titleCase(level), value: level }))}
              disabled={isSubmitting}
              fullWidth
              data-testid="followup-priority-select"
            />
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="followup-datetime"
              className="text-sm font-medium text-foreground"
            >
              Due date &amp; time <span className="text-destructive">*</span>
            </label>
            <Input
              id="followup-datetime"
              type="datetime-local"
              value={scheduledAt}
              onChange={(event) => setScheduledAt(event.target.value)}
              disabled={isSubmitting}
              fullWidth
              data-testid="followup-datetime-input"
            />
          </div>

          {/* "Unassigned" is a real option rather than `placeholder`, because Select
              renders its placeholder as `disabled hidden` — usable as a prompt, but not
              re-selectable once an assignee has been picked. Leaving a task unassigned is
              a legitimate choice the backend accepts, so it needs a selectable entry. */}
          <Select
            label="Assign to"
            value={assigneeId}
            onChange={(event) => setAssigneeId(event.target.value)}
            options={[
              { label: 'Unassigned', value: '' },
              ...employees.map((employee) => ({
                label: employee.full_name ?? employee.name ?? employee.email ?? employee.id,
                value: employee.id,
              })),
            ]}
            disabled={isSubmitting}
            fullWidth
            data-testid="followup-assignee-select"
          />

          <Textarea
            label="Description"
            rows={3}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="What needs to happen?"
            maxLength={10000}
            disabled={isSubmitting}
            fullWidth
            data-testid="followup-description-input"
          />

          {error && (
            <p className="text-xs text-destructive" role="alert" data-testid="followup-error">
              {error}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={onClose}
            disabled={isSubmitting}
            data-testid="followup-cancel"
          >
            Cancel
          </Button>
          <Button
            onClick={handleConfirm}
            isLoading={isSubmitting}
            data-testid="followup-submit"
          >
            Create Follow-up
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
