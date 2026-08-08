/**
 * src/features/leads/components/PipelineColumn.tsx
 *
 * One status column: a drop target, a header carrying the column's totals, and the
 * scrolling stack of cards with its own Load More.
 *
 * The column is the drop target rather than the card, so a lead can be dropped anywhere in
 * the column's body — including the empty space below the last card, and including an
 * empty column, which would otherwise be the one place a card could never be moved to.
 *
 * `dragCounter` deserves a note. `dragleave` fires when the pointer crosses into a *child*
 * of the drop target, not just when it leaves the target, so highlighting naively on
 * enter/leave makes the column flicker as the cursor passes over each card. Counting
 * enters minus leaves and only clearing the highlight at zero is the standard fix.
 */

import * as React from 'react';
import { Inbox, Loader2 } from 'lucide-react';
import { Badge } from '../../../components/ui/Badge';
import { Button } from '../../../components/ui/Button';
import { Skeleton } from '../../../components/ui/Skeleton';
import { PipelineCard } from './PipelineCard';
import { humanizeStatus } from './LeadStatusBadge';
import { Lead, LeadStatus, PipelineColumnState } from '../types';

/**
 * The accent stripe on each column header.
 *
 * Mirrors the badge semantics used across the lead module — progress toward a sale reads
 * green, active engagement blue, attention-needed amber, dead ends red — so a column's
 * colour and its cards' badges never disagree. Both light and dark values are given
 * explicitly, since these are decorative fills rather than themed tokens.
 */
const COLUMN_ACCENTS: Record<string, string> = {
  NEW: 'bg-sky-500',
  CONTACTED: 'bg-slate-400 dark:bg-slate-500',
  MESSAGE_SENT: 'bg-slate-400 dark:bg-slate-500',
  REPLIED: 'bg-sky-500',
  INTERESTED: 'bg-emerald-500',
  NEGOTIATION: 'bg-amber-500',
  FOLLOW_UP: 'bg-amber-500',
  CONVERTED: 'bg-emerald-600',
  LOST: 'bg-rose-500',
};

export interface PipelineColumnProps {
  column: PipelineColumnState;
  /** Resolves an assignee id to a display name; supplied by the board. */
  resolveAssignee: (employeeId: string | null) => string | null;
  /** Resolves a lead's next open follow-up due date, if any. */
  resolveFollowUpDue: (leadId: string) => string | null;
  isDragActive: boolean;
  isDragOver: boolean;
  draggingLeadId: string | null;
  movingLeadId: string | null;
  onDragStart: (lead: Lead) => void;
  onDragEnd: () => void;
  onDragEnterColumn: (status: LeadStatus | null) => void;
  onDrop: (status: LeadStatus) => void;
  onCreateFollowUp: (lead: Lead) => void;
  onAddNote: (lead: Lead) => void;
  onMoveTo: (lead: Lead, status: LeadStatus) => void;
}

export const PipelineColumn = ({
  column,
  resolveAssignee,
  resolveFollowUpDue,
  isDragActive,
  isDragOver,
  draggingLeadId,
  movingLeadId,
  onDragStart,
  onDragEnd,
  onDragEnterColumn,
  onDrop,
  onCreateFollowUp,
  onAddNote,
  onMoveTo,
}: PipelineColumnProps) => {
  const dragCounter = React.useRef(0);

  const handleDragEnter = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragCounter.current += 1;
    onDragEnterColumn(column.status);
  };

  const handleDragLeave = () => {
    dragCounter.current = Math.max(0, dragCounter.current - 1);
    if (dragCounter.current === 0) onDragEnterColumn(null);
  };

  const handleDragOver = (event: React.DragEvent<HTMLDivElement>) => {
    // Without preventDefault the browser treats the element as a non-target and the drop
    // event never fires. This is the single most important line in the DnD implementation.
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  };

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragCounter.current = 0;
    onDrop(column.status);
  };

  const accent = COLUMN_ACCENTS[column.status] ?? 'bg-slate-400';

  return (
    <section
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      aria-label={`${humanizeStatus(column.status)} column, ${column.total} leads`}
      data-testid={`pipeline-column-${column.status}`}
      data-drag-over={isDragOver ? 'true' : 'false'}
      className={[
        'flex h-full w-72 shrink-0 flex-col rounded-xl border bg-muted/40 transition-colors',
        'sm:w-80',
        isDragOver
          ? 'border-primary bg-primary/5 ring-2 ring-primary/30'
          : 'border-border',
      ].join(' ')}
    >
      {/* Header — sticky so the column's identity and totals stay visible while its
          card list scrolls independently. */}
      <header className="sticky top-0 z-10 rounded-t-xl border-b border-border bg-muted/80 px-3 py-2.5 backdrop-blur">
        <div className="flex items-center gap-2">
          <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${accent}`} aria-hidden="true" />
          <h3 className="flex-1 truncate text-sm font-semibold text-foreground">
            {humanizeStatus(column.status)}
          </h3>
          <Badge variant="secondary" size="sm" data-testid={`pipeline-total-${column.status}`}>
            {column.total}
          </Badge>
        </div>

        {/* Only shown once a column is partially loaded, so a fully-loaded column is not
            cluttered with "12 of 12". */}
        {column.loadedCount > 0 && column.hasMore && (
          <p className="mt-1 text-[11px] text-muted-foreground" data-testid={`pipeline-loaded-${column.status}`}>
            Showing {column.loadedCount} of {column.total}
          </p>
        )}
      </header>

      <div className="flex-1 space-y-2 overflow-y-auto p-2">
        {column.isLoading && (
          <div className="space-y-2" data-testid={`pipeline-skeleton-${column.status}`}>
            <Skeleton className="h-28 w-full rounded-lg" />
            <Skeleton className="h-28 w-full rounded-lg" />
          </div>
        )}

        {!column.isLoading && column.isError && (
          <p
            className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive"
            role="alert"
            data-testid={`pipeline-error-${column.status}`}
          >
            Could not load this column.
          </p>
        )}

        {!column.isLoading && !column.isError && column.leads.length === 0 && (
          <div
            className="flex flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed border-border py-8 text-center"
            data-testid={`pipeline-empty-${column.status}`}
          >
            <Inbox className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
            <p className="text-xs text-muted-foreground">
              {isDragActive ? 'Drop here' : 'No leads'}
            </p>
          </div>
        )}

        {column.leads.map((lead) => (
          <PipelineCard
            key={lead.id}
            lead={lead}
            assigneeName={resolveAssignee(lead.assigned_employee_id)}
            followUpDueAt={resolveFollowUpDue(lead.id)}
            isDragging={draggingLeadId === lead.id}
            isMoving={movingLeadId === lead.id}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            onCreateFollowUp={onCreateFollowUp}
            onAddNote={onAddNote}
            onMoveTo={onMoveTo}
          />
        ))}

        {column.hasMore && (
          <Button
            variant="outline"
            size="sm"
            fullWidth
            disabled={column.isFetchingMore}
            onClick={column.loadMore}
            data-testid={`pipeline-load-more-${column.status}`}
          >
            {column.isFetchingMore ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                Loading…
              </>
            ) : (
              `Load more (${column.total - column.loadedCount} left)`
            )}
          </Button>
        )}
      </div>
    </section>
  );
};
