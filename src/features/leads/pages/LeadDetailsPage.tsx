/**
 * src/features/leads/pages/LeadDetailsPage.tsx
 *
 * The Lead Details workspace — the primary screen for working a single lead.
 *
 * Like the dashboard, this page is deliberately thin: it resolves the lead id from the
 * route, calls the feature's hooks, owns the dialog open/closed state, and lays the
 * sections out. Every fetch, join and cache-invalidation decision lives in
 * `detailHooks.ts`; every piece of markup is a component from `../components`.
 *
 * Sections are gated individually rather than all-or-nothing, matching the dashboard's
 * precedent: someone with `leads:view` but not `followups:view` still gets a useful
 * profile, timeline and notes instead of a permission wall.
 */

import * as React from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import { PageContainer, PageHeader } from '../../../components/ui/LayoutHelpers';
import { Button } from '../../../components/ui/Button';
import { ErrorState } from '../../../components/ui/ErrorState';
import { useAuthStore, useNotificationStore } from '../../../app/store';
import { checkPermission } from '../../../components/auth/PermissionGuard';
import { LeadProfileCard } from '../components/LeadProfileCard';
import { LeadStatusPanel } from '../components/LeadStatusPanel';
import { LeadQuickActions } from '../components/LeadQuickActions';
import { LeadActivityTimeline } from '../components/LeadActivityTimeline';
import { LeadNotesSection } from '../components/LeadNotesSection';
import { LeadFollowUpsSection } from '../components/LeadFollowUpsSection';
import { LeadWhatsAppHistory } from '../components/LeadWhatsAppHistory';
import { EditLeadDialog } from '../components/EditLeadDialog';
import { CreateFollowUpDialog } from '../components/CreateFollowUpDialog';
import { RescheduleDialog } from '../components/RescheduleDialog';
import { useLeadEmployees } from '../hooks';
import {
  useCancelLeadFollowUp,
  useCompleteLeadFollowUp,
  useCreateLeadFollowUp,
  useCreateLeadNote,
  useDeleteLeadNote,
  useLead,
  useLeadActivities,
  useLeadFollowUps,
  useLeadNotes,
  useLeadWhatsAppHistory,
  useRescheduleLeadFollowUp,
  useUpdateLead,
  useUpdateLeadNote,
  useUpdateLeadStatus,
} from '../detailHooks';
import { FollowUpTask, LeadStatus, LeadUpdatePayload } from '../types';

export const LeadDetailsPage = () => {
  const { id } = useParams<{ id: string }>();
  const leadId = id ?? '';
  const navigate = useNavigate();
  const addToast = useNotificationStore((state) => state.addToast);

  const { permissions, user } = useAuthStore();
  const roleName = user?.role?.name;
  const canUpdateLead = checkPermission(permissions, 'leads:update', roleName);
  const canViewFollowUps = checkPermission(permissions, 'followups:view', roleName);
  const canViewWhatsApp = checkPermission(permissions, 'whatsapp:view', roleName);

  // ----- Data -----
  const { lead, assigneeName, isLoading, isError, refetch } = useLead(leadId);
  const activities = useLeadActivities(leadId);
  const notes = useLeadNotes(leadId);
  const followUps = useLeadFollowUps(leadId);
  const whatsapp = useLeadWhatsAppHistory(leadId);
  const employeesQuery = useLeadEmployees();

  // ----- Mutations -----
  const updateLead = useUpdateLead(leadId);
  const statusMutation = useUpdateLeadStatus(leadId);
  const createNote = useCreateLeadNote(leadId);
  const updateNote = useUpdateLeadNote(leadId);
  const deleteNote = useDeleteLeadNote(leadId);
  const createFollowUp = useCreateLeadFollowUp(leadId);
  const completeFollowUp = useCompleteLeadFollowUp(leadId);
  const cancelFollowUp = useCancelLeadFollowUp(leadId);
  const rescheduleFollowUp = useRescheduleLeadFollowUp(leadId);

  // ----- Dialog state -----
  const [isEditOpen, setIsEditOpen] = React.useState(false);
  const [isCreateFollowUpOpen, setIsCreateFollowUpOpen] = React.useState(false);
  const [reschedulingTask, setReschedulingTask] = React.useState<FollowUpTask | null>(null);
  // Bumped by the "Add Note" quick action to focus the composer further down the page.
  const [noteFocusToken, setNoteFocusToken] = React.useState(0);

  const notesRef = React.useRef<HTMLDivElement>(null);

  const handleAddNoteShortcut = () => {
    setNoteFocusToken((token) => token + 1);
    notesRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  // ----- Handlers -----
  const handleUpdateLead = async (payload: LeadUpdatePayload) => {
    const result = await updateLead.mutateAsync(payload);
    addToast({ message: 'Lead updated.', type: 'success' });
    return result;
  };

  const handleStatusChange = async (status: LeadStatus, version?: number) => {
    const result = await statusMutation.updateStatus(status, version);
    addToast({ message: 'Lead status updated.', type: 'success' });
    return result;
  };

  const handleCreateNote = async (note: string) => {
    await createNote.mutateAsync(note);
    addToast({ message: 'Note added.', type: 'success' });
  };

  const handleUpdateNote = async (noteId: string, note: string) => {
    await updateNote.mutateAsync({ noteId, note });
    addToast({ message: 'Note updated.', type: 'success' });
  };

  const handleDeleteNote = async (noteId: string) => {
    await deleteNote.mutateAsync(noteId);
    addToast({ message: 'Note deleted.', type: 'success' });
  };

  const handleCompleteFollowUp = async (taskId: string) => {
    await completeFollowUp.mutateAsync({ id: taskId });
    addToast({ message: 'Follow-up completed.', type: 'success' });
  };

  const handleCancelFollowUp = async (taskId: string) => {
    await cancelFollowUp.mutateAsync({ id: taskId });
    addToast({ message: 'Follow-up cancelled.', type: 'success' });
  };

  const handleReschedule = async (scheduledAt: string, remarks: string) => {
    if (!reschedulingTask) return;
    await rescheduleFollowUp.mutateAsync({
      id: reschedulingTask.id,
      payload: { scheduled_at: scheduledAt, remarks: remarks || null },
    });
    addToast({ message: 'Follow-up rescheduled.', type: 'success' });
    setReschedulingTask(null);
  };

  /** Pulls every section on the page back in sync after an out-of-band change. */
  const refreshAll = () => {
    refetch();
    activities.refetch();
    notes.refetch();
    followUps.refetch();
    whatsapp.refetch();
  };

  // A lead that does not exist (or was soft-deleted) is a dead end — there is nothing on
  // this page to render around it, so the whole page becomes the error.
  if (isError) {
    return (
      <PageContainer>
        <ErrorState
          title="Lead not found"
          description="This lead could not be loaded. It may have been deleted, or you may not have access to it."
          onRetry={refetch}
          data-testid="lead-details-error"
        />
        <div className="flex justify-center pt-4">
          <Button variant="outline" onClick={() => navigate('/leads')}>
            <ArrowLeft className="h-4 w-4 mr-1.5" />
            Back to Leads
          </Button>
        </div>
      </PageContainer>
    );
  }

  return (
    <PageContainer data-testid="lead-details-page">
      <PageHeader
        title={lead?.business_name ?? 'Lead Details'}
        description={
          lead
            ? `${lead.phone}${lead.city ? ` · ${lead.city}` : ''}`
            : 'Loading this lead’s workspace…'
        }
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate('/leads')}
              data-testid="lead-details-back"
            >
              <ArrowLeft className="h-4 w-4 mr-1.5" />
              Back
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={refreshAll}
              data-testid="lead-details-refresh"
            >
              <RefreshCw className="h-4 w-4 mr-1.5" />
              Refresh
            </Button>
          </div>
        }
      />

      {/* Two columns on desktop: the working surface on the left, the action rail on the
          right. Collapses to a single column on tablet and below. */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 pt-6">
        <div className="lg:col-span-2 space-y-6">
          <LeadProfileCard
            lead={lead}
            assigneeName={assigneeName}
            isLoading={isLoading}
            onEdit={() => setIsEditOpen(true)}
          />

          <LeadActivityTimeline
            activities={activities.activities}
            total={activities.total}
            isLoading={activities.isLoading}
            isError={activities.isError}
            isEmpty={activities.isEmpty}
            hasMore={activities.hasMore}
            onLoadMore={activities.loadMore}
            onRetry={activities.refetch}
          />

          <div ref={notesRef}>
            <LeadNotesSection
              notes={notes.notes}
              total={notes.total}
              authorNames={notes.authorNames}
              isLoading={notes.isLoading}
              isError={notes.isError}
              isEmpty={notes.isEmpty}
              onCreate={handleCreateNote}
              onUpdate={handleUpdateNote}
              onDelete={handleDeleteNote}
              isMutating={
                createNote.isPending || updateNote.isPending || deleteNote.isPending
              }
              onRetry={notes.refetch}
              autoFocusComposer={noteFocusToken > 0}
            />
          </div>
        </div>

        <div className="space-y-6">
          <LeadStatusPanel
            lead={lead}
            onChangeStatus={handleStatusChange}
            isUpdating={statusMutation.isPending}
          />

          <LeadQuickActions
            lead={lead}
            onCreateFollowUp={() => setIsCreateFollowUpOpen(true)}
            onAddNote={handleAddNoteShortcut}
            onEditLead={() => setIsEditOpen(true)}
          />

          {canViewFollowUps && (
            <LeadFollowUpsSection
              followUps={followUps.followUps}
              total={followUps.total}
              overdueCount={followUps.overdueCount}
              assigneeNames={followUps.assigneeNames}
              isLoading={followUps.isLoading}
              isError={followUps.isError}
              isEmpty={followUps.isEmpty}
              onCreate={() => setIsCreateFollowUpOpen(true)}
              onComplete={handleCompleteFollowUp}
              onCancel={handleCancelFollowUp}
              onReschedule={setReschedulingTask}
              isMutating={
                completeFollowUp.isPending ||
                cancelFollowUp.isPending ||
                rescheduleFollowUp.isPending
              }
              onRetry={followUps.refetch}
            />
          )}

          {canViewWhatsApp && (
            <LeadWhatsAppHistory
              history={whatsapp.history}
              isLoading={whatsapp.isLoading}
              isError={whatsapp.isError}
              isEmpty={whatsapp.isEmpty}
              isSampled={whatsapp.isSampled}
              onRetry={whatsapp.refetch}
            />
          )}
        </div>
      </div>

      {/* Dialogs. Edit is mounted only with leads:update so the form cannot be opened at
          all by someone whose save would 403. */}
      {canUpdateLead && (
        <EditLeadDialog
          isOpen={isEditOpen}
          lead={lead}
          employees={employeesQuery.data ?? []}
          isSubmitting={updateLead.isPending}
          onClose={() => setIsEditOpen(false)}
          onConfirm={handleUpdateLead}
        />
      )}

      <CreateFollowUpDialog
        isOpen={isCreateFollowUpOpen}
        leadName={lead?.business_name}
        employees={employeesQuery.data ?? []}
        isSubmitting={createFollowUp.isPending}
        onClose={() => setIsCreateFollowUpOpen(false)}
        onConfirm={async (payload) => {
          await createFollowUp.mutateAsync(payload);
          addToast({ message: 'Follow-up created.', type: 'success' });
        }}
      />

      <RescheduleDialog
        isOpen={!!reschedulingTask}
        taskTitle={reschedulingTask?.title}
        currentScheduledAt={reschedulingTask?.scheduled_at}
        isSubmitting={rescheduleFollowUp.isPending}
        onClose={() => setReschedulingTask(null)}
        onConfirm={handleReschedule}
      />
    </PageContainer>
  );
};

export default LeadDetailsPage;
