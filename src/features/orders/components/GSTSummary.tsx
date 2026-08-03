import * as React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../../../components/ui/Card';
import { Badge } from '../../../components/ui/Badge';
import { formatCurrency } from '../../../utils/helpers';
import { DEFAULT_GST_PERCENTAGE } from '../types';

const round2 = (value: number) => Math.round(value * 100) / 100;

const Field = ({ label, value }: { label: string; value: React.ReactNode }) => (
  <div className="flex flex-col gap-0.5">
    <span className="text-xs font-medium text-muted-foreground">{label}</span>
    <span className="text-sm font-semibold text-foreground">{value}</span>
  </div>
);

interface GSTSummaryProps {
  taxableValue: number;
  gstPercentage?: number;
}

// GST does not exist on Order/OrderItem in the backend (only on the separate Invoice model,
// out of scope this phase) — this is a client-side-only estimate for planning purposes. It is
// never read from or sent to the backend, and is clearly labeled as an estimate so it can't be
// mistaken for the order's real, invoiced total.
export const GSTSummary = ({ taxableValue, gstPercentage = DEFAULT_GST_PERCENTAGE }: GSTSummaryProps) => {
  const gstAmount = round2(taxableValue * (gstPercentage / 100));
  const finalTotal = round2(taxableValue + gstAmount);

  return (
    <Card data-testid="gst-summary">
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          GST Summary
          <Badge variant="secondary" size="sm" data-testid="gst-summary-estimate-badge">
            Estimate
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Field label="Taxable Value" value={formatCurrency(taxableValue)} />
        <Field label="GST %" value={`${gstPercentage}%`} />
        <Field label="GST Amount" value={formatCurrency(gstAmount)} />
        <Field label="Final Total (est.)" value={<span data-testid="gst-summary-final-total">{formatCurrency(finalTotal)}</span>} />
      </CardContent>
      <p className="px-6 pb-4 text-xs text-muted-foreground">
        Estimate only — actual GST is calculated when an invoice is generated. Not sent to or stored by the order.
      </p>
    </Card>
  );
};
