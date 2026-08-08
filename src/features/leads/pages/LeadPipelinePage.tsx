/**
 * src/features/leads/pages/LeadPipelinePage.tsx
 *
 * The Lead Pipeline board — every lead in the CRM, grouped into a column per status, with
 * drag-and-drop between columns.
 *
 * The page is a composition root and nothing more: it owns the filter/sort state and the
 * two dialogs, wires the hooks to the columns, and holds no data logic of its own. The
 * fetching, page accumulation, sorting and the optimistic move all live in
 * `pipelineHooks.ts`; the comparators and column list live in `pipelineUtils.ts`.
 *
 * Layout is a horizontally scrolling row of fixed-width columns, each scrolling
 * vertically inside itself, rather than a wrapping grid. Nine columns cannot be made
 * legible on a phone at any width, and a wrapping grid breaks the left-to-right
 * progression that makes a pipeline readable in the first place — so the board scrolls
 * sideways at every breakpoint and the columns simply get a little wider on larger ones.
 */

import * as React from 'react';
import { LayoutGrid, RefreshCw } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '../../../components/ui/Button';
import { Badge } from '../../../components/ui/Badge';
import { useNotificationStore } from '../../../app/store';
import { useLeadEmployees } from '../hooks';
import {
  pipelineKeys,
  usePipelineBoard,
  usePipelineCreateFollowUp,
  usePipelineCreateNote,
  usePipelineDragAndDrop,
  usePipelineFollowUpDueDates,
} from '../pipelineHooks';
import { EMPTY_PIPELINE_FILTERS } from '../pipelineUtils';
import { PipelineColumn } from '../components/PipelineColumn';
import { PipelineFiltersBar } from '../components/PipelineFilters';
import { CreateFollowUpDialog } from '../components/CreateFollowUpDialog';
import { AddNoteDialog } from '../components/AddNoteDialog';
import {
  EmployeeSummary,
  FollowUpCreatePayload,
  Lead,
  LeadStatus,
  PipelineFilters as PipelineFiltersState,
  PipelineSort,
} from '../types';

export const LeadPipelinePage = () => {
  const queryClient = useQueryClient();
  const { addToast } = useNotificationStore();

  const [filters, setFilters] = React.useState<PipelineFiltersState>(EMPTY_PIPELINE_FILTERS);
  const [sort, setSort] = React.useState<PipelineSort>('NEWEST');

  // Which lead a dialog is acting on. Null closes the dialog, so one piece of state
  // covers both "is it open" and "what is it about" — they cannot disagree.
  const [followUpLead, setFollowUpLead] = React.useState<Lead | null>(null);
  const [noteLead, setNoteLead] = React.useState<Lead | null>(null);

  const { columns, totalLeads, isLoading } = usePipelineBoard(filters, sort);
  const { resolveFollowUpDue } = usePipelineFollowUpDueDates();
  const employeesQuery = useLeadEmployees();
  const employees: EmployeeSummary[] = employeesQuery.data ?? [];

  const dnd = usePipelineDragAndDrop(filters);
  const createFollowUp = usePipelineCreateFollowUp();
  const createNote = usePipelineCreateNote();

  /** Resolves an assignee id to a name, so cards never learn the employee endpoint exists. */
  const resolveAssignee = React.useCallback(
    (employeeId: string | null): string | null => {
      if (!employeeId) return null;
      const employee = employees.find((candidate) => candidate.id === employeeId);
      return employee?.full_name ?? employee?.name ?? null;
    },
    [employees]
  );

  const handleFilterChange = React.useCallback((patch: Partial<PipelineFiltersState>) => {
    setFilters((current) => ({ ...current, ...patch }));
  }, []);

  const handleClearFilters = React.useCallback(() => {
    setFilters(EMPTY_PIPELINE_FILTERS);
  }, []);

  /** Refetches every column. The board does not poll, so this is how a stale board recovers. */
  const handleRefresh = React.useCallback(() => {
    queryClient.invalidateQueries({ queryKey: pipelineKeys.board() });
  }, [queryClient]);

  /**
   * The "Move to…" select on a card — the keyboard and touch equivalent of a drag.
   *
   * Routed through the same `onDrop` the drag path uses, so both gestures share one code
   * path: identical optimistic update, identical rollback, identical toasts.
   */
  const handleMoveTo = React.useCallback(
    (lead: Lead, status: LeadStatus) => {
      void dnd.onDrop(status, lead);
    },
    [dnd]
  );

  const handleCreateFollowUp = async (payload: Omit<FollowUpCreatePayload, 'lead_id'>) => {
    if (!followUpLead) return;
    const lead = followUpLead;
    try {
      await createFollowUp.mutateAsync({ leadId: lead.id, payload });
      addToast({
        title: 'Follow-up created',
        message: `A follow-up was scheduled for "${lead.business_name}".`,
        type: 'success',
      });
    } catch (error) {
      addToast({
        title: 'Could not create follow-up',
        message: `The follow-up for "${lead.business_name}" was not saved.`,
        type: 'error',
      });
      // Rethrown so the dialog stays open with the draft intact — the user should not
      // have to retype a task because the network blipped.
      throw error;
    }
  };

  const handleAddNote = async (note: string) => {
    if (!noteLead) return;
    const lead = noteLead;
    try {
      await createNote.mutateAsync({ leadId: lead.id, note });
      addToast({
        title: 'Note added',
        message: `Your note was added to "${lead.business_name}".`,
        type: 'success',
      });
    } catch (error) {
      addToast({
        title: 'Could not add note',
        message: `The note for "${lead.business_name}" was not saved.`,
        type: 'error',
      });
      throw error;
    }
  };

  return (
    <div className="flex h-full flex-col gap-4" data-testid="lead-pipeline-page">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-extrabold tracking-tight text-foreground sm:text-3xl">
            <LayoutGrid className="h-6 w-6 text-primary" aria-hidden="true" />
            Lead Pipeline
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Drag a card between columns to change its status, or use the card&apos;s
            &ldquo;Move&rdquo; menu.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Badge variant="secondary" data-testid="pipeline-grand-total">
            {totalLeads} {totalLeads === 1 ? 'lead' : 'leads'}
          </Badge>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefresh}
            disabled={isLoading}
            data-testid="pipeline-refresh"
          >
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      <PipelineFiltersBar
        filters={filters}
        sort={sort}
        employees={employees}
        onChange={handleFilterChange}
        onSortChange={setSort}
        onClear={handleClearFilters}
      />

      {/* The board. `min-h-0` is what allows the columns to own their own vertical
          scrolling instead of stretching this flex child to the height of the tallest. */}
      <div
        className="flex min-h-0 flex-1 gap-3 overflow-x-auto pb-3"
        role="list"
        aria-label="Lead pipeline columns"
        data-testid="pipeline-board"
      >
        {columns.map((column) => (
          <PipelineColumn
            key={column.status}
            column={column}
            resolveAssignee={resolveAssignee}
            resolveFollowUpDue={resolveFollowUpDue}
            isDragActive={!!dnd.draggingLeadId}
            isDragOver={dnd.dragOverStatus === column.status}
            draggingLeadId={dnd.draggingLeadId}
            movingLeadId={dnd.movingLeadId}
            onDragStart={dnd.onDragStart}
            onDragEnd={dnd.onDragEnd}
            onDragEnterColumn={dnd.onDragEnterColumn}
            onDrop={(status) => void dnd.onDrop(status)}
            onCreateFollowUp={setFollowUpLead}
            onAddNote={setNoteLead}
            onMoveTo={handleMoveTo}
          />
        ))}
      </div>

      <CreateFollowUpDialog
        isOpen={!!followUpLead}
        leadName={followUpLead?.business_name}
        employees={employees}
        isSubmitting={createFollowUp.isPending}
        onClose={() => setFollowUpLead(null)}
        onConfirm={handleCreateFollowUp}
      />

      <AddNoteDialog
        isOpen={!!noteLead}
        leadName={noteLead?.business_name}
        isSubmitting={createNote.isPending}
        onClose={() => setNoteLead(null)}
        onConfirm={handleAddNote}
      />
    </div>
  );
};

export default LeadPipelinePage;
