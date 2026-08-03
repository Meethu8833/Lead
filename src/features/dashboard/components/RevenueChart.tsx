import { Card, CardHeader, CardTitle, CardContent } from '../../../components/ui/Card';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { Order, DashboardFiltersState } from '../types';
import { formatCurrency } from '../../../utils/helpers';
import * as React from 'react';
import dayjs from 'dayjs';

interface RevenueChartProps {
  orders: Order[];
  filters: DashboardFiltersState;
}

export const RevenueChart = ({ orders, filters }: RevenueChartProps) => {
  const chartData = React.useMemo(() => {
    const dailyMap = new Map<string, number>();

    // Determine the date range based on filter
    let daysToInclude = 30; // default this month
    let dateFormat = 'MMM DD';

    if (filters.dateRange === 'today') {
      daysToInclude = 1;
      dateFormat = 'HH:00';
    } else if (filters.dateRange === 'week') {
      daysToInclude = 7;
      dateFormat = 'ddd';
    } else if (filters.dateRange === 'month') {
      daysToInclude = 30;
      dateFormat = 'MMM DD';
    } else if (filters.dateRange === 'custom') {
      const start = filters.startDate ? dayjs(filters.startDate) : dayjs().subtract(30, 'day');
      const end = filters.endDate ? dayjs(filters.endDate) : dayjs();
      daysToInclude = Math.max(1, end.diff(start, 'day') + 1);
      dateFormat = daysToInclude > 30 ? 'MMM YYYY' : 'MMM DD';
    }

    const now = dayjs();
    
    // Seed days with 0 to prevent empty/broken chart rendering
    if (filters.dateRange === 'custom' && filters.startDate && filters.endDate) {
      const start = dayjs(filters.startDate);
      for (let i = 0; i < daysToInclude; i++) {
        const d = start.add(i, 'day').format(dateFormat);
        dailyMap.set(d, 0);
      }
    } else if (filters.dateRange === 'today') {
      for (let i = 0; i < 24; i += 2) {
        const hourLabel = `${String(i).padStart(2, '0')}:00`;
        dailyMap.set(hourLabel, 0);
      }
    } else {
      for (let i = daysToInclude - 1; i >= 0; i--) {
        const d = now.subtract(i, 'day').format(dateFormat);
        dailyMap.set(d, 0);
      }
    }

    // Populate with actual order totals
    orders.forEach((order) => {
      const bookingDate = dayjs(order.booking_date);
      let label = '';
      
      if (filters.dateRange === 'today') {
        const hour = bookingDate.hour();
        // round to nearest seed hour block
        const nearestHour = Math.floor(hour / 2) * 2;
        label = `${String(nearestHour).padStart(2, '0')}:00`;
      } else {
        label = bookingDate.format(dateFormat);
      }

      if (dailyMap.has(label)) {
        const existing = dailyMap.get(label) || 0;
        dailyMap.set(label, existing + order.total_amount);
      } else if (filters.dateRange === 'custom') {
        // Fallback for custom range to avoid missing dates
        dailyMap.set(label, (dailyMap.get(label) || 0) + order.total_amount);
      }
    });

    // Convert map to recharts array format
    return Array.from(dailyMap.entries()).map(([date, revenue]) => ({
      date,
      revenue,
    }));
  }, [orders, filters]);

  // Dynamic colors for dark-mode
  const isDark = document.documentElement.classList.contains('dark');
  const primaryColor = isDark ? '#a78bfa' : '#4f46e5'; // Purple-400 / Indigo-600
  const gradientColor = isDark ? '#7c3aed' : '#818cf8';

  return (
    <Card className="w-full h-80 flex flex-col" data-testid="revenue-chart-card">
      <CardHeader className="pb-2">
        <CardTitle className="text-lg font-bold">Revenue Trend</CardTitle>
      </CardHeader>
      <CardContent className="flex-1 w-full min-h-0">
        <ResponsiveContainer width="100%" height="100%" data-testid="revenue-chart-container">
          <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="revenueGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={gradientColor} stopOpacity={0.4} />
                <stop offset="95%" stopColor={gradientColor} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={isDark ? '#27272a' : '#e4e4e7'} />
            <XAxis
              dataKey="date"
              tickLine={false}
              axisLine={false}
              tick={{ fill: '#71717a', fontSize: 10 }}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              tickFormatter={(val) => `₹${val}`}
              tick={{ fill: '#71717a', fontSize: 10 }}
            />
            <Tooltip
              formatter={(val: any) => [formatCurrency(Number(val) || 0), 'Revenue']}
              contentStyle={{
                backgroundColor: isDark ? '#09090b' : '#ffffff',
                border: `1px solid ${isDark ? '#27272a' : '#e4e4e7'}`,
                borderRadius: '8px',
                color: isDark ? '#fafafa' : '#09090b',
                fontSize: '12px',
              }}
            />
            <Area
              type="monotone"
              dataKey="revenue"
              stroke={primaryColor}
              strokeWidth={2}
              fillOpacity={1}
              fill="url(#revenueGradient)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
};
