/**
 * src/features/leads/components/QuickActions.tsx
 *
 * Section 6 — the four primary entry points into the CRM's daily work.
 *
 * Each tile declares the permission it needs and is hidden outright when the signed-in
 * employee lacks it, using the same `checkPermission` the router and sidebar use. Hiding
 * beats disabling here: a greyed-out "Import Leads" tile tells a viewer-role user nothing
 * actionable, and the grid reflows cleanly at any count.
 */

import { Link } from 'react-router-dom';
import { Card } from '../../../components/ui/Card';
import { useAuthStore } from '../../../app/store';
import { checkPermission } from '../../../components/auth/PermissionGuard';
import { cn } from '../../../utils/cn';
import { Upload, Send, Users, CalendarClock } from 'lucide-react';

interface QuickAction {
  label: string;
  description: string;
  to: string;
  icon: React.ComponentType<{ className?: string }>;
  permission: string;
  /** Tailwind classes for the icon chip, kept per-action so the four read as distinct. */
  accent: string;
}

const ACTIONS: QuickAction[] = [
  {
    label: 'Import Leads',
    description: 'Pull in new prospects',
    to: '/leads/import',
    icon: Upload,
    permission: 'leads:create',
    accent: 'bg-sky-50 text-sky-600 dark:bg-sky-950/40 dark:text-sky-400',
  },
  {
    label: 'Create Campaign',
    description: 'Start a WhatsApp blast',
    to: '/campaigns/new',
    icon: Send,
    permission: 'whatsapp:create',
    accent: 'bg-violet-50 text-violet-600 dark:bg-violet-950/40 dark:text-violet-400',
  },
  {
    label: 'View Leads',
    description: 'Browse the full pipeline',
    to: '/leads',
    icon: Users,
    permission: 'leads:view',
    accent: 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-400',
  },
  {
    label: "Today's Follow-ups",
    description: 'Work your due tasks',
    to: '/followups',
    icon: CalendarClock,
    permission: 'followups:view',
    accent: 'bg-amber-50 text-amber-600 dark:bg-amber-950/40 dark:text-amber-400',
  },
];

export const QuickActions = () => {
  const { permissions, user } = useAuthStore();

  const visibleActions = ACTIONS.filter((action) =>
    checkPermission(permissions, action.permission, user?.role?.name)
  );

  // With no permitted actions the section would render as an empty strip; omit it.
  if (visibleActions.length === 0) {
    return null;
  }

  return (
    <div
      className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"
      data-testid="quick-actions"
    >
      {visibleActions.map((action) => {
        const Icon = action.icon;

        return (
          <Link
            key={action.label}
            to={action.to}
            className="rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            data-testid={`quick-action-${action.permission.split(':')[0]}-${action.label
              .toLowerCase()
              .replace(/[^a-z]+/g, '-')
              .replace(/^-|-$/g, '')}`}
          >
            <Card className="h-full p-4 flex items-center gap-3 transition-all hover:shadow-md hover:border-primary/40">
              <span className={cn('p-2.5 rounded-lg shrink-0', action.accent)}>
                <Icon className="h-5 w-5" />
              </span>
              <span className="min-w-0">
                <span className="block font-semibold text-sm text-foreground truncate">
                  {action.label}
                </span>
                <span className="block text-xs text-muted-foreground truncate">
                  {action.description}
                </span>
              </span>
            </Card>
          </Link>
        );
      })}
    </div>
  );
};
