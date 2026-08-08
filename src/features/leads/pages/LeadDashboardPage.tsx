/**
 * src/features/leads/pages/LeadDashboardPage.tsx
 *
 * The Lead CRM dashboard — the photographer-acquisition home screen.
 *
 * This page is deliberately thin. It calls the feature's hooks, gates each section on
 * the permission that section's data requires, and lays the widgets out; every
 * aggregation and join lives in `hooks.ts`, and every piece of markup is a widget from
 * `../components`. What is left here is composition and RBAC.
 *
 * Sections are gated individually rather than all-or-nothing so that, for example, an
 * employee with `leads:view` but not `whatsapp:view` still gets a useful dashboard
 * instead of a permission wall.
 */

import * as React from 'react';
import { PageContainer, PageHeader, Section } from '../../../components/ui/LayoutHelpers';
import { Button } from '../../../components/ui/Button';
import { useAuthStore, useNotificationStore } from '../../../app/store';
import { checkPermission } from '../../../components/auth/PermissionGuard';
import { LeadSummaryCards } from '../components/LeadSummaryCards';
import { RecentReplies } from '../components/RecentReplies';
import { TodaysFollowUps } from '../components/TodaysFollowUps';
import { RecentImports } from '../components/RecentImports';
import { CampaignSummary } from '../components/CampaignSummary';
import { QuickActions } from '../components/QuickActions';
import {
  CampaignPerformanceChart,
  DailyGrowthChart,
  LeadSourcesChart,
  LeadStatusChart,
} from '../components/LeadCharts';
import {
  useCampaignPerformance,
  useCampaignSummary,
  useCompleteFollowUp,
  useLeadCharts,
  useLeadSummary,
  useRecentImports,
  useRecentReplies,
  useRescheduleFollowUp,
  useTodaysFollowUps,
} from '../hooks';
import { RefreshCw } from 'lucide-react';

export const LeadDashboardPage = () => {
  const { permissions, user } = useAuthStore();
  const addToast = useNotificationStore((state) => state.addToast);

  const roleName = user?.role?.name;
  const canViewLeads = checkPermission(permissions, 'leads:view', roleName);
  const canViewFollowUps = checkPermission(permissions, 'followups:view', roleName);
  const canUpdateFollowUps = checkPermission(permissions, 'followups:update', roleName);
  const canViewWhatsApp = checkPermission(permissions, 'whatsapp:view', roleName);

  // ----- Data -----
  const summary = useLeadSummary();
  const replies = useRecentReplies();
  const followUps = useTodaysFollowUps();
  const imports = useRecentImports();
  const campaigns = useCampaignSummary();
  const charts = useLeadCharts();
  const campaignPerformance = useCampaignPerformance();

  // ----- Mutations -----
  const completeMutation = useCompleteFollowUp();
  const rescheduleMutation = useRescheduleFollowUp();

  // Which follow-up row is mid-flight, so only that row shows a spinner.
  const [pendingTaskId, setPendingTaskId] = React.useState<string | null>(null);

  const handleComplete = (taskId: string) => {
    setPendingTaskId(taskId);
    completeMutation.mutate(
      { id: taskId },
      {
        onSuccess: () => {
          addToast({ message: 'Follow-up marked as complete.', type: 'success' });
        },
        onError: () => {
          addToast({ message: 'Could not complete the follow-up. Please try again.', type: 'error' });
        },
        onSettled: () => setPendingTaskId(null),
      }
    );
  };

  const handleReschedule = (taskId: string, scheduledAt: string, remarks: string) => {
    setPendingTaskId(taskId);
    rescheduleMutation.mutate(
      { id: taskId, payload: { scheduled_at: scheduledAt, remarks: remarks || null } },
      {
        onSuccess: () => {
          addToast({ message: 'Follow-up rescheduled.', type: 'success' });
        },
        onError: () => {
          addToast({ message: 'Could not reschedule the follow-up. Please try again.', type: 'error' });
        },
        onSettled: () => setPendingTaskId(null),
      }
    );
  };

  const handleRefreshAll = () => {
    summary.refetch();
    replies.refetch();
    followUps.refetch();
    imports.refetch();
    campaigns.refetch();
    charts.refetch();
    campaignPerformance.refetch();
  };

  const isRefreshing = summary.isFetching;

  return (
    <PageContainer data-testid="lead-dashboard-page">
      <PageHeader
        title="Lead CRM Dashboard"
        description="Track photographer acquisition from first contact to conversion."
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefreshAll}
            leftIcon={<RefreshCw className="h-3.5 w-3.5" />}
            isLoading={isRefreshing}
            data-testid="dashboard-refresh"
          >
            Refresh
          </Button>
        }
      />

      {/* 6. Quick Actions — first, because they are what the page is usually opened to do.
             The component hides itself entirely when no action is permitted. */}
      <QuickActions />

      {/* 1. Lead Summary Cards */}
      {canViewLeads && (
        <Section title="Overview" data-testid="section-summary">
          <LeadSummaryCards
            counts={summary.counts}
            isLoading={summary.isLoading}
            isError={summary.isError}
            isEmpty={summary.isEmpty}
            onRetry={summary.refetch}
          />
        </Section>
      )}

      {/* 2 + 3. Replies and follow-ups sit side by side on desktop: they are the two
                 "what needs my attention now" lists and are read together. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {canViewWhatsApp && (
          <RecentReplies
            replies={replies.replies}
            isLoading={replies.isLoading}
            isError={replies.isError}
            isEmpty={replies.isEmpty}
            onRetry={replies.refetch}
          />
        )}

        {canViewFollowUps && (
          <TodaysFollowUps
            followUps={followUps.followUps}
            isLoading={followUps.isLoading}
            isError={followUps.isError}
            isEmpty={followUps.isEmpty}
            onRetry={followUps.refetch}
            onComplete={handleComplete}
            onReschedule={handleReschedule}
            pendingTaskId={pendingTaskId}
            canUpdate={canUpdateFollowUps}
          />
        )}
      </div>

      {/* 4 + 5. Operational history — imports and campaign funnels. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {canViewLeads && (
          <RecentImports
            imports={imports.imports}
            isLoading={imports.isLoading}
            isError={imports.isError}
            isEmpty={imports.isEmpty}
            onRetry={imports.refetch}
          />
        )}

        {canViewWhatsApp && (
          <CampaignSummary
            rows={campaigns.rows}
            isLoading={campaigns.isLoading}
            isError={campaigns.isError}
            isEmpty={campaigns.isEmpty}
            onRetry={campaigns.refetch}
          />
        )}
      </div>

      {/* 7. Charts */}
      <Section title="Analytics" data-testid="section-analytics">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {canViewLeads && (
            <>
              <LeadSourcesChart
                data={charts.sources}
                isSampled={charts.isSampled}
                isLoading={charts.isLoading}
                isError={charts.isError}
                isEmpty={charts.isEmpty}
                onRetry={charts.refetch}
              />
              <LeadStatusChart
                data={charts.statusDistribution}
                isSampled={charts.isSampled}
                isLoading={charts.isLoading}
                isError={charts.isError}
                isEmpty={charts.isEmpty}
                onRetry={charts.refetch}
              />
              <DailyGrowthChart
                data={charts.dailyGrowth}
                isLoading={charts.isLoading}
                isError={charts.isError}
                isEmpty={charts.isEmpty}
                onRetry={charts.refetch}
              />
            </>
          )}

          {canViewWhatsApp && (
            <CampaignPerformanceChart
              data={campaignPerformance.data}
              isLoading={campaignPerformance.isLoading}
              isError={campaignPerformance.isError}
              isEmpty={campaignPerformance.isEmpty}
              onRetry={campaignPerformance.refetch}
            />
          )}
        </div>
      </Section>
    </PageContainer>
  );
};

export default LeadDashboardPage;
