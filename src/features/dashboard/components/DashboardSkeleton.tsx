import { Skeleton } from '../../../components/ui/Skeleton';
import { PageContainer } from '../../../components/ui/LayoutHelpers';

export const DashboardSkeleton = () => {
  return (
    <PageContainer data-testid="dashboard-skeleton">
      {/* Filters Bar Skeleton */}
      <div className="h-14 w-full bg-card border border-border/80 rounded-lg p-3 flex justify-between items-center">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-8 w-24" />
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, idx) => (
          <div
            key={idx}
            className="border rounded-lg p-6 bg-card flex flex-col justify-between gap-4 h-36"
          >
            <div className="flex justify-between items-center">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-8 w-8 rounded-md" />
            </div>
            <Skeleton className="h-8 w-32" />
            <Skeleton className="h-3 w-16" />
          </div>
        ))}
      </div>

      {/* Secondary KPI Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, idx) => (
          <div
            key={idx}
            className="border rounded-lg p-4 bg-card flex flex-col justify-between gap-3 h-28"
          >
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-6 w-16" />
            <Skeleton className="h-3 w-28" />
          </div>
        ))}
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 border rounded-lg p-6 bg-card h-80 flex flex-col gap-4">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="flex-1 w-full" />
        </div>
        <div className="border rounded-lg p-6 bg-card h-80 flex flex-col gap-4">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="flex-1 w-full" />
        </div>
      </div>

      {/* Tables & Lists row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 border rounded-lg p-6 bg-card h-96 flex flex-col gap-4">
          <div className="flex justify-between">
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-8 w-40" />
          </div>
          <Skeleton className="flex-1 w-full" />
        </div>
        <div className="border rounded-lg p-6 bg-card h-96 flex flex-col gap-4">
          <Skeleton className="h-5 w-32" />
          <div className="flex-1 flex flex-col gap-3">
            {Array.from({ length: 5 }).map((_, idx) => (
              <div key={idx} className="flex justify-between items-center py-2 border-b border-border/40">
                <div className="flex items-center gap-2">
                  <Skeleton className="h-8 w-8 rounded-full" />
                  <div className="flex flex-col gap-1">
                    <Skeleton className="h-3 w-24" />
                    <Skeleton className="h-2 w-16" />
                  </div>
                </div>
                <Skeleton className="h-3 w-12" />
              </div>
            ))}
          </div>
        </div>
      </div>
    </PageContainer>
  );
};
