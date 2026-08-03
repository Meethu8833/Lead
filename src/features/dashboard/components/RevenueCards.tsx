import { KpiCard } from '../../../components/ui/KpiCard';
import { DollarSign, CreditCard, Wallet } from 'lucide-react';
import { formatCurrency } from '../../../utils/helpers';
import { DashboardStats } from '../types';

interface RevenueCardsProps {
  stats: DashboardStats;
  loading: boolean;
}

export const RevenueCards = ({ stats, loading }: RevenueCardsProps) => {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="revenue-cards">
      <KpiCard
        title="Revenue Today"
        value={formatCurrency(stats.revenue_today)}
        icon={<DollarSign className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />}
        percentageChange={12}
        comparisonLabel="vs. yesterday"
        loading={loading}
      />
      <KpiCard
        title="Revenue This Month"
        value={formatCurrency(stats.revenue_this_month)}
        icon={<CreditCard className="h-5 w-5 text-primary" />}
        percentageChange={8.4}
        comparisonLabel="vs. last month"
        loading={loading}
      />
      <KpiCard
        title="Outstanding Balance"
        value={formatCurrency(stats.outstanding_balance)}
        icon={<Wallet className="h-5 w-5 text-rose-600 dark:text-rose-400" />}
        percentageChange={-2.5}
        comparisonLabel="vs. last week"
        loading={loading}
      />
    </div>
  );
};
