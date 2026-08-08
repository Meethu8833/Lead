/**
 * src/features/leads/components/RescheduleDialog.tsx
 *
 * The date/time prompt behind the "Reschedule" action on a follow-up.
 *
 * Kept separate from `TodaysFollowUps` so the list stays a pure presentation component
 * and this dialog can be tested on its own. It owns only its form state; the mutation is
 * the parent's, handed in as `onConfirm`.
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
import { Textarea } from '../../../components/ui/Textarea';

export interface RescheduleDialogProps {
  isOpen: boolean;
  taskTitle?: string;
  /** Current due time, used to seed the picker. */
  currentScheduledAt?: string;
  isSubmitting?: boolean;
  onClose: () => void;
  onConfirm: (scheduledAt: string, remarks: string) => void;
}

/** `datetime-local` needs a zone-less "YYYY-MM-DDTHH:mm", not an ISO string. */
const toLocalInputValue = (value?: string): string => {
  const base = value && dayjs(value).isValid() ? dayjs(value) : dayjs().add(1, 'day');
  return base.format('YYYY-MM-DDTHH:mm');
};

export const RescheduleDialog = ({
  isOpen,
  taskTitle,
  currentScheduledAt,
  isSubmitting = false,
  onClose,
  onConfirm,
}: RescheduleDialogProps) => {
  const [scheduledAt, setScheduledAt] = React.useState(() => toLocalInputValue(currentScheduledAt));
  const [remarks, setRemarks] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);

  // Re-seed whenever a different task opens the dialog, so it never shows the previous
  // task's due time.
  React.useEffect(() => {
    if (isOpen) {
      setScheduledAt(toLocalInputValue(currentScheduledAt));
      setRemarks('');
      setError(null);
    }
  }, [isOpen, currentScheduledAt]);

  const handleConfirm = () => {
    const parsed = dayjs(scheduledAt);

    if (!scheduledAt || !parsed.isValid()) {
      setError('Please choose a valid date and time.');
      return;
    }

    if (parsed.isBefore(dayjs())) {
      setError('The new time must be in the future.');
      return;
    }

    setError(null);
    // The API requires a timezone-aware value; toISOString() supplies the UTC offset
    // that the bare datetime-local input lacks.
    onConfirm(parsed.toDate().toISOString(), remarks.trim());
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && !isSubmitting && onClose()}>
      <DialogContent data-testid="reschedule-dialog">
        <DialogHeader>
          <DialogTitle>Reschedule follow-up</DialogTitle>
          <DialogDescription>
            {taskTitle
              ? `Choose a new date and time for "${taskTitle}".`
              : 'Choose a new date and time for this follow-up.'}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <label
              htmlFor="reschedule-datetime"
              className="text-sm font-medium text-foreground"
            >
              New date &amp; time
            </label>
            <Input
              id="reschedule-datetime"
              type="datetime-local"
              value={scheduledAt}
              onChange={(event) => setScheduledAt(event.target.value)}
              disabled={isSubmitting}
              data-testid="reschedule-datetime-input"
            />
            {error && (
              <p className="text-xs text-destructive" data-testid="reschedule-error">
                {error}
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <label htmlFor="reschedule-remarks" className="text-sm font-medium text-foreground">
              Reason <span className="text-muted-foreground font-normal">(optional)</span>
            </label>
            <Textarea
              id="reschedule-remarks"
              rows={3}
              value={remarks}
              placeholder="Why is this being moved?"
              onChange={(event) => setRemarks(event.target.value)}
              disabled={isSubmitting}
              data-testid="reschedule-remarks-input"
            />
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={onClose}
            disabled={isSubmitting}
            data-testid="reschedule-cancel"
          >
            Cancel
          </Button>
          <Button
            onClick={handleConfirm}
            isLoading={isSubmitting}
            data-testid="reschedule-confirm"
          >
            Reschedule
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
