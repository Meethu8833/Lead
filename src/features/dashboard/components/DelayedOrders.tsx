import { Card, CardHeader, CardTitle, CardContent } from '../../../components/ui/Card';
import { StatusBadge } from '../../../components/ui/StatusBadge';
import { Badge } from '../../../components/ui/Badge';
import { formatDate } from '../../../utils/helpers';
import { Order, Photographer } from '../types';
import { AlertCircle } from 'lucide-react';
import * as React from 'react';

interface DelayedOrdersProps {
  orders: Order[];
  photographers: Photographer[];
}

export const DelayedOrders = ({ orders, photographers }: DelayedOrdersProps) => {
  const photographerMap = React.useMemo(() => {
    const map = new Map<string, Photographer>();
    photographers.forEach((p) => map.set(p.id, p));
    return map;
  }, [photographers]);

  const delayedOrdersList = React.useMemo(() => {
    const now = new Date();
    return orders
      .filter((o) => {
        if (!o.expected_delivery_date) return false;
        const expectedDate = new Date(o.expected_delivery_date);
        const isOverdue = expectedDate < now;
        const isNotFinished = o.status !== 'DELIVERED' && o.status !== 'CANCELLED';
        return isOverdue && isNotFinished;
      })
      .map((o) => {
        const photo = photographerMap.get(o.photographer_id);
        return {
          ...o,
          photographerName: photo ? photo.name : 'Unknown',
          studioName: photo ? photo.studio_name : 'Unknown',
        };
      });
  }, [orders, photographerMap]);

  return (
    <Card className="border-rose-200 dark:border-rose-950/40 h-full flex flex-col" data-testid="delayed-orders-card">
      <CardHeader className="flex flex-row items-center gap-2 text-rose-700 dark:text-rose-400">
        <AlertCircle className="h-5 w-5 shrink-0" />
        <CardTitle className="text-lg font-bold">Delayed & Overdue Orders</CardTitle>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto">
        {delayedOrdersList.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-4">
            No delayed orders. Good job!
          </p>
        ) : (
          <div className="space-y-4" data-testid="delayed-orders-list">
            {delayedOrdersList.map((order, idx) => (
              <div
                key={idx}
                className="flex flex-col gap-2 p-3 rounded-lg border border-rose-100 bg-rose-50/20 dark:border-rose-950/20 dark:bg-rose-950/5"
                data-testid={`delayed-order-item-${idx}`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-rose-700 dark:text-rose-400">
                    {order.order_number}
                  </span>
                  <StatusBadge status="failed">{order.status}</StatusBadge>
                </div>
                <div className="text-xs text-muted-foreground space-y-1">
                  <div>
                    <span className="font-semibold text-foreground">Job: </span>
                    {order.job_name}
                  </div>
                  <div>
                    <span className="font-semibold text-foreground">Photographer: </span>
                    {order.photographerName} ({order.studioName})
                  </div>
                  <div className="flex items-center gap-1.5 pt-1">
                    <span className="font-semibold text-foreground">Expected: </span>
                    <Badge variant="danger" size="sm">
                      {formatDate(order.expected_delivery_date)}
                    </Badge>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
};
