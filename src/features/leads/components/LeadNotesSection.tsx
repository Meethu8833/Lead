/**
 * src/features/leads/components/LeadNotesSection.tsx
 *
 * Human-authored commentary on a lead: add, edit and delete, with author and timestamp.
 *
 * Notes are separate from the timeline on purpose, and the backend enforces the split —
 * adding a note appends a NOTE entry to the immutable timeline, but editing or deleting
 * the note leaves that entry standing. So this section is the mutable view of the same
 * facts the timeline records permanently.
 *
 * All three mutations require `leads:update` server-side (notes reuse the lead permission
 * set rather than introducing `lead-notes:*`), so the composer and the per-note controls
 * are gated on exactly that.
 */

import * as React from 'react';
import dayjs from 'dayjs';
import { Pencil, StickyNote, Trash2, X } from 'lucide-react';
import { Button } from '../../../components/ui/Button';
import { Textarea } from '../../../components/ui/Textarea';
import { ConfirmationDialog } from '../../../components/ui/ConfirmationDialog';
import PermissionGuard from '../../../components/auth/PermissionGuard';
import { DashboardSection } from './DashboardSection';
import { LeadNote } from '../types';

export interface LeadNotesSectionProps {
  notes: LeadNote[];
  total: number;
  /** Employee id → display name, for attributing each note to its author. */
  authorNames: Record<string, string>;
  isLoading: boolean;
  isError: boolean;
  isEmpty: boolean;
  onCreate: (note: string) => Promise<unknown>;
  onUpdate: (noteId: string, note: string) => Promise<unknown>;
  onDelete: (noteId: string) => Promise<unknown>;
  isMutating?: boolean;
  onRetry?: () => void;
  /** Focuses the composer on mount — set when arriving from the "Add Note" quick action. */
  autoFocusComposer?: boolean;
}

export const LeadNotesSection = ({
  notes,
  total,
  authorNames,
  isLoading,
  isError,
  isEmpty,
  onCreate,
  onUpdate,
  onDelete,
  isMutating = false,
  onRetry,
  autoFocusComposer = false,
}: LeadNotesSectionProps) => {
  const [draft, setDraft] = React.useState('');
  const [editingId, setEditingId] = React.useState<string | null>(null);
  const [editDraft, setEditDraft] = React.useState('');
  const [deletingId, setDeletingId] = React.useState<string | null>(null);
  const composerRef = React.useRef<HTMLTextAreaElement>(null);

  React.useEffect(() => {
    if (autoFocusComposer) composerRef.current?.focus();
  }, [autoFocusComposer]);

  // The backend rejects a whitespace-only body, so the button is disabled on the same
  // rule rather than letting the request fail.
  const canSubmit = draft.trim().length > 0 && !isMutating;

  const handleCreate = async () => {
    if (!canSubmit) return;
    await onCreate(draft.trim());
    setDraft('');
  };

  const handleUpdate = async () => {
    if (!editingId || !editDraft.trim()) return;
    await onUpdate(editingId, editDraft.trim());
    setEditingId(null);
    setEditDraft('');
  };

  const handleDelete = async () => {
    if (!deletingId) return;
    await onDelete(deletingId);
    setDeletingId(null);
  };

  const authorFor = (note: LeadNote) =>
    (note.created_by_employee_id && authorNames[note.created_by_employee_id]) || 'System';

  return (
    <>
      <DashboardSection
        title="Notes"
        description={total > 0 ? `${total} ${total === 1 ? 'note' : 'notes'}` : undefined}
        icon={<StickyNote className="h-4 w-4" />}
        isLoading={isLoading}
        isError={isError}
        // The composer must stay reachable on an empty list, so emptiness is handled
        // inline below rather than by the section's own empty state.
        isEmpty={false}
        errorDescription="We could not load this lead's notes. Please try again."
        onRetry={onRetry}
        skeletonRows={3}
        data-testid="lead-notes-section"
      >
        <div className="space-y-4">
          <PermissionGuard requiredPermission="leads:update">
            <div className="space-y-2" data-testid="note-composer">
              <Textarea
                ref={composerRef}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Add a note about this lead…"
                rows={3}
                maxLength={10000}
                disabled={isMutating}
                fullWidth
                data-testid="note-composer-input"
              />
              <div className="flex justify-end">
                <Button
                  variant="primary"
                  size="sm"
                  disabled={!canSubmit}
                  isLoading={isMutating}
                  onClick={handleCreate}
                  data-testid="note-composer-submit"
                >
                  Add Note
                </Button>
              </div>
            </div>
          </PermissionGuard>

          {isEmpty ? (
            <p className="text-sm text-muted-foreground py-2" data-testid="lead-notes-empty">
              No notes on this lead yet.
            </p>
          ) : (
            <ul className="space-y-3" data-testid="lead-notes-list">
              {notes.map((note) => (
                <li
                  key={note.id}
                  className="rounded-lg border border-border bg-muted/30 dark:bg-muted/10 p-3 space-y-2"
                  data-testid={`lead-note-${note.id}`}
                >
                  {editingId === note.id ? (
                    <div className="space-y-2">
                      <Textarea
                        value={editDraft}
                        onChange={(event) => setEditDraft(event.target.value)}
                        rows={3}
                        maxLength={10000}
                        disabled={isMutating}
                        fullWidth
                        data-testid="note-edit-input"
                      />
                      <div className="flex justify-end gap-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setEditingId(null);
                            setEditDraft('');
                          }}
                          data-testid="note-edit-cancel"
                        >
                          <X className="h-3.5 w-3.5 mr-1.5" />
                          Cancel
                        </Button>
                        <Button
                          variant="primary"
                          size="sm"
                          disabled={!editDraft.trim() || isMutating}
                          isLoading={isMutating}
                          onClick={handleUpdate}
                          data-testid="note-edit-save"
                        >
                          Save
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <p
                        className="text-sm text-foreground whitespace-pre-wrap break-words"
                        data-testid="note-body"
                      >
                        {note.note}
                      </p>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-xs text-muted-foreground">
                          <span className="font-medium text-foreground/80">{authorFor(note)}</span>
                          {' · '}
                          <span title={dayjs(note.created_at).format('DD MMM YYYY, h:mm A')}>
                            {dayjs(note.created_at).format('DD MMM YYYY, h:mm A')}
                          </span>
                          {/* Surfaced because the timeline's NOTE entry records only the
                              original authoring time, so an edit is otherwise invisible. */}
                          {note.updated_at !== note.created_at && ' · edited'}
                        </p>

                        <PermissionGuard requiredPermission="leads:update">
                          <div className="flex items-center gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                setEditingId(note.id);
                                setEditDraft(note.note);
                              }}
                              data-testid={`note-edit-${note.id}`}
                              aria-label="Edit note"
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setDeletingId(note.id)}
                              data-testid={`note-delete-${note.id}`}
                              aria-label="Delete note"
                            >
                              <Trash2 className="h-3.5 w-3.5 text-destructive" />
                            </Button>
                          </div>
                        </PermissionGuard>
                      </div>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </DashboardSection>

      <ConfirmationDialog
        isOpen={!!deletingId}
        title="Delete this note?"
        description="The note will be removed from this lead. The timeline entry recording that a note was added is kept."
        confirmText="Delete"
        variant="danger"
        isLoading={isMutating}
        onConfirm={handleDelete}
        onCancel={() => setDeletingId(null)}
      />
    </>
  );
};
