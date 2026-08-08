/**
 * src/features/leads/components/PipelineCard.tsx
 *
 * One lead, as a draggable card on the pipeline board.
 *
 * Drag-and-drop uses the native HTML5 drag API rather than a library. That is a deliberate
 * choice with a real trade-off: no library needed to be added, the card stays a plain
 * element that jsdom can exercise with ordinary `dragStart`/`drop` events (so the drag
 * behaviour is genuinely unit tested rather than mocked away), and keyboard users get the
 * explicit "Move to…" control below instead of a drag interaction they could never
 * perform. The cost is that HTML5 drag has no touch support, which is why the same
 * "Move to…" select is the primary path on small screens.
 *
 * The whole card is a link target — clicking it opens Lead Details — so every interactive
 * control inside it must stop propagation, or a quick action would navigate as well as
 * act. `stopCardNavigation` below is applied to each one.
 */

import * as React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Building2,
  CalendarClock,
  Clock,
  ExternalLink,
  MessageSquarePlus,
  Phone,
  PhoneCall,
  StickyNote,
  User,
} from 'lucide-react';
import dayjs from 'dayjs';
import { Badge } from '../../../components/ui/Badge';
import { Button } from '../../../components/ui/Button';
import PermissionGuard from '../../../components/auth/PermissionGuard';
import { LeadStatusBadge } from './LeadStatusBadge';
import { Lead, LeadStatus } from '../types';
import { isWhatsAppReady, whatsAppHref } from '../utils';
import { PIPELINE_COLUMNS, PIPELINE_DND_MIME } from '../pipelineUtils';

/** "GOOGLE_MAPS" -> "Google Maps". */
const humanize = (value: string): string =>
  value
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');

/**
 * A short relative time ("3d ago"), or an em dash when the timestamp is absent.
 *
 * Relative rather than absolute because the column is narrow and the question a card
 * answers is "how stale is this?", not "what was the date?".
 */
const relativeTime = (value: string | null | undefined): string => {
  if (!value) return '—';
  const parsed = dayjs(value);
  if (!parsed.isValid()) return '—';

  const diffMinutes = dayjs().diff(parsed, 'minute');
  if (diffMinutes < 1) return 'just now';
  if (diffMinutes < 60) return `${diffMinutes}m ago`;

  const diffHours = dayjs().diff(parsed, 'hour');
  if (diffHours < 24) return `${diffHours}h ago`;

  const diffDays = dayjs().diff(parsed, 'day');
  if (diffDays < 30) return `${diffDays}d ago`;
  return parsed.format('DD MMM YYYY');
};

/** Stops a control inside the card from also triggering the card's own navigation. */
const stopCardNavigation = (event: React.SyntheticEvent) => {
  event.stopPropagation();
};

export interface PipelineCardProps {
  lead: Lead;
  /** Display name of the assigned employee, already resolved by the board. */
  assigneeName: string | null;
  /** The lead's next open follow-up, if it has one. */
  followUpDueAt?: string | null;
  isDragging?: boolean;
  /** True while this card's own move is in flight, which dims it and blocks a re-drag. */
  isMoving?: boolean;
  onDragStart: (lead: Lead) => void;
  onDragEnd: () => void;
  onCreateFollowUp: (lead: Lead) => void;
  onAddNote: (lead: Lead) => void;
  /** Keyboard/touch alternative to dragging. */
  onMoveTo: (lead: Lead, status: LeadStatus) => void;
}

export const PipelineCard = ({
  lead,
  assigneeName,
  followUpDueAt,
  isDragging = false,
  isMoving = false,
  onDragStart,
  onDragEnd,
  onCreateFollowUp,
  onAddNote,
  onMoveTo,
}: PipelineCardProps) => {
  const navigate = useNavigate();
  const waHref = whatsAppHref(lead);

  const openLead = () => navigate(`/leads/${lead.id}`);

  const handleDragStart = (event: React.DragEvent<HTMLElement>) => {
    // The id goes on the dataTransfer so a drop can identify the card even though the
    // board also tracks it in state — belt and braces, and it makes the drag legible to
    // the browser's own drop targeting.
    event.dataTransfer.setData(PIPELINE_DND_MIME, lead.id);
    event.dataTransfer.effectAllowed = 'move';
    onDragStart(lead);
  };

  /** Enter/Space open the lead, matching what a click does. */
  const handleKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      openLead();
    }
  };

  const followUpLabel = followUpDueAt ? dayjs(followUpDueAt) : null;
  const isFollowUpOverdue = followUpLabel ? followUpLabel.isBefore(dayjs()) : false;

  return (
    <article
      draggable={!isMoving}
      onDragStart={handleDragStart}
      onDragEnd={onDragEnd}
      onClick={openLead}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={0}
      aria-label={`Lead ${lead.business_name}. Open details.`}
      data-testid={`pipeline-card-${lead.id}`}
      data-lead-id={lead.id}
      className={[
        'group w-full rounded-lg border border-border bg-card p-3 text-left shadow-sm',
        'cursor-grab active:cursor-grabbing transition-all',
        'hover:border-primary/40 hover:shadow-md',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
        isDragging ? 'opacity-40 ring-2 ring-primary' : '',
        isMoving ? 'opacity-60 pointer-events-none animate-pulse' : '',
      ].join(' ')}
    >
      {/* Business name + quick status badge */}
      <div className="flex items-start justify-between gap-2">
        <h4
          className="flex items-start gap-1.5 text-sm font-semibold leading-snug text-foreground line-clamp-2"
          title={lead.business_name}
        >
          <Building2 className="h-3.5 w-3.5 mt-0.5 shrink-0 text-muted-foreground" />
          {lead.business_name}
        </h4>
        <LeadStatusBadge status={lead.status} size="sm" className="shrink-0" />
      </div>

      {/* Phone */}
      <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
        <Phone className="h-3 w-3 shrink-0" />
        <span className="truncate">{lead.phone}</span>
      </p>

      {/* Lead source + WhatsApp readiness + assigned employee */}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <Badge variant="secondary" size="sm" data-testid="pipeline-card-source">
          {humanize(lead.source)}
        </Badge>
        {/*
          Marks the leads a WhatsApp campaign can actually reach. Driven by the `whatsapp`
          column alone — a lead with only an ordinary phone is not shown as ready, because
          nothing has confirmed that number is on WhatsApp.
        */}
        {isWhatsAppReady(lead) && (
          <Badge variant="success" size="sm" data-testid="pipeline-card-whatsapp-ready">
            WhatsApp
          </Badge>
        )}
        <span
          className="inline-flex max-w-full items-center gap-1 text-xs text-muted-foreground"
          data-testid="pipeline-card-assignee"
        >
          <User className="h-3 w-3 shrink-0" />
          <span className="truncate">{assigneeName ?? 'Unassigned'}</span>
        </span>
      </div>

      {/* Last contacted + follow-up due */}
      <dl className="mt-2 space-y-1 border-t border-border pt-2 text-xs">
        <div className="flex items-center justify-between gap-2">
          <dt className="flex items-center gap-1 text-muted-foreground">
            <Clock className="h-3 w-3 shrink-0" />
            Last contacted
          </dt>
          <dd className="font-medium text-foreground" data-testid="pipeline-card-last-contacted">
            {relativeTime(lead.last_contacted_at)}
          </dd>
        </div>

        {followUpLabel && (
          <div className="flex items-center justify-between gap-2">
            <dt className="flex items-center gap-1 text-muted-foreground">
              <CalendarClock className="h-3 w-3 shrink-0" />
              Follow-up due
            </dt>
            <dd
              className={
                isFollowUpOverdue
                  ? 'font-semibold text-destructive'
                  : 'font-medium text-foreground'
              }
              data-testid="pipeline-card-followup-due"
            >
              {followUpLabel.format('DD MMM, HH:mm')}
            </dd>
          </div>
        )}
      </dl>

      {/* Quick actions. Revealed on hover on pointer devices, always present for keyboard
          and touch (focus-within keeps them open while tabbing through them). */}
      <div
        className="mt-2 flex items-center gap-1 border-t border-border pt-2 opacity-100 sm:opacity-0 sm:transition-opacity sm:group-hover:opacity-100 sm:group-focus-within:opacity-100"
        data-testid="pipeline-card-actions"
      >
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-1.5"
          title="Open lead"
          aria-label={`Open ${lead.business_name}`}
          onClick={(event) => {
            stopCardNavigation(event);
            openLead();
          }}
          data-testid="pipeline-action-open"
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </Button>

        <PermissionGuard requiredPermission="whatsapp:create">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-1.5"
            title="Send WhatsApp"
            aria-label={`Send WhatsApp to ${lead.business_name}`}
            disabled={!waHref}
            onClick={(event) => {
              stopCardNavigation(event);
              if (waHref) window.open(waHref, '_blank', 'noopener,noreferrer');
            }}
            data-testid="pipeline-action-whatsapp"
          >
            <MessageSquarePlus className="h-3.5 w-3.5" />
          </Button>
        </PermissionGuard>

        <PermissionGuard requiredPermission="followups:create">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-1.5"
            title="Create follow-up"
            aria-label={`Create follow-up for ${lead.business_name}`}
            onClick={(event) => {
              stopCardNavigation(event);
              onCreateFollowUp(lead);
            }}
            data-testid="pipeline-action-followup"
          >
            <PhoneCall className="h-3.5 w-3.5" />
          </Button>
        </PermissionGuard>

        <PermissionGuard requiredPermission="leads:update">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-1.5"
            title="Add note"
            aria-label={`Add note to ${lead.business_name}`}
            onClick={(event) => {
              stopCardNavigation(event);
              onAddNote(lead);
            }}
            data-testid="pipeline-action-note"
          >
            <StickyNote className="h-3.5 w-3.5" />
          </Button>
        </PermissionGuard>

        {/* The accessible equivalent of dragging. Native drag cannot be performed by
            keyboard or touch at all, so without this the board's central interaction
            would be mouse-only. Gated on leads:update, exactly like the drop it mirrors. */}
        <PermissionGuard requiredPermission="leads:update">
          <select
            aria-label={`Move ${lead.business_name} to another status`}
            title="Move to…"
            value=""
            disabled={isMoving}
            onClick={stopCardNavigation}
            onChange={(event) => {
              const next = event.target.value as LeadStatus;
              event.target.value = '';
              if (next) onMoveTo(lead, next);
            }}
            className="ml-auto h-7 rounded-md border border-input bg-background px-1 text-xs text-muted-foreground hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            data-testid="pipeline-action-move"
          >
            <option value="">Move…</option>
            {PIPELINE_COLUMNS.filter((status) => status !== lead.status).map((status) => (
              <option key={status} value={status}>
                {humanize(status)}
              </option>
            ))}
          </select>
        </PermissionGuard>
      </div>
    </article>
  );
};
