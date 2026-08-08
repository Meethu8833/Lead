/**
 * src/features/leads/components/LeadStatusPanel.tsx
 *
 * Moves a lead through its CRM lifecycle.
 *
 * The panel is deliberately two-step — pick a status, then confirm — because a status
 * change is not a local UI preference: it writes a STATUS_CHANGED entry to the immutable
 * activity timeline and moves the lead between the dashboard's pipeline counters. A
 * mis-click on a dropdown should not be able to do that silently.
 *
 * `version` is sent with the update so a change issued from a page left open while
 * someone else edited the lead fails with a 409 VERSION_CONFLICT instead of silently
 * overwriting them.
 */

import * as React from 'react';
import { AlertCircle, ArrowRight } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../../../components/ui/Card';
import { Button } from '../../../components/ui/Button';
import { Select } from '../../../components/ui/Select';
import { ConfirmationDialog } from '../../../components/ui/ConfirmationDialog';
import PermissionGuard from '../../../components/auth/PermissionGuard';
import { LeadStatusBadge, humanizeStatus } from './LeadStatusBadge';
import { Lead, LeadStatus } from '../types';

/** Every lifecycle status, in pipeline order. Mirrors LeadStatus in app/models/lead.py. */
export const LEAD_STATUS_OPTIONS: LeadStatus[] = [
  'NEW',
  'CONTACTED',
  'MESSAGE_SENT',
  'REPLIED',
  'INTERESTED',
  'FOLLOW_UP',
  'NEGOTIATION',
  'CONVERTED',
  'LOST',
];

export interface LeadStatusPanelProps {
  lead: Lead | null;
  onChangeStatus: (status: LeadStatus, version?: number) => Promise<unknown>;
  isUpdating?: boolean;
}

export const LeadStatusPanel = ({
  lead,
  onChangeStatus,
  isUpdating = false,
}: LeadStatusPanelProps) => {
  const [pendingStatus, setPendingStatus] = React.useState<LeadStatus | ''>('');
  const [isConfirmOpen, setIsConfirmOpen] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  if (!lead) return null;

  const handleConfirm = async () => {
    if (!pendingStatus) return;
    setError(null);
    try {
      await onChangeStatus(pendingStatus as LeadStatus, lead.version);
      setIsConfirmOpen(false);
      setPendingStatus('');
    } catch (err) {
      // Kept open on failure so the chosen status is not lost. A 409 here means someone
      // else changed the lead first and the page needs reloading.
      const status = (err as { response?: { status?: number } })?.response?.status;
      setError(
        status === 409
          ? 'This lead was changed by someone else. Reload the page and try again.'
          : 'Could not update the status. Please try again.'
      );
      setIsConfirmOpen(false);
    }
  };

  return (
    <PermissionGuard requiredPermission="leads:update">
      <Card data-testid="lead-status-panel">
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-semibold">Lead Status</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">Current:</span>
            <LeadStatusBadge status={lead.status} />
          </div>

          <Select
            label="Change status to"
            placeholder="Select a status…"
            value={pendingStatus}
            onChange={(event) => {
              setPendingStatus(event.target.value as LeadStatus);
              setError(null);
            }}
            options={LEAD_STATUS_OPTIONS.filter((status) => status !== lead.status).map(
              (status) => ({ label: humanizeStatus(status), value: status })
            )}
            fullWidth
            disabled={isUpdating}
            data-testid="lead-status-select"
          />

          {error && (
            <p
              className="flex items-start gap-1.5 text-xs text-destructive"
              role="alert"
              data-testid="lead-status-error"
            >
              <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              {error}
            </p>
          )}

          <Button
            variant="primary"
            size="sm"
            fullWidth
            disabled={!pendingStatus || isUpdating}
            isLoading={isUpdating}
            onClick={() => setIsConfirmOpen(true)}
            data-testid="lead-status-apply"
          >
            Update Status
            <ArrowRight className="h-3.5 w-3.5 ml-1.5" />
          </Button>
        </CardContent>
      </Card>

      <ConfirmationDialog
        isOpen={isConfirmOpen}
        title="Change lead status?"
        description={
          pendingStatus
            ? `This will move "${lead.business_name}" from ${humanizeStatus(
                lead.status
              )} to ${humanizeStatus(pendingStatus)} and record the change on the lead's timeline.`
            : ''
        }
        confirmText="Change Status"
        variant="warning"
        isLoading={isUpdating}
        onConfirm={handleConfirm}
        onCancel={() => setIsConfirmOpen(false)}
      />
    </PermissionGuard>
  );
};
