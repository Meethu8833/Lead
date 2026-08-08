/**
 * src/features/leads/components/LeadProfileCard.tsx
 *
 * The lead's identity, contact channels and location — the top-left panel of the Lead
 * Details workspace.
 *
 * Every field on a lead except `business_name`, `phone`, `source` and `status` is
 * nullable, so the card renders a field only when it has a value rather than showing a
 * grid half-full of dashes. The one exception is the block of always-meaningful metadata
 * (source, status, assignee, created, last contacted, converted), which reads as a fixed
 * summary and so always renders, saying "Unassigned" / "Never contacted" when empty.
 */

import * as React from 'react';
import dayjs from 'dayjs';
import {
  AtSign,
  Building2,
  Calendar,
  CheckCircle2,
  Clock,
  ExternalLink,
  Facebook,
  Globe,
  Mail,
  MapPin,
  MessageCircle,
  Pencil,
  Phone,
  Tag,
  User,
  UserCircle,
  Youtube,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../../../components/ui/Card';
import { Button } from '../../../components/ui/Button';
import { Badge } from '../../../components/ui/Badge';
import { Skeleton } from '../../../components/ui/Skeleton';
import PermissionGuard from '../../../components/auth/PermissionGuard';
import { LeadStatusBadge, humanizeStatus } from './LeadStatusBadge';
import { Lead } from '../types';
import {
  externalHref,
  formatAddress,
  instagramHref,
  mailtoHref,
  mapsUrlFor,
  telHref,
  whatsAppHref,
} from '../utils';

/** One label/value row. `href` turns the value into a link; omit it for plain text. */
interface FieldProps {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  href?: string | null;
  testId: string;
}

const ProfileField = ({ icon, label, value, href, testId }: FieldProps) => (
  <div className="flex items-start gap-3 py-2" data-testid={testId}>
    <span className="text-muted-foreground shrink-0 mt-0.5">{icon}</span>
    <div className="min-w-0 flex-1">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="text-sm text-foreground break-words">
        {href ? (
          <a
            href={href}
            target={href.startsWith('http') ? '_blank' : undefined}
            rel={href.startsWith('http') ? 'noopener noreferrer' : undefined}
            className="inline-flex items-center gap-1 text-primary hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-sm"
          >
            <span className="break-all">{value}</span>
            {href.startsWith('http') && <ExternalLink className="h-3 w-3 shrink-0" />}
          </a>
        ) : (
          value
        )}
      </dd>
    </div>
  </div>
);

export interface LeadProfileCardProps {
  lead: Lead | null;
  assigneeName: string | null;
  isLoading?: boolean;
  onEdit?: () => void;
}

export const LeadProfileCard = ({
  lead,
  assigneeName,
  isLoading = false,
  onEdit,
}: LeadProfileCardProps) => {
  if (isLoading || !lead) {
    return (
      <Card data-testid="lead-profile-loading">
        <CardHeader className="pb-4">
          <Skeleton className="h-6 w-1/2" />
        </CardHeader>
        <CardContent className="space-y-4">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={index} className="flex items-center gap-3">
              <Skeleton className="h-8 w-8 rounded-full shrink-0" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-3 w-1/4" />
                <Skeleton className="h-3.5 w-2/3" />
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    );
  }

  const address = formatAddress(lead);
  const mapsUrl = mapsUrlFor(lead);

  return (
    <Card data-testid="lead-profile">
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0 pb-4">
        <div className="min-w-0 space-y-1.5">
          <CardTitle
            className="text-lg font-semibold flex items-center gap-2"
            data-testid="lead-profile-business-name"
          >
            <Building2 className="h-4 w-4 text-muted-foreground shrink-0" />
            <span className="truncate">{lead.business_name}</span>
          </CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            <LeadStatusBadge status={lead.status} />
            {lead.is_converted && (
              <Badge variant="success" size="sm" data-testid="lead-profile-converted">
                Converted
              </Badge>
            )}
          </div>
        </div>

        {/* Hidden entirely without leads:update — the dialog it opens would 403 anyway. */}
        <PermissionGuard requiredPermission="leads:update">
          <Button
            variant="outline"
            size="sm"
            onClick={onEdit}
            className="shrink-0"
            data-testid="lead-profile-edit"
          >
            <Pencil className="h-3.5 w-3.5 mr-1.5" />
            Edit Lead
          </Button>
        </PermissionGuard>
      </CardHeader>

      <CardContent>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 divide-y divide-border sm:divide-y-0">
          {lead.contact_person && (
            <ProfileField
              icon={<User className="h-4 w-4" />}
              label="Contact Person"
              value={lead.contact_person}
              testId="lead-field-contact-person"
            />
          )}

          <ProfileField
            icon={<Phone className="h-4 w-4" />}
            label="Phone"
            value={lead.phone}
            href={telHref(lead.phone)}
            testId="lead-field-phone"
          />

          {lead.whatsapp && (
            <ProfileField
              icon={<MessageCircle className="h-4 w-4" />}
              label="WhatsApp"
              value={lead.whatsapp}
              href={whatsAppHref(lead)}
              testId="lead-field-whatsapp"
            />
          )}

          {lead.email && (
            <ProfileField
              icon={<Mail className="h-4 w-4" />}
              label="Email"
              value={lead.email}
              href={mailtoHref(lead.email)}
              testId="lead-field-email"
            />
          )}

          {lead.website && (
            <ProfileField
              icon={<Globe className="h-4 w-4" />}
              label="Website"
              value={lead.website}
              href={externalHref(lead.website)}
              testId="lead-field-website"
            />
          )}

          {lead.instagram && (
            <ProfileField
              icon={<AtSign className="h-4 w-4" />}
              label="Instagram"
              value={lead.instagram}
              href={instagramHref(lead.instagram)}
              testId="lead-field-instagram"
            />
          )}

          {/*
            Social links collected from the business's own website by the contact extractor.
            Each is rendered only when stored, so the card never shows a link that goes
            nowhere. The platforms themselves are never scraped — these URLs were published
            by the business on its own site.
          */}
          {lead.facebook && (
            <ProfileField
              icon={<Facebook className="h-4 w-4" />}
              label="Facebook"
              value={lead.facebook}
              href={externalHref(lead.facebook)}
              testId="lead-field-facebook"
            />
          )}

          {lead.youtube && (
            <ProfileField
              icon={<Youtube className="h-4 w-4" />}
              label="YouTube"
              value={lead.youtube}
              href={externalHref(lead.youtube)}
              testId="lead-field-youtube"
            />
          )}

          {/* Derived from lat/long — see mapsUrlFor(). Absent for leads without coordinates. */}
          {mapsUrl && (
            <ProfileField
              icon={<MapPin className="h-4 w-4" />}
              label="Google Maps"
              value="View on Google Maps"
              href={mapsUrl}
              testId="lead-field-maps"
            />
          )}

          {address && (
            <ProfileField
              icon={<MapPin className="h-4 w-4" />}
              label="Address"
              value={address}
              testId="lead-field-address"
            />
          )}

          {lead.city && (
            <ProfileField
              icon={<MapPin className="h-4 w-4" />}
              label="City"
              value={lead.city}
              testId="lead-field-city"
            />
          )}

          {lead.district && (
            <ProfileField
              icon={<MapPin className="h-4 w-4" />}
              label="District"
              value={lead.district}
              testId="lead-field-district"
            />
          )}

          {lead.state && (
            <ProfileField
              icon={<MapPin className="h-4 w-4" />}
              label="State"
              value={lead.state}
              testId="lead-field-state"
            />
          )}

          <ProfileField
            icon={<Tag className="h-4 w-4" />}
            label="Lead Source"
            value={humanizeStatus(lead.source)}
            testId="lead-field-source"
          />

          <ProfileField
            icon={<Tag className="h-4 w-4" />}
            label="Current Status"
            value={<LeadStatusBadge status={lead.status} />}
            testId="lead-field-status"
          />

          <ProfileField
            icon={<UserCircle className="h-4 w-4" />}
            label="Assigned Employee"
            value={assigneeName ?? <span className="text-muted-foreground">Unassigned</span>}
            testId="lead-field-assignee"
          />

          <ProfileField
            icon={<Calendar className="h-4 w-4" />}
            label="Created Date"
            value={dayjs(lead.created_at).format('DD MMM YYYY, h:mm A')}
            testId="lead-field-created"
          />

          <ProfileField
            icon={<Clock className="h-4 w-4" />}
            label="Last Contacted"
            value={
              lead.last_contacted_at ? (
                dayjs(lead.last_contacted_at).format('DD MMM YYYY, h:mm A')
              ) : (
                <span className="text-muted-foreground">Never contacted</span>
              )
            }
            testId="lead-field-last-contacted"
          />

          <ProfileField
            icon={<CheckCircle2 className="h-4 w-4" />}
            label="Converted"
            value={lead.is_converted ? 'Yes' : 'No'}
            testId="lead-field-converted"
          />

          {lead.remarks && (
            <div className="sm:col-span-2 pt-2" data-testid="lead-field-remarks">
              <dt className="text-xs font-medium text-muted-foreground">Remarks</dt>
              <dd className="text-sm text-foreground whitespace-pre-wrap mt-1">{lead.remarks}</dd>
            </div>
          )}
        </dl>
        {!address && !lead.city && !lead.district && !lead.state && (
          <p className="text-xs text-muted-foreground pt-3" data-testid="lead-field-no-location">
            No location recorded for this lead.
          </p>
        )}
      </CardContent>
    </Card>
  );
};
