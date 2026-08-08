/**
 * src/features/leads/components/LeadQuickActions.tsx
 *
 * The action rail for a single lead: the seven things a caller does most often, without
 * scrolling to find the section that owns each one.
 *
 * Actions split into two kinds, and the distinction drives the RBAC treatment:
 *
 *  - **Local** (Copy Phone, Open WhatsApp, Call Now) touch no API and need no permission.
 *    They are available to anyone who can see the lead at all.
 *  - **Mutating** (Send WhatsApp, Create Follow-up, Add Note, Edit Lead) each open the
 *    section that performs them, and are wrapped in the permission that section's endpoint
 *    enforces — `whatsapp:create`, `followups:create` and `leads:update` respectively.
 *    Hiding them client-side mirrors the server rather than replacing it.
 *
 * "Send WhatsApp" deserves a note: there is no per-lead send endpoint (the backend
 * dispatches WhatsApp per *campaign*, via POST /whatsapp/campaigns/{id}/start), so this
 * opens the lead's wa.me conversation rather than pretending a one-off API send exists.
 */

import * as React from 'react';
import { Check, Copy, MessageCircle, MessageSquarePlus, Pencil, Phone, PhoneCall, StickyNote } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../../../components/ui/Card';
import { Button } from '../../../components/ui/Button';
import PermissionGuard from '../../../components/auth/PermissionGuard';
import { Lead } from '../types';
import { telHref, whatsAppHref, normalizePhone } from '../utils';

export interface LeadQuickActionsProps {
  lead: Lead | null;
  onCreateFollowUp: () => void;
  onAddNote: () => void;
  onEditLead: () => void;
}

export const LeadQuickActions = ({
  lead,
  onCreateFollowUp,
  onAddNote,
  onEditLead,
}: LeadQuickActionsProps) => {
  const [copied, setCopied] = React.useState(false);

  // Clears the "Copied" confirmation, and cancels on unmount so a copy immediately before
  // navigating away does not set state on an unmounted component.
  React.useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  if (!lead) return null;

  const waHref = whatsAppHref(lead);
  const callHref = telHref(lead.phone);

  const handleCopyPhone = async () => {
    const phone = normalizePhone(lead.phone) || lead.phone;
    try {
      await navigator.clipboard.writeText(phone);
      setCopied(true);
    } catch {
      // clipboard is unavailable over plain HTTP and in some embedded webviews. Failing
      // silently is right here: the number is already visible in the profile above.
      setCopied(false);
    }
  };

  return (
    <Card data-testid="lead-quick-actions">
      <CardHeader className="pb-3">
        <CardTitle className="text-base font-semibold">Quick Actions</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-1 gap-2">
        <PermissionGuard requiredPermission="whatsapp:create">
          <Button
            variant="primary"
            size="sm"
            fullWidth
            disabled={!waHref}
            onClick={() => waHref && window.open(waHref, '_blank', 'noopener,noreferrer')}
            data-testid="quick-action-send-whatsapp"
          >
            <MessageSquarePlus className="h-3.5 w-3.5 mr-1.5" />
            Send WhatsApp
          </Button>
        </PermissionGuard>

        <PermissionGuard requiredPermission="followups:create">
          <Button
            variant="outline"
            size="sm"
            fullWidth
            onClick={onCreateFollowUp}
            data-testid="quick-action-create-followup"
          >
            <PhoneCall className="h-3.5 w-3.5 mr-1.5" />
            Create Follow-up
          </Button>
        </PermissionGuard>

        <PermissionGuard requiredPermission="leads:update">
          <Button
            variant="outline"
            size="sm"
            fullWidth
            onClick={onAddNote}
            data-testid="quick-action-add-note"
          >
            <StickyNote className="h-3.5 w-3.5 mr-1.5" />
            Add Note
          </Button>
        </PermissionGuard>

        <PermissionGuard requiredPermission="leads:update">
          <Button
            variant="outline"
            size="sm"
            fullWidth
            onClick={onEditLead}
            data-testid="quick-action-edit-lead"
          >
            <Pencil className="h-3.5 w-3.5 mr-1.5" />
            Edit Lead
          </Button>
        </PermissionGuard>

        {/* Local actions below — no API call, so no permission gate. */}
        <Button
          variant="ghost"
          size="sm"
          fullWidth
          onClick={handleCopyPhone}
          data-testid="quick-action-copy-phone"
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 mr-1.5 text-emerald-500" />
          ) : (
            <Copy className="h-3.5 w-3.5 mr-1.5" />
          )}
          {copied ? 'Copied!' : 'Copy Phone'}
        </Button>

        <Button
          variant="ghost"
          size="sm"
          fullWidth
          disabled={!waHref}
          onClick={() => waHref && window.open(waHref, '_blank', 'noopener,noreferrer')}
          data-testid="quick-action-open-whatsapp"
        >
          <MessageCircle className="h-3.5 w-3.5 mr-1.5" />
          Open WhatsApp
        </Button>

        <Button
          variant="ghost"
          size="sm"
          fullWidth
          disabled={!callHref}
          onClick={() => callHref && (window.location.href = callHref)}
          data-testid="quick-action-call-now"
        >
          <Phone className="h-3.5 w-3.5 mr-1.5" />
          Call Now
        </Button>
      </CardContent>
    </Card>
  );
};
