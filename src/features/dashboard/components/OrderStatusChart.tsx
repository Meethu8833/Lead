import { Card, CardHeader, CardTitle, CardContent } from '../../../components/ui/Card';
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { Order } from '../types';
import * as React from 'react';

interface OrderStatusChartProps {
  orders: Order[];
}

export const OrderStatusChart = ({ orders }: OrderStatusChartProps) => {
  const chartData = React.useMemo(() => {
    const statusCounts: Record<string, number> = {};

    orders.forEach((o) => {
      const status = o.status || 'RECEIVED';
      statusCounts[status] = (statusCounts[status] || 0) + 1;
    });

    return Object.entries(statusCounts).map(([name, value]) => ({
      name: name.replace('_', ' ').toLowerCase(),
      value,
    }));
  }, [orders]);

  // Color palette map for statuses
  const COLORS: Record<string, string> = {
    delivered: '#10b981', // emerald-500
    ready: '#0ea5e9',     // sky-500
    cancelled: '#f43f5e', // rose-500
    printing: '#f59e0b',   // amber-500
    designing: '#6366f1',  // indigo-500
    editing: '#8b5cf6',    // violet-500
    received: '#6b7280',   // gray-500
    lamination: '#ec4899', // pink-500
    packing: '#14b8a6',    // teal-500
    'color correction': '#a855f7', // purple-500
    'quality check': '#06b6d4',    // cyan-500
  };

  const getStatusColor = (statusName: string) => {
    return COLORS[statusName] || '#94a3b8'; // slate-400 fallback
  };

  const isDark = document.documentElement.classList.contains('dark');

  return (
    <Card className="w-full h-80 flex flex-col" data-testid="order-status-chart-card">
      <CardHeader className="pb-2">
        <CardTitle className="text-lg font-bold">Status Distribution</CardTitle>
      </CardHeader>
      <CardContent className="flex-1 w-full min-h-0 flex items-center justify-center">
        {chartData.length === 0 ? (
          <p className="text-sm text-muted-foreground py-8">
            No status data available
          </p>
        ) : (
          <ResponsiveContainer width="100%" height="100%" data-testid="status-chart-container">
            <PieChart>
              <Pie
                data={chartData}
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={80}
                paddingAngle={3}
                dataKey="value"
              >
                {chartData.map((entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={getStatusColor(entry.name)}
                  />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  backgroundColor: isDark ? '#09090b' : '#ffffff',
                  border: `1px solid ${isDark ? '#27272a' : '#e4e4e7'}`,
                  borderRadius: '8px',
                  color: isDark ? '#fafafa' : '#09090b',
                  fontSize: '12px',
                }}
              />
              <Legend
                verticalAlign="bottom"
                height={36}
                iconSize={10}
                iconType="circle"
                wrapperStyle={{ fontSize: '11px', textTransform: 'capitalize' }}
              />
            </PieChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
};
