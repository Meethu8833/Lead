import { StatCard } from '../../../components/ui/StatCard';
import {
  Activity,
  CheckCircle2,
  AlertTriangle,
  Truck,
  Users,
  Award,
  ShoppingBag,
} from 'lucide-react';
import { DashboardStats } from '../types';

interface ProductionOverviewProps {
  stats: DashboardStats;
  activeCustomersCount: number;
  loading: boolean;
}

export const ProductionOverview = ({
  stats,
  activeCustomersCount,
  loading,
}: ProductionOverviewProps) => {
  const topProduct = stats.top_products?.[0]?.product_name || 'N/A';
  const topPhotographer = stats.top_customers?.[0]?.name || 'N/A';

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4" data-testid="production-overview">
      <StatCard
        title="Orders In Progress"
        value={stats.pending_production}
        icon={<Activity className="h-5 w-5 text-amber-500" />}
        loading={loading}
      />
      <StatCard
        title="Completed Orders"
        value={stats.orders_delivered_today}
        icon={<CheckCircle2 className="h-5 w-5 text-emerald-500" />}
        loading={loading}
      />
      <StatCard
        title="Delayed Orders"
        value={stats.delayed_orders}
        icon={<AlertTriangle className="h-5 w-5 text-rose-500" />}
        loading={loading}
      />
      <StatCard
        title="Pending Deliveries"
        value={stats.pending_deliveries}
        icon={<Truck className="h-5 w-5 text-sky-500" />}
        loading={loading}
      />
      <StatCard
        title="Active Customers"
        value={activeCustomersCount}
        icon={<Users className="h-5 w-5 text-indigo-500" />}
        loading={loading}
      />
      <StatCard
        title="Top Product"
        value={topProduct}
        icon={<ShoppingBag className="h-5 w-5 text-violet-500" />}
        loading={loading}
      />
      <StatCard
        title="Top Photographer"
        value={topPhotographer}
        icon={<Award className="h-5 w-5 text-yellow-500" />}
        loading={loading}
      />
    </div>
  );
};
