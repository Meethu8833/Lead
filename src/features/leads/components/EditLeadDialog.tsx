/**
 * src/features/leads/components/EditLeadDialog.tsx
 *
 * The Edit Lead form, covering every client-editable field on the profile.
 *
 * Two fields on the profile are deliberately absent:
 *  - **Status** is owned by the Status Panel, which confirms before changing it because a
 *    status change writes to the immutable timeline. Duplicating it here would create a
 *    second, unconfirmed path to the same effect.
 *  - **Last Contacted** is maintained server-side by the WhatsApp module and is not part
 *    of `LeadUpdate` at all.
 *
 * The submitted payload contains only fields that actually changed, plus `version`.
 * Sending the whole form would make every save a full overwrite and would turn any
 * concurrent edit into silent data loss even when the two edits touched different fields.
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
import { Input } from '../../../components/ui/Input';
import { Select } from '../../../components/ui/Select';
import { Textarea } from '../../../components/ui/Textarea';
import { humanizeStatus } from './LeadStatusBadge';
import { EmployeeSummary, Lead, LeadSource, LeadUpdatePayload } from '../types';

const LEAD_SOURCES: LeadSource[] = [
  'MANUAL',
  'GOOGLE_MAPS',
  'INSTAGRAM',
  'FACEBOOK',
  'JUSTDIAL',
  'REFERRAL',
  'CSV_IMPORT',
  'OTHER',
];

/** The editable text fields, so the form state and the diff stay in one list. */
const TEXT_FIELDS = [
  'business_name',
  'contact_person',
  'phone',
  'whatsapp',
  'email',
  'website',
  'instagram',
  'facebook',
  'youtube',
  'address',
  'city',
  'district',
  'state',
  'country',
  'remarks',
] as const;

type TextField = (typeof TEXT_FIELDS)[number];

type FormState = Record<TextField, string> & {
  source: LeadSource;
  assigned_employee_id: string;
};

const toFormState = (lead: Lead): FormState => {
  const state = {} as FormState;
  TEXT_FIELDS.forEach((field) => {
    state[field] = lead[field] ?? '';
  });
  state.source = lead.source;
  state.assigned_employee_id = lead.assigned_employee_id ?? '';
  return state;
};

export interface EditLeadDialogProps {
  isOpen: boolean;
  lead: Lead | null;
  employees: EmployeeSummary[];
  isSubmitting?: boolean;
  onClose: () => void;
  onConfirm: (payload: LeadUpdatePayload) => Promise<unknown>;
}

export const EditLeadDialog = ({
  isOpen,
  lead,
  employees,
  isSubmitting = false,
  onClose,
  onConfirm,
}: EditLeadDialogProps) => {
  const [form, setForm] = React.useState<FormState | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  // Re-seed whenever the dialog opens or the underlying lead changes, so the form never
  // shows a stale snapshot after a save elsewhere on the page.
  React.useEffect(() => {
    if (isOpen && lead) {
      setForm(toFormState(lead));
      setError(null);
    }
  }, [isOpen, lead]);

  if (!lead || !form) return null;

  const setField = (field: keyof FormState) => (value: string) =>
    setForm((current) => (current ? { ...current, [field]: value } : current));

  const handleConfirm = async () => {
    // Mirrors the backend's required-field validation so the obvious mistakes never cost
    // a round trip.
    if (!form.business_name.trim()) {
      setError('Business name is required.');
      return;
    }
    if (!form.phone.trim()) {
      setError('Phone is required.');
      return;
    }

    const payload: LeadUpdatePayload = { version: lead.version };

    TEXT_FIELDS.forEach((field) => {
      const next = form[field].trim();
      const current = lead[field] ?? '';
      if (next === current) return;
      // Clearing an optional field must send null, not "": the column is nullable and the
      // backend's URL/email validators reject an empty string.
      (payload as Record<string, unknown>)[field] = next === '' ? null : next;
    });

    if (form.source !== lead.source) payload.source = form.source;

    const nextAssignee = form.assigned_employee_id || null;
    if (nextAssignee !== (lead.assigned_employee_id ?? null)) {
      payload.assigned_employee_id = nextAssignee;
    }

    // Only `version` present means nothing changed — close rather than issue a no-op PUT
    // that would still bump the version and invalidate everyone else's open page.
    if (Object.keys(payload).length === 1) {
      onClose();
      return;
    }

    setError(null);
    try {
      await onConfirm(payload);
      onClose();
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      setError(
        status === 409
          ? 'This lead was changed by someone else. Close and reopen the form to get the latest values.'
          : status === 400
            ? 'Some values were rejected. Check the phone, email and URL formats.'
            : 'Could not save the lead. Please try again.'
      );
    }
  };

  const field = (name: TextField, label: string, props: Record<string, unknown> = {}) => (
    <Input
      label={label}
      value={form[name]}
      onChange={(event: React.ChangeEvent<HTMLInputElement>) => setField(name)(event.target.value)}
      disabled={isSubmitting}
      fullWidth
      data-testid={`edit-lead-${name.replace(/_/g, '-')}`}
      {...props}
    />
  );

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && !isSubmitting && onClose()}>
      <DialogContent size="xl" data-testid="edit-lead-dialog">
        <DialogHeader>
          <DialogTitle>Edit lead</DialogTitle>
          <DialogDescription>
            Update this lead&apos;s details. Use the Status panel to change its lifecycle status.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {field('business_name', 'Business Name', { required: true, maxLength: 255 })}
            {field('contact_person', 'Contact Person', { maxLength: 255 })}
            {field('phone', 'Phone', { required: true, type: 'tel' })}
            {field('whatsapp', 'WhatsApp', { type: 'tel' })}
            {field('email', 'Email', { type: 'email' })}
            {field('website', 'Website', { placeholder: 'https://example.com' })}
            {field('instagram', 'Instagram', { placeholder: '@handle' })}
            {field('facebook', 'Facebook')}
            {field('youtube', 'YouTube')}
            {field('city', 'City')}
            {field('district', 'District')}
            {field('state', 'State')}
            {field('country', 'Country')}

            <Select
              label="Lead Source"
              value={form.source}
              onChange={(event) => setField('source')(event.target.value)}
              options={LEAD_SOURCES.map((source) => ({
                label: humanizeStatus(source),
                value: source,
              }))}
              disabled={isSubmitting}
              fullWidth
              data-testid="edit-lead-source"
            />

            {/* "Unassigned" is a real option rather than `placeholder`, which Select
                renders as `disabled hidden` and so cannot be re-selected. */}
            <Select
              label="Assigned Employee"
              value={form.assigned_employee_id}
              onChange={(event) => setField('assigned_employee_id')(event.target.value)}
              options={[
                { label: 'Unassigned', value: '' },
                ...employees.map((employee) => ({
                  label: employee.full_name ?? employee.name ?? employee.email ?? employee.id,
                  value: employee.id,
                })),
              ]}
              disabled={isSubmitting}
              fullWidth
              data-testid="edit-lead-assignee"
            />
          </div>

          <Textarea
            label="Address"
            rows={2}
            value={form.address}
            onChange={(event) => setField('address')(event.target.value)}
            disabled={isSubmitting}
            fullWidth
            data-testid="edit-lead-address"
          />

          <Textarea
            label="Remarks"
            rows={3}
            value={form.remarks}
            onChange={(event) => setField('remarks')(event.target.value)}
            maxLength={10000}
            disabled={isSubmitting}
            fullWidth
            data-testid="edit-lead-remarks"
          />

          {error && (
            <p className="text-xs text-destructive" role="alert" data-testid="edit-lead-error">
              {error}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={onClose}
            disabled={isSubmitting}
            data-testid="edit-lead-cancel"
          >
            Cancel
          </Button>
          <Button onClick={handleConfirm} isLoading={isSubmitting} data-testid="edit-lead-submit">
            Save Changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
