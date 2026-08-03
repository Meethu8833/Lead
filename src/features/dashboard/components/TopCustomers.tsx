import { Card, CardHeader, CardTitle, CardContent } from '../../../components/ui/Card';
import { Avatar } from '../../../components/ui/Avatar';
import { formatCurrency } from '../../../utils/helpers';
import { TopCustomer, Order, Photographer } from '../types';
import * as React from 'react';

interface TopCustomersProps {
  topCustomers: TopCustomer[];
  orders: Order[];
  photographers: Photographer[];
}

export const TopCustomers = ({
  topCustomers,
  orders,
  photographers,
}: TopCustomersProps) => {
  const customerList = React.useMemo(() => {
    return topCustomers.map((cust) => {
      // Find matching photographer in the CRM list
      const matchingPhotographer = photographers.find(
        (p) => p.name.toLowerCase() === cust.name.toLowerCase()
      );

      let orderCount = 0;
      let studioName = 'Freelance Photographer';

      if (matchingPhotographer) {
        studioName = matchingPhotographer.studio_name;
        // Count orders placed by this photographer ID
        orderCount = orders.filter(
          (o) => o.photographer_id === matchingPhotographer.id
        ).length;
      }

      // If we don't find orders from database, use spent to approximate
      if (orderCount === 0) {
        orderCount = Math.max(1, Math.floor(cust.total_spent / 300));
      }

      // Get Initials
      const initials = cust.name
        .split(' ')
        .map((part) => part[0])
        .join('')
        .slice(0, 2)
        .toUpperCase();

      return {
        ...cust,
        studioName,
        orderCount,
        initials,
      };
    });
  }, [topCustomers, orders, photographers]);

  return (
    <Card className="h-full flex flex-col" data-testid="top-customers-card">
      <CardHeader>
        <CardTitle className="text-lg font-bold">Top Customers</CardTitle>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto">
        {customerList.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-4">
            No customer data available
          </p>
        ) : (
          <div className="space-y-4" data-testid="top-customers-list">
            {customerList.map((cust, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between py-2 border-b border-border/40 last:border-b-0"
                data-testid={`top-customer-item-${idx}`}
              >
                <div className="flex items-center gap-3">
                  <Avatar fallback={cust.initials} size="md" />
                  <div className="flex flex-col">
                    <span className="text-sm font-semibold text-foreground">
                      {cust.name}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {cust.studioName}
                    </span>
                  </div>
                </div>
                <div className="text-right">
                  <span className="text-sm font-bold text-foreground block">
                    {formatCurrency(cust.total_spent)}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {cust.orderCount} {cust.orderCount === 1 ? 'order' : 'orders'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
};
