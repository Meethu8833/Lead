/**
 * src/features/leads/components/LeadStatusBadge.tsx
 *
 * Renders a lead / follow-up / import / campaign status as a coloured pill.
 *
 * The shared `StatusBadge` maps only generic statuses (pending, completed, failed…) and
 * would fall through to the default variant for every CRM-specific one, so this wraps it
 * with the domain's own colour semantics while still delegating the actual rendering.
 */

import { Badge, BadgeProps } from '../../../components/ui/Badge';
import { LeadStatus } from '../types';

type Variant = BadgeProps['variant'];

/**
 * Colour semantics: progress toward a sale is green, active engagement is blue,
 * attention-needed is amber, and dead ends are red.
 */
const STATUS_VARIANTS: Record<string, Variant> = {
  // Lead lifecycle
  NEW: 'info',
  CONTACTED: 'secondary',
  MESSAGE_SENT: 'secondary',
  REPLIED: 'info',
  INTERESTED: 'success',
  FOLLOW_UP: 'warning',
  NEGOTIATION: 'warning',
  CONVERTED: 'success',
  LOST: 'danger',
  // Follow-up task lifecycle
  PENDING: 'warning',
  COMPLETED: 'success',
  CANCELLED: 'secondary',
  OVERDUE: 'danger',
  // Import job lifecycle
  RUNNING: 'info',
  PARTIAL: 'warning',
  FAILED: 'danger',
  // Campaign lifecycle
  DRAFT: 'secondary',
  SCHEDULED: 'info',
  PAUSED: 'warning',
};

/** Turns MESSAGE_SENT into "Message Sent" for display. */
export const humanizeStatus = (status: string): string =>
  status
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');

export interface LeadStatusBadgeProps {
  status: LeadStatus | string | null | undefined;
  size?: BadgeProps['size'];
  className?: string;
}

export const LeadStatusBadge = ({ status, size = 'sm', className }: LeadStatusBadgeProps) => {
  if (!status) {
    return (
      <Badge variant="secondary" size={size} className={className} data-testid="lead-status-badge">
        Unknown
      </Badge>
    );
  }

  const key = String(status).toUpperCase();

  return (
    <Badge
      variant={STATUS_VARIANTS[key] ?? 'default'}
      size={size}
      className={className}
      data-testid="lead-status-badge"
    >
      {humanizeStatus(String(status))}
    </Badge>
  );
};
