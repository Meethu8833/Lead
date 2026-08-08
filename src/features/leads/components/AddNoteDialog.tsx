/**
 * src/features/leads/components/AddNoteDialog.tsx
 *
 * The "Add Note" quick action from a pipeline card.
 *
 * The Lead Details page adds notes through an inline composer inside `LeadNotesSection`,
 * which is bound to the one lead that page is about. The board is about many leads at
 * once and has no room for an inline composer on a card, so the same action is a dialog
 * here, parameterised by whichever card raised it.
 */

import * as React from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../../components/ui/Dialog';
import { Button } from '../../../components/ui/Button';
import { Textarea } from '../../../components/ui/Textarea';

export interface AddNoteDialogProps {
  isOpen: boolean;
  leadName?: string;
  isSubmitting?: boolean;
  onClose: () => void;
  onConfirm: (note: string) => Promise<unknown>;
}

export const AddNoteDialog = ({
  isOpen,
  leadName,
  isSubmitting = false,
  onClose,
  onConfirm,
}: AddNoteDialogProps) => {
  const [note, setNote] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);

  // Reset on every open so a draft abandoned against one lead never reappears against
  // another — which on a board, where the dialog is reused across cards, would otherwise
  // be easy to do and hard to notice.
  React.useEffect(() => {
    if (!isOpen) return;
    setNote('');
    setError(null);
  }, [isOpen]);

  const handleConfirm = async () => {
    if (!note.trim()) {
      setError('Please write something before saving.');
      return;
    }

    setError(null);
    try {
      await onConfirm(note.trim());
      onClose();
    } catch {
      setError('Could not save the note. Please try again.');
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && !isSubmitting && onClose()}>
      <DialogContent data-testid="add-note-dialog">
        <DialogHeader>
          <DialogTitle>Add note</DialogTitle>
          <DialogDescription>
            {leadName
              ? `This note will be added to "${leadName}" and appear on its timeline.`
              : "This note will be added to the lead's timeline."}
          </DialogDescription>
        </DialogHeader>

        <Textarea
          label="Note"
          rows={5}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="What should the team know about this lead?"
          maxLength={10000}
          disabled={isSubmitting}
          fullWidth
          autoFocus
          data-testid="add-note-input"
        />

        {error && (
          <p className="text-xs text-destructive" role="alert" data-testid="add-note-error">
            {error}
          </p>
        )}

        <DialogFooter>
          <Button
            variant="outline"
            onClick={onClose}
            disabled={isSubmitting}
            data-testid="add-note-cancel"
          >
            Cancel
          </Button>
          <Button onClick={handleConfirm} isLoading={isSubmitting} data-testid="add-note-submit">
            Save Note
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
