import * as React from 'react';
import { Badge, BadgeProps } from './Badge';

export type BadgeVariant = BadgeProps['variant'];

export type AllowedStatus =
  | 'pending'
  | 'approved'
  | 'completed'
  | 'cancelled'
  | 'failed'
  | 'processing'
  | 'active'
  | 'inactive'
  | 'draft';

export interface StatusBadgeProps extends Omit<BadgeProps, 'variant'> {
  status: AllowedStatus | string;
  variantOverride?: BadgeVariant;
}

export const statusMap: Record<AllowedStatus | string, BadgeVariant> = {
  pending: 'warning',
  approved: 'success',
  completed: 'success',
  cancelled: 'danger',
  failed: 'danger',
  processing: 'info',
  active: 'success',
  inactive: 'secondary',
  draft: 'secondary',
};

export const StatusBadge = React.forwardRef<HTMLSpanElement, StatusBadgeProps>(
  ({ status, variantOverride, className, children, ...props }, ref) => {
    const normalizedStatus = String(status).toLowerCase();
    const mappedVariant = statusMap[normalizedStatus] || 'default';
    const variant = variantOverride || mappedVariant;

    const displayLabel =
      children ||
      (typeof status === 'string'
        ? status.charAt(0).toUpperCase() + status.slice(1)
        : status);

    return (
      <Badge
        ref={ref}
        variant={variant}
        className={className}
        data-testid="status-badge"
        {...props}
      >
        {displayLabel}
      </Badge>
    );
  }
);

StatusBadge.displayName = 'StatusBadge';
