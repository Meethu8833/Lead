/**
 * src/features/leads/components/LeadCharts.tsx
 *
 * Section 7 — the four analytics charts.
 *
 * All four share `DashboardSection` so their loading / empty / error states match the
 * rest of the page, and all four take pre-aggregated data: no chart computes anything,
 * which keeps the aggregation logic in `useLeadCharts` where it can be tested without
 * mounting a chart.
 *
 * A note on colour: one shared categorical palette is used across every chart so the same
 * series never changes colour between panels, and each hue was picked to stay legible on
 * both light and dark backgrounds.
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import dayjs from 'dayjs';
import { DashboardSection } from './DashboardSection';
import { humanizeStatus } from './LeadStatusBadge';
import { CampaignPerformanceDatum, ChartDatum, DailyGrowthDatum } from '../types';
import { BarChart3, LineChart as LineChartIcon, PieChart as PieChartIcon, Activity } from 'lucide-react';

/** Shared categorical palette — readable against both themes. */
const PALETTE = [
  '#0ea5e9', // sky-500
  '#10b981', // emerald-500
  '#8b5cf6', // violet-500
  '#f59e0b', // amber-500
  '#ec4899', // pink-500
  '#14b8a6', // teal-500
  '#6366f1', // indigo-500
  '#f43f5e', // rose-500
  '#84cc16', // lime-500
];

const AXIS_STYLE = { fontSize: 11, fill: 'currentColor' };

/** Tooltip chrome that reads correctly in dark mode, where the default white box does not. */
const TOOLTIP_STYLE = {
  contentStyle: {
    backgroundColor: 'hsl(var(--card, 0 0% 100%))',
    border: '1px solid hsl(var(--border, 240 5.9% 90%))',
    borderRadius: '0.5rem',
    fontSize: '12px',
  },
} as const;

interface BaseChartProps {
  isLoading?: boolean;
  isError?: boolean;
  isEmpty?: boolean;
  onRetry?: () => void;
}

// ==========================================
// 7a. LEAD SOURCES
// ==========================================

export interface LeadSourcesChartProps extends BaseChartProps {
  data: ChartDatum[];
  /** True when the underlying sample was truncated; surfaced as a footnote. */
  isSampled?: boolean;
}

export const LeadSourcesChart = ({
  data,
  isSampled = false,
  isLoading,
  isError,
  isEmpty,
  onRetry,
}: LeadSourcesChartProps) => (
  <DashboardSection
    title="Lead Sources"
    description={
      isSampled ? 'Where your leads come from (most recent 500)' : 'Where your leads come from'
    }
    icon={<PieChartIcon className="h-4 w-4" />}
    isLoading={isLoading}
    isError={isError}
    isEmpty={isEmpty}
    emptyTitle="No source data"
    emptyDescription="Once leads are imported, their origin channels will be charted here."
    errorDescription="We could not load lead sources. Please try again."
    onRetry={onRetry}
    data-testid="lead-sources-chart"
  >
    <div className="h-72 w-full text-muted-foreground">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data.map((d) => ({ ...d, name: humanizeStatus(d.name) }))}
            dataKey="value"
            nameKey="name"
            cx="50%"
            cy="50%"
            innerRadius={55}
            outerRadius={90}
            paddingAngle={2}
          >
            {data.map((entry, index) => (
              <Cell key={entry.name} fill={PALETTE[index % PALETTE.length]} />
            ))}
          </Pie>
          <Tooltip {...TOOLTIP_STYLE} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  </DashboardSection>
);

// ==========================================
// 7b. LEAD STATUS DISTRIBUTION
// ==========================================

export interface LeadStatusChartProps extends BaseChartProps {
  data: ChartDatum[];
  isSampled?: boolean;
}

export const LeadStatusChart = ({
  data,
  isSampled = false,
  isLoading,
  isError,
  isEmpty,
  onRetry,
}: LeadStatusChartProps) => (
  <DashboardSection
    title="Lead Status Distribution"
    description={
      isSampled ? 'Pipeline spread (most recent 500 leads)' : 'How leads are spread across the pipeline'
    }
    icon={<BarChart3 className="h-4 w-4" />}
    isLoading={isLoading}
    isError={isError}
    isEmpty={isEmpty}
    emptyTitle="No status data"
    emptyDescription="Lead statuses will be charted here as your pipeline fills up."
    errorDescription="We could not load the status distribution. Please try again."
    onRetry={onRetry}
    data-testid="lead-status-chart"
  >
    <div className="h-72 w-full text-muted-foreground">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data.map((d) => ({ ...d, name: humanizeStatus(d.name) }))}
          margin={{ top: 8, right: 8, bottom: 8, left: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" opacity={0.2} vertical={false} />
          {/* Angled labels: status names like "Message Sent" collide when horizontal. */}
          <XAxis
            dataKey="name"
            tick={AXIS_STYLE}
            interval={0}
            angle={-35}
            textAnchor="end"
            height={70}
          />
          <YAxis tick={AXIS_STYLE} allowDecimals={false} width={35} />
          <Tooltip {...TOOLTIP_STYLE} cursor={{ opacity: 0.1 }} />
          <Bar dataKey="value" name="Leads" radius={[4, 4, 0, 0]}>
            {data.map((entry, index) => (
              <Cell key={entry.name} fill={PALETTE[index % PALETTE.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  </DashboardSection>
);

// ==========================================
// 7c. DAILY LEAD GROWTH
// ==========================================

export interface DailyGrowthChartProps extends BaseChartProps {
  data: DailyGrowthDatum[];
}

export const DailyGrowthChart = ({
  data,
  isLoading,
  isError,
  isEmpty,
  onRetry,
}: DailyGrowthChartProps) => (
  <DashboardSection
    title="Daily Lead Growth"
    description="New leads captured per day"
    icon={<LineChartIcon className="h-4 w-4" />}
    isLoading={isLoading}
    isError={isError}
    isEmpty={isEmpty}
    emptyTitle="No growth data"
    emptyDescription="Daily lead counts will be plotted here once leads start arriving."
    errorDescription="We could not load lead growth. Please try again."
    onRetry={onRetry}
    data-testid="daily-growth-chart"
  >
    <div className="h-72 w-full text-muted-foreground">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.2} vertical={false} />
          {/* Ticks are shortened to "05 Aug"; the tooltip keeps the full date. */}
          <XAxis
            dataKey="date"
            tick={AXIS_STYLE}
            tickFormatter={(value: string) => dayjs(value).format('DD MMM')}
            minTickGap={16}
          />
          <YAxis tick={AXIS_STYLE} allowDecimals={false} width={35} />
          <Tooltip
            {...TOOLTIP_STYLE}
            labelFormatter={(value) => dayjs(String(value)).format('DD MMM YYYY')}
          />
          <Line
            type="monotone"
            dataKey="count"
            name="New leads"
            stroke={PALETTE[0]}
            strokeWidth={2}
            dot={{ r: 2.5 }}
            activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  </DashboardSection>
);

// ==========================================
// 7d. CAMPAIGN PERFORMANCE
// ==========================================

export interface CampaignPerformanceChartProps extends BaseChartProps {
  data: CampaignPerformanceDatum[];
}

export const CampaignPerformanceChart = ({
  data,
  isLoading,
  isError,
  isEmpty,
  onRetry,
}: CampaignPerformanceChartProps) => (
  <DashboardSection
    title="Campaign Performance"
    description="Sent, delivered, read and replied per campaign"
    icon={<Activity className="h-4 w-4" />}
    isLoading={isLoading}
    isError={isError}
    isEmpty={isEmpty}
    emptyTitle="No campaign data"
    emptyDescription="Campaign delivery funnels will be charted here once you send one."
    errorDescription="We could not load campaign performance. Please try again."
    onRetry={onRetry}
    data-testid="campaign-performance-chart"
  >
    <div className="h-72 w-full text-muted-foreground">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.2} vertical={false} />
          <XAxis
            dataKey="name"
            tick={AXIS_STYLE}
            interval={0}
            angle={-20}
            textAnchor="end"
            height={60}
            // Long campaign names are truncated on the axis; the tooltip shows them whole.
            tickFormatter={(value: string) =>
              value.length > 14 ? `${value.slice(0, 14)}…` : value
            }
          />
          <YAxis tick={AXIS_STYLE} allowDecimals={false} width={35} />
          <Tooltip {...TOOLTIP_STYLE} cursor={{ opacity: 0.1 }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="sent" name="Sent" fill={PALETTE[0]} radius={[3, 3, 0, 0]} />
          <Bar dataKey="delivered" name="Delivered" fill={PALETTE[1]} radius={[3, 3, 0, 0]} />
          <Bar dataKey="read" name="Read" fill={PALETTE[2]} radius={[3, 3, 0, 0]} />
          <Bar dataKey="replied" name="Replied" fill={PALETTE[3]} radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  </DashboardSection>
);
